#!/usr/bin/env python3
"""Deterministic iMessage fallback for FUNDz OpenClaw model outages.

OpenClaw normally routes iMessage text through an LLM session. When every model
provider fails before a reply, this script can answer a narrow set of safe owner
commands without model access:

- /new or /reset
- client update/status/details requests backed by local FUNDz data

It is intentionally not a general chat bot and does not send client-facing
outreach.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from fundz_client_billing_lookup import build_lookup as build_billing_lookup, monitoring_reply_text
from fundz_ai_router import route_with_receipt
from fundz_owner_command import load_env_file, normalize_phone, sender_allowed


ROOT = Path(__file__).resolve().parents[1]
OPENCLAW_SESSIONS_DIR = Path.home() / ".openclaw" / "agents" / "fundz" / "sessions"
OPENCLAW_SESSIONS_INDEX = OPENCLAW_SESSIONS_DIR / "sessions.json"
PROCESSED_PATH = ROOT / "data" / "local" / "owner-command-mode" / "imessage-fallback-processed.json"
RECEIPT_PATH = ROOT / "data" / "local" / "owner-command-mode" / "imessage-fallback-receipts.jsonl"
FUNDZ_UPDATE = ROOT / "scripts" / "fundz_update.py"
FUNDZ_COMMAND_CENTER = ROOT / "scripts" / "fundz_command_center.py"
OPENCLAW = str(Path.home() / ".local" / "bin" / "openclaw")

MODEL_ERROR_RE = re.compile(
    r"(insufficient credits|all models failed|rate limit|billing error|failed before reply)",
    re.IGNORECASE,
)
CLIENT_QUERY_RE = re.compile(
    r"\b(?:update|status|details)\b(?:\s+(?:on|for|about))?\s+(?:the\s+)?(.+)$",
    re.IGNORECASE,
)
MONITORING_TOPIC_RE = re.compile(
    r"\b(?:score\s*fusion|scorefusion|credit\s+monitor(?:ing)?|monitoring\s+agency|my\s*score\s*iq|myscoreiq|credit\s+tracker)\b",
    re.IGNORECASE,
)
MONITORING_NAME_PATTERNS = (
    re.compile(r"\bis\s+(.+?)\s+(?:active|in|on|using|with|enrolled|found|showing)\b", re.IGNORECASE),
    re.compile(r"\b(?:for|about|on)\s+(.+?)\s+(?:in|on|using|with|active|score\s*fusion|scorefusion|credit\s+monitor)", re.IGNORECASE),
    re.compile(r"\b(?:look\s*up|check|verify|find)\s+(.+?)\s+(?:in|on|for|score\s*fusion|scorefusion|credit\s+monitor|monitoring)", re.IGNORECASE),
)
DAILY_BOARD_RE = re.compile(
    r"\b(?:daily board|today'?s board|what should i do next|next action|what'?s next)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FallbackCandidate:
    key: str
    sender: str
    message: str
    session_file: Path
    user_message_id: str
    error: str


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_receipt(row: dict[str, Any]) -> None:
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RECEIPT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def session_sender_map(index_path: Path = OPENCLAW_SESSIONS_INDEX) -> dict[Path, str]:
    data = read_json(index_path)
    result: dict[Path, str] = {}
    if not isinstance(data, dict):
        return result
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        session_file = value.get("sessionFile")
        session_key = str(value.get("sessionKey") or key)
        match = re.search(r"imessage:direct:(\+\d+)", session_key, re.IGNORECASE)
        if session_file and match:
            result[Path(session_file)] = match.group(1)
    return result


def parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def strip_metadata(text: str) -> str:
    cleaned = re.sub(r"Conversation info \(untrusted metadata\):\s*```json\s*.*?```", "", text, flags=re.S)
    cleaned = re.sub(r"Sender \(untrusted metadata\):\s*```json\s*.*?```", "", cleaned, flags=re.S)
    cleaned = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def compact_text(text: str, limit: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def metadata_json(text: str, label: str) -> dict[str, Any]:
    pattern = re.escape(label) + r"\s*```json\s*(.*?)```"
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_model_error(message: dict[str, Any]) -> tuple[bool, str]:
    error_text = str(message.get("errorMessage") or "")
    stop_reason = str(message.get("stopReason") or "")
    if stop_reason == "error" or MODEL_ERROR_RE.search(error_text):
        return True, error_text or stop_reason
    return False, ""


def user_text_and_sender(message: dict[str, Any], session_sender: str = "") -> tuple[str, str, str]:
    content = message.get("content") or []
    if not isinstance(content, list) or not content:
        return "", session_sender, str(message.get("id") or "")
    text = "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    conversation = metadata_json(text, "Conversation info (untrusted metadata):")
    sender = str(conversation.get("sender_id") or conversation.get("sender") or session_sender or "")
    user_message_id = str(conversation.get("message_id") or message.get("id") or "")
    stripped = strip_metadata(text)
    if stripped.startswith("A new session was started via /new or /reset"):
        stripped = "/new"
    return stripped, sender, user_message_id


def iter_session_files(sessions_dir: Path, since: datetime) -> Iterable[Path]:
    if not sessions_dir.exists():
        return []
    files = sorted(sessions_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [path for path in files if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) >= since]


def fallback_candidates(
    sessions_dir: Path = OPENCLAW_SESSIONS_DIR,
    since_minutes: int = 240,
) -> list[FallbackCandidate]:
    since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    senders = session_sender_map()
    candidates: list[FallbackCandidate] = []

    for session_file in iter_session_files(sessions_dir, since):
        session_sender = senders.get(session_file, "")
        last_user: tuple[str, str, str, str] | None = None
        for line in session_file.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = parse_timestamp(str(event.get("timestamp") or ""))
            if timestamp and timestamp < since:
                continue
            if event.get("type") != "message":
                continue
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            role = message.get("role")
            if role == "user":
                text, sender, user_message_id = user_text_and_sender(message, session_sender)
                if text and sender:
                    last_user = (text, sender, user_message_id, str(event.get("id") or message.get("id") or ""))
                continue
            if role != "assistant" or not last_user:
                continue
            failed, error = is_model_error(message)
            if not failed:
                last_user = None
                continue
            text, sender, user_message_id, event_id = last_user
            normalized_sender = normalize_phone(sender)
            key = f"{normalized_sender}:{user_message_id or event_id}:{text[:80]}"
            candidates.append(
                FallbackCandidate(
                    key=key,
                    sender=sender,
                    message=text,
                    session_file=session_file,
                    user_message_id=user_message_id or event_id,
                    error=error,
                )
            )
            last_user = None
    deduped: dict[str, FallbackCandidate] = {}
    for candidate in candidates:
        deduped.setdefault(candidate.key, candidate)
    return list(deduped.values())


def client_query_from_message(message: str) -> str:
    match = CLIENT_QUERY_RE.search(message)
    if not match:
        return ""
    query = match.group(1)
    query = re.sub(r"\b(?:please|pls|thanks|thank you|right now|today)\b.*$", "", query, flags=re.I)
    query = query.strip(" .?!,:;")
    return "" if query.lower() in {"me", "my file", "my account", "an update", "a update"} else query


def clean_client_name_query(query: str) -> str:
    query = re.sub(r"\b(?:please|pls|thanks|thank you|right now|today|her|his|their|the)\b", "", query, flags=re.I)
    query = re.sub(r"\b(?:score\s*fusion|scorefusion|credit\s+monitor(?:ing)?|monitoring\s+agency|my\s*score\s*iq|myscoreiq|credit\s+tracker)\b", "", query, flags=re.I)
    query = re.sub(r"'s\b", "", query)
    query = re.sub(r"\s+", " ", query)
    return query.strip(" .?!,:;-")


def monitoring_query_from_message(message: str) -> str:
    command = message.strip()
    if not MONITORING_TOPIC_RE.search(command):
        return ""
    for pattern in MONITORING_NAME_PATTERNS:
        match = pattern.search(command)
        if match:
            query = clean_client_name_query(match.group(1))
            if query and query.lower() not in {"me", "my file", "my account", "she", "he", "they"}:
                return query
    names = [name for name in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b", command) if name.lower() not in {"scorefusion", "credit tracker", "myscoreiq"}]
    return names[0].strip() if names else ""


def build_monitoring_reply(client_name: str) -> str:
    result = build_billing_lookup(client_name)
    return monitoring_reply_text(result)


def build_reply(message: str) -> tuple[str, str]:
    command = message.strip()
    if command.lower() in {"/new", "/reset", "new session", "reset session"}:
        return (
            "new_session",
            "FUNDz reset is live. Model providers are down right now, but I can still answer stored client updates. Try: update on Dedrick.",
        )

    if DAILY_BOARD_RE.search(command):
        return "daily_board", build_daily_board_reply()

    monitoring_query = monitoring_query_from_message(command)
    if monitoring_query:
        return "billing_monitoring", build_monitoring_reply(monitoring_query)

    query = client_query_from_message(command)
    if not query:
        try:
            ai_result = route_with_receipt(command)
        except Exception as error:  # pragma: no cover - defensive fallback for live iMessage safety.
            return "ai_router_error", f"I tried the local-first AI router, but it hit an error: {error}"
        return "ai_router", ai_result.reply

    completed = subprocess.run(
        [sys.executable, str(FUNDZ_UPDATE), "--client", query, "--reply-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    reply = completed.stdout.strip() if completed.returncode == 0 else ""
    if not reply:
        reply = (
            f"I could not build the stored FUNDz update for {query}. "
            "Check the local client export or send the full client name."
        )
    return "client_update", reply


def build_daily_board_reply() -> str:
    completed = subprocess.run(
        [sys.executable, str(FUNDZ_COMMAND_CENTER), "--limit", "10"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        return "I could not refresh the Daily Board locally. Check the A FUND Solution Command Center logs before doing live work."
    board_path = ROOT / "data" / "local" / "command-center" / "fundz-daily-board.md"
    try:
        text = board_path.read_text(encoding="utf-8")
    except OSError:
        return "Daily Board refreshed, but I could not read the local board file."
    useful = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not line.startswith("#")
        and not line.lower().startswith("generated:")
    ]
    return "\n".join(useful[:5])


def send_imessage(sender: str, reply: str, dry_run: bool) -> dict[str, Any]:
    args = [OPENCLAW, "message", "send", "--channel", "imessage", "--target", sender, "--message", reply, "--json"]
    if dry_run:
        args.append("--dry-run")
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=45, check=False)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "dry_run": dry_run,
    }


def run_fallback(since_minutes: int, dry_run: bool, limit: int) -> list[dict[str, Any]]:
    load_env_file()
    processed = read_json(PROCESSED_PATH)
    processed_keys = set(processed.get("processed_keys", [])) if isinstance(processed, dict) else set()
    attempt_counts = processed.get("attempt_counts", {}) if isinstance(processed, dict) else {}
    if not isinstance(attempt_counts, dict):
        attempt_counts = {}
    max_attempts = int(os.getenv("FUNDZ_IMESSAGE_FALLBACK_MAX_ATTEMPTS", "3") or "3")
    results: list[dict[str, Any]] = []

    for candidate in fallback_candidates(since_minutes=since_minutes):
        if candidate.key in processed_keys:
            continue
        attempts = int(attempt_counts.get(candidate.key, 0) or 0)
        if attempts >= max_attempts:
            continue
        allowed, allow_reason = sender_allowed(candidate.sender)
        kind, reply = build_reply(candidate.message) if allowed else ("", "")
        row: dict[str, Any] = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "key": candidate.key,
            "sender_suffix": normalize_phone(candidate.sender)[-4:],
            "message": candidate.message,
            "kind": kind or "unsupported",
            "allow_reason": allow_reason,
            "session_file": str(candidate.session_file),
            "user_message_id": candidate.user_message_id,
            "model_error": compact_text(candidate.error),
            "sent": False,
            "dry_run": dry_run,
            "attempts": attempts,
            "max_attempts": max_attempts,
        }
        if not allowed:
            row["status"] = "blocked_sender"
        elif not reply:
            row["status"] = "unsupported_message"
        else:
            send_result = send_imessage(candidate.sender, reply, dry_run=dry_run)
            row["status"] = "dry_run" if dry_run else ("sent" if send_result["returncode"] == 0 else "send_failed")
            row["sent"] = not dry_run and send_result["returncode"] == 0
            row["reply"] = reply
            row["send_result"] = send_result
            if not dry_run and send_result["returncode"] == 0:
                processed_keys.add(candidate.key)
                attempt_counts.pop(candidate.key, None)
            elif not dry_run:
                attempt_counts[candidate.key] = attempts + 1
        append_receipt(row)
        results.append(row)
        if len(results) >= limit:
            break

    write_json(PROCESSED_PATH, {"attempt_counts": attempt_counts, "processed_keys": sorted(processed_keys)})
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-minutes", type=int, default=240)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--live", action="store_true", help="Actually send iMessage fallback replies.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = run_fallback(since_minutes=args.since_minutes, dry_run=not args.live, limit=args.limit)
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
