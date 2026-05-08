#!/usr/bin/env python3
"""Local-first AI router for FUNDz owner questions.

Routing order:

1. Local deterministic FUNDz tools should run before this module.
2. Local AI on this Mac, currently Ollama, if available.
3. Paid/cloud AI only when enabled and the prompt passes the privacy gate.

The default stance is conservative: anything that looks like client, money,
credit, phone, inbox, billing, or dispute context does not go to paid AI unless
the operator intentionally changes the local environment policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fundz_autonomy_daemon import redact_text
from fundz_credit_tracker_bridge import load_env_file


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = ROOT / "data" / "local" / "owner-command-mode" / "ai-router-receipts.jsonl"

SYSTEM_PROMPT = (
    "You are FUNDz's private assistant for Brandon. Keep answers short, practical, "
    "and clear. Do not claim you accessed live client records unless the user "
    "provided the facts in the prompt. Do not give legal, financial, or credit "
    "repair guarantees."
)

SENSITIVE_RE = re.compile(
    r"("
    r"\bclient\b|\bcustomer\b|\bmember\b|\blead\b|\bcase\b|\bdispute\b|"
    r"\bdisputefox\b|\bhighlevel\b|\bcredit\s*(?:score|report|repair|file)?\b|"
    r"\btradeline\b|\bround\s*\d+\b|\bimport\b|\bonboarding\b|"
    r"\bbilling\b|\bpayment\b|\bpaid\b|\bowe\b|\bcollected\b|\brevenue\b|"
    r"\bimessage\b|\bsms\b|\bphone\b|\bemail\b|\binbox\b|"
    r"\bupdate\s+(?:on|for|about)\b|\bstatus\s+(?:on|for|about)\b|"
    r"\brecord\s+(?:on|for|about)\b|"
    r"\$\s*\d+|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    r")",
    re.IGNORECASE,
)
CAPITALIZED_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")
PAID_APPROVAL_RE = re.compile(
    r"\b(?:approve|approved|use|send\s+to)\s+(?:the\s+)?(?:paid\s+)?ai\b|"
    r"\bpaid\s+ai\s*:",
    re.IGNORECASE,
)
ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\)|\x1B[@-Z\\-_])"
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class AIResponse:
    ok: bool
    text: str
    provider: str
    model: str
    error: str = ""


@dataclass(frozen=True)
class AIRouteResult:
    route: str
    reply: str
    sensitive: bool
    paid_approved: bool
    provider: str = ""
    model: str = ""
    reason: str = ""


def env_bool(name: str, default: bool = False, env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    raw = str(values.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def receipt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def append_receipt(row: dict[str, Any]) -> None:
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RECEIPT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def is_sensitive_prompt(prompt: str) -> bool:
    text = prompt or ""
    if SENSITIVE_RE.search(text):
        return True
    # A full-looking proper name in a business command is treated as private.
    if CAPITALIZED_NAME_RE.search(text) and re.search(r"\b(update|status|record|paid|owe|credit|file)\b", text, re.I):
        return True
    return False


def paid_ai_approved(prompt: str) -> bool:
    return bool(PAID_APPROVAL_RE.search(prompt or ""))


def strip_paid_approval(prompt: str) -> str:
    cleaned = PAID_APPROVAL_RE.sub("", prompt or "")
    return re.sub(r"\s+", " ", cleaned).strip(" :-")


def clean_model_text(text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", text or "")
    cleaned = CONTROL_CHAR_RE.sub("", cleaned)
    return cleaned.strip()


def safe_prompt_for_paid(prompt: str, sensitive: bool, allow_sensitive_raw: bool) -> str:
    cleaned = strip_paid_approval(prompt)
    if sensitive and not allow_sensitive_raw:
        return redact_text(cleaned)
    return cleaned


def call_ollama(prompt: str, env: dict[str, str] | None = None) -> AIResponse:
    values = os.environ if env is None else env
    binary = values.get("FUNDZ_AI_OLLAMA_BIN") or shutil.which("ollama")
    model = values.get("FUNDZ_AI_LOCAL_MODEL", "llama3.2:3b")
    if not binary:
        return AIResponse(False, "", "ollama", model, "Ollama is not installed on this Mac.")
    timeout = int(values.get("FUNDZ_AI_TIMEOUT_SECONDS", "90") or "90")
    full_prompt = f"{SYSTEM_PROMPT}\n\nQuestion:\n{prompt.strip()}"
    completed = subprocess.run(
        [binary, "run", "--nowordwrap", model, full_prompt],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        return AIResponse(False, "", "ollama", model, completed.stderr.strip() or "Ollama returned an error.")
    text = clean_model_text(completed.stdout)
    if not text:
        return AIResponse(False, "", "ollama", model, "Ollama returned an empty answer.")
    return AIResponse(True, text, "ollama", model)


def call_openai(prompt: str, env: dict[str, str] | None = None) -> AIResponse:
    values = os.environ if env is None else env
    api_key = values.get("OPENAI_API_KEY", "").strip()
    model = values.get("FUNDZ_AI_PAID_MODEL", "gpt-5.4-mini")
    if not api_key:
        return AIResponse(False, "", "openai", model, "OPENAI_API_KEY is not configured.")
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_output_tokens": int(values.get("FUNDZ_AI_MAX_OUTPUT_TOKENS", "600") or "600"),
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(values.get("FUNDZ_AI_TIMEOUT_SECONDS", "90") or "90")) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return AIResponse(False, "", "openai", model, str(error))
    text = str(data.get("output_text") or "").strip()
    if not text:
        parts: list[str] = []
        output_items = data.get("output", [])
        for item in output_items if isinstance(output_items, list) else []:
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(content, dict) and content.get("text"):
                    parts.append(str(content["text"]))
        text = "\n".join(parts).strip()
    if not text:
        return AIResponse(False, "", "openai", model, "OpenAI returned an empty answer.")
    return AIResponse(True, text, "openai", model)


def call_groq(prompt: str, env: dict[str, str] | None = None) -> AIResponse:
    values = os.environ if env is None else env
    api_key = values.get("GROQ_API_KEY", "").strip()
    model = values.get("FUNDZ_AI_PAID_MODEL", "llama-3.1-8b-instant")
    if not api_key:
        return AIResponse(False, "", "groq", model, "GROQ_API_KEY is not configured.")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": int(values.get("FUNDZ_AI_MAX_OUTPUT_TOKENS", "600") or "600"),
    }
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(values.get("FUNDZ_AI_TIMEOUT_SECONDS", "90") or "90")) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return AIResponse(False, "", "groq", model, str(error))
    choices = data.get("choices") if isinstance(data, dict) else []
    text = ""
    if choices and isinstance(choices[0], dict):
        text = str(choices[0].get("message", {}).get("content") or "").strip()
    if not text:
        return AIResponse(False, "", "groq", model, "Groq returned an empty answer.")
    return AIResponse(True, text, "groq", model)


def call_paid(prompt: str, env: dict[str, str] | None = None) -> AIResponse:
    values = os.environ if env is None else env
    provider = values.get("FUNDZ_AI_PAID_PROVIDER", "openai").strip().lower()
    if provider == "groq":
        return call_groq(prompt, values)
    return call_openai(prompt, values)


def route_question(
    prompt: str,
    env: dict[str, str] | None = None,
    local_caller: Callable[[str, dict[str, str] | None], AIResponse] = call_ollama,
    paid_caller: Callable[[str, dict[str, str] | None], AIResponse] = call_paid,
) -> AIRouteResult:
    values = os.environ if env is None else env
    prompt = (prompt or "").strip()
    sensitive = is_sensitive_prompt(prompt)
    approved = paid_ai_approved(prompt)

    if not prompt:
        return AIRouteResult("empty", "", sensitive, approved, reason="empty question")

    if env_bool("FUNDZ_AI_LOCAL_ENABLED", True, values):
        local = local_caller(strip_paid_approval(prompt), values)
        if local.ok:
            return AIRouteResult("local_ai", local.text, sensitive, approved, local.provider, local.model, "answered locally")
        local_reason = local.error
    else:
        local_reason = "local AI is disabled"

    paid_enabled = env_bool("FUNDZ_AI_PAID_ENABLED", False, values)
    paid_auto_for_safe = env_bool("FUNDZ_AI_PAID_AUTO_FOR_SAFE", True, values)
    allow_sensitive_raw = env_bool("FUNDZ_AI_PAID_ALLOW_SENSITIVE", False, values)

    if paid_enabled and (approved or (paid_auto_for_safe and not sensitive)):
        if sensitive and not allow_sensitive_raw:
            return AIRouteResult(
                "paid_blocked_sensitive",
                "I am keeping this local because it may include client, money, credit, phone, or inbox details. Local AI is not available right now. Send a generic version with no private details, or change the local FUNDz paid-AI policy before using cloud help for sensitive data.",
                sensitive,
                approved,
                reason="sensitive prompt blocked by paid-AI policy",
            )
        paid_prompt = safe_prompt_for_paid(prompt, sensitive, allow_sensitive_raw)
        paid = paid_caller(paid_prompt, values)
        if paid.ok:
            note = "" if not sensitive or allow_sensitive_raw else "\n\nNote: I removed obvious private details before using paid AI."
            return AIRouteResult("paid_ai", paid.text + note, sensitive, approved, paid.provider, paid.model, "answered by paid AI")
        return AIRouteResult(
            "paid_failed",
            f"Local AI is not available, and paid AI failed too. Local issue: {local_reason}. Paid issue: {paid.error}",
            sensitive,
            approved,
            paid.provider,
            paid.model,
            "paid provider failed",
        )

    if sensitive:
        reply = (
            "I am keeping this local because it may include client, money, credit, phone, or inbox details. "
            f"Local AI is not available right now: {local_reason}. "
            "For now I can still answer stored FUNDz commands like: update on Dedrick, daily board, or status for a client."
        )
    else:
        reply = (
            f"Local AI is not available right now: {local_reason}. "
            "Paid AI is not enabled for this router yet, so I did not send this question outside your Mac."
        )
    return AIRouteResult("no_ai_available", reply, sensitive, approved, reason=local_reason)


def route_with_receipt(prompt: str, env: dict[str, str] | None = None) -> AIRouteResult:
    result = route_question(prompt, env=env)
    append_receipt(
        {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "prompt_hash": receipt_hash(prompt),
            "prompt_preview": redact_text(prompt[:160]),
            "route": result.route,
            "sensitive": result.sensitive,
            "paid_approved": result.paid_approved,
            "provider": result.provider,
            "model": result.model,
            "reason": result.reason,
        }
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-paid", action="store_true", help="Enable paid AI for this one CLI run.")
    return parser.parse_args()


def main() -> int:
    load_env_file()
    args = parse_args()
    env = dict(os.environ)
    if args.allow_paid:
        env["FUNDZ_AI_PAID_ENABLED"] = "true"
    start = time.time()
    result = route_with_receipt(args.prompt, env=env)
    if args.json:
        payload = asdict(result)
        payload["duration_ms"] = int((time.time() - start) * 1000)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(result.reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
