#!/usr/bin/env python3
"""Protected owner-command mode for FUNDz iMessage-style instructions."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import redact_sensitive
from fundz_credit_tracker_bridge import load_env_file


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data" / "local" / "owner-command-mode"
RECEIPTS_DIR = RUN_DIR / "receipts"
PENDING_DIR = RUN_DIR / "pending"
LATEST_RECEIPT = RUN_DIR / "latest-owner-command-receipt.json"
LATEST_REPLY = RUN_DIR / "latest-owner-command-reply.txt"
ENV_PATH = ROOT / ".env.local"
BRIDGE_LAUNCHD_LABEL = "com.fundz.credit-tracker-bridge"
BRIDGE_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{BRIDGE_LAUNCHD_LABEL}.plist"
BRIDGE_START_SCRIPT = Path.home() / "fundz-autoheal" / "start-credit-tracker-bridge.sh"

SAFE_COMMANDS = {"status", "health", "review_quarantine", "run_tests", "prepare_fix", "help"}
APPROVAL_COMMANDS = {"fix_bridge", "fix_webhook"}
BLOCKED_COMMANDS = {"send_pilot", "bulk_send", "apply_code"}

APPROVAL_RE = re.compile(r"\b(?:approve|approved|approval granted|go ahead|run approved)\b", re.I)
PHONE_RE = re.compile(r"\D+")


@dataclass(frozen=True)
class CommandDecision:
    command: str
    action_level: str
    requires_approval: bool
    approved: bool
    blocked: bool
    reason: str


def normalize_phone(value: str) -> str:
    digits = PHONE_RE.sub("", value or "")
    if len(digits) == 10:
        return "1" + digits
    return digits


def owner_allowlist() -> set[str]:
    raw = os.getenv("FUNDZ_OWNER_COMMAND_SENDERS", "").strip()
    return {normalize_phone(item) for item in re.split(r"[,;\s]+", raw) if normalize_phone(item)}


def sender_allowed(sender: str) -> tuple[bool, str]:
    allowed = owner_allowlist()
    if not allowed:
        return True, "owner sender allowlist is not configured; CLI/local command accepted"
    normalized = normalize_phone(sender)
    if normalized in allowed:
        return True, "sender is owner-allowlisted"
    return False, "sender is not owner-allowlisted"


def command_from_text(text: str) -> str:
    lower = " ".join((text or "").lower().split())
    lower = re.sub(r"^fundz[:,]?\s*", "", lower)
    if not lower:
        return "help"
    if "bulk" in lower and "send" in lower:
        return "bulk_send"
    if "send pilot" in lower or "pilot" in lower and "send" in lower:
        return "send_pilot"
    if "apply" in lower and ("code" in lower or "patch" in lower or "fix" in lower):
        return "apply_code"
    if "fix" in lower and ("webhook" in lower or "tunnel" in lower):
        return "fix_webhook"
    if "fix" in lower and ("bridge" in lower or "credit tracker" in lower):
        return "fix_bridge"
    if "quarantine" in lower or "review blocked" in lower:
        return "review_quarantine"
    if "test" in lower:
        return "run_tests"
    if "prepare" in lower and "fix" in lower:
        return "prepare_fix"
    if "health" in lower or "status" in lower or "check" in lower:
        return "health"
    if "help" in lower or "commands" in lower:
        return "help"
    return "prepare_fix"


def decide_command(text: str, sender: str = "") -> CommandDecision:
    command = command_from_text(text)
    approved = bool(APPROVAL_RE.search(text or ""))

    allowed, reason = sender_allowed(sender)
    if not allowed:
        return CommandDecision(command, "blocked", command in APPROVAL_COMMANDS, approved, True, reason)

    if command in BLOCKED_COMMANDS:
        return CommandDecision(
            command,
            "blocked",
            True,
            approved,
            True,
            "this command is blocked in owner-command mode; use the dedicated approved pilot/batch scripts",
        )
    if command in APPROVAL_COMMANDS and not approved:
        return CommandDecision(
            command,
            "prepare_fix",
            True,
            False,
            True,
            f"{command} requires an approval phrase such as FUNDz APPROVE {command.replace('_', ' ')}",
        )
    if command in APPROVAL_COMMANDS:
        return CommandDecision(command, "apply_approved_fix", True, True, False, "approved owner fix command")
    return CommandDecision(command if command in SAFE_COMMANDS else "prepare_fix", "check", False, approved, False, "safe read-only command")


def read_url(url: str, timeout: float = 4.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")[:500]
            return 200 <= response.status < 300, body
    except (OSError, urllib.error.URLError) as error:
        return False, str(error)


def latest_file(directory: Path, pattern: str) -> str:
    if not directory.exists():
        return ""
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return str(files[0].relative_to(ROOT)) if files else ""


def run_command(args: list[str], timeout: int = 30) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def health_payload() -> dict[str, Any]:
    bridge_ok, bridge_body = read_url("http://127.0.0.1:8787/health")
    old_ok, old_body = read_url("http://127.0.0.1:8789/health")
    return {
        "bridge_8787": {"ok": bridge_ok, "body": bridge_body},
        "old_bridge_8789": {"ok": old_ok, "body": old_body},
        "latest_autofox_audit": latest_file(ROOT / "data" / "local" / "autofox-audits", "autofox-audit-*.md"),
        "latest_safe_live_report": latest_file(ROOT / "data" / "local" / "safe-live-pilot", "*.md"),
        "quarantine_count": len(list((ROOT / "data" / "local" / "autonomy" / "quarantine").glob("*.json"))),
        "owner_mode_receipt_dir": str(RECEIPTS_DIR.relative_to(ROOT)),
    }


def quarantine_summary() -> dict[str, Any]:
    quarantine_dir = ROOT / "data" / "local" / "autonomy" / "quarantine"
    counts: dict[str, int] = {}
    latest: list[dict[str, str]] = []
    for path in sorted(quarantine_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        reason = str(payload.get("reason") or "unknown")
        category = classify_quarantine_reason(reason)
        counts[category] = counts.get(category, 0) + 1
        if len(latest) < 6:
            latest.append({"file": str(path.relative_to(ROOT)), "category": category, "reason": reason})
    return {"counts": counts, "latest": latest}


def classify_quarantine_reason(reason: str) -> str:
    lower = reason.lower()
    if "do-not-disturb" in lower:
        return "do_not_disturb_keep_blocked"
    if "phone" in lower:
        return "missing_phone_fix_contact"
    if "401" in lower or "403" in lower:
        return "auth_or_permission_fix_needed"
    if "400" in lower or "contact" in lower:
        return "bad_contact_id_or_payload"
    if "422" in lower:
        return "payload_shape_fix_needed"
    if "signature" in lower:
        return "bad_signature_blocked"
    return "owner_review_needed"


def prepare_fix_payload(command_text: str) -> dict[str, Any]:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    health = health_payload()
    quarantine = quarantine_summary()
    pending = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "requested_command": command_text,
        "recommended_next": "Reply with an explicit approved fix command only if the diagnosis matches the issue.",
        "safe_approved_commands": [
            "FUNDz approve fix bridge",
            "FUNDz approve fix webhook",
        ],
        "blocked_commands": sorted(BLOCKED_COMMANDS),
        "health": health,
        "quarantine": quarantine,
    }
    path = PENDING_DIR / f"pending-fix-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(redact_sensitive(pending), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pending["path"] = str(path.relative_to(ROOT))
    return pending


def apply_fix(command: str) -> dict[str, Any]:
    if command == "fix_bridge":
        domain = f"gui/{os.getuid()}"
        return {
            "steps": [
                run_command(["screen", "-S", "fundz-bridge", "-X", "quit"], timeout=5),
                run_command(["pkill", "-f", "scripts/fundz_credit_tracker_bridge.py"], timeout=5),
                run_command(["launchctl", "bootout", domain, str(BRIDGE_LAUNCHD_PLIST)], timeout=5),
                run_command(
                    [
                        "screen",
                        "-dmS",
                        "fundz-bridge",
                        str(BRIDGE_START_SCRIPT),
                    ],
                    timeout=5,
                ),
            ],
            "post_health": health_payload(),
        }
    if command == "fix_webhook":
        return {
            "steps": [
                run_command(["screen", "-S", "fundz-tunnel", "-X", "quit"], timeout=5),
                run_command(
                    [
                        "screen",
                        "-dmS",
                        "fundz-tunnel",
                        "zsh",
                        "-lc",
                        f'cd "{ROOT}" && exec /opt/homebrew/bin/cloudflared tunnel --protocol http2 --url http://127.0.0.1:8787 > logs/cloudflared-fundz.out 2>&1',
                    ],
                    timeout=5,
                ),
            ],
            "post_health": health_payload(),
            "note": "quick Cloudflare tunnels are not permanent; named tunnel is still recommended for production stability",
        }
    return {"blocked": True, "reason": f"unsupported approved fix command: {command}"}


def reply_for_receipt(receipt: dict[str, Any]) -> str:
    decision = receipt["decision"]
    command = decision["command"]
    if decision["blocked"]:
        return f"FUNDz owner command blocked: {command}. Reason: {decision['reason']}. Receipt: {receipt['receipt_path']}"
    if command in {"health", "status"}:
        health = receipt["result"].get("health", {})
        bridge = "OK" if health.get("bridge_8787", {}).get("ok") else "FAILED"
        return f"FUNDz health check complete. Bridge: {bridge}. Quarantine: {health.get('quarantine_count', 0)}. Receipt: {receipt['receipt_path']}"
    if command == "review_quarantine":
        counts = receipt["result"].get("quarantine", {}).get("counts", {})
        return f"FUNDz quarantine review complete: {counts}. Receipt: {receipt['receipt_path']}"
    if command == "run_tests":
        result = receipt["result"].get("tests", {})
        return f"FUNDz tests completed with code {result.get('returncode')}. Receipt: {receipt['receipt_path']}"
    if decision["action_level"] == "apply_approved_fix":
        ok = receipt["result"].get("post_health", {}).get("bridge_8787", {}).get("ok")
        return f"FUNDz approved fix ran for {command}. Bridge health: {'OK' if ok else 'CHECK NEEDED'}. Receipt: {receipt['receipt_path']}"
    pending_path = receipt["result"].get("prepared_fix", {}).get("path", "")
    return f"FUNDz prepared a fix review for {command}. No live changes applied. Pending fix: {pending_path}. Receipt: {receipt['receipt_path']}"


def execute_owner_command(text: str, sender: str = "") -> dict[str, Any]:
    load_env_file()
    decision = decide_command(text, sender)
    result: dict[str, Any]
    if decision.blocked:
        result = {"blocked": True}
        if decision.command in APPROVAL_COMMANDS and not decision.approved:
            result["prepared_fix"] = prepare_fix_payload(text)
    elif decision.command in {"health", "status", "help"}:
        result = {"health": health_payload(), "help": command_help() if decision.command == "help" else ""}
    elif decision.command == "review_quarantine":
        result = {"quarantine": quarantine_summary()}
    elif decision.command == "run_tests":
        result = {"tests": run_command(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"], timeout=60)}
    elif decision.action_level == "apply_approved_fix":
        result = apply_fix(decision.command)
    else:
        result = {"prepared_fix": prepare_fix_payload(text)}

    receipt = write_receipt(text, sender, decision, result)
    receipt["reply"] = reply_for_receipt(receipt)
    LATEST_REPLY.write_text(receipt["reply"] + "\n", encoding="utf-8")
    LATEST_RECEIPT.write_text(json.dumps(redact_sensitive(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def write_receipt(text: str, sender: str, decision: CommandDecision, result: dict[str, Any]) -> dict[str, Any]:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sender": sender,
        "requested_text": text,
        "decision": decision.__dict__,
        "result": redact_sensitive(result),
    }
    path = RECEIPTS_DIR / f"owner-command-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}.json"
    receipt["receipt_path"] = str(path.relative_to(ROOT))
    path.write_text(json.dumps(redact_sensitive(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def command_help() -> str:
    return (
        "Supported owner commands: FUNDz status, FUNDz health check, FUNDz review quarantine, "
        "FUNDz run tests, FUNDz prepare fix, FUNDz fix bridge, FUNDz fix webhook. "
        "Fix bridge/webhook require APPROVE in the text. Pilot/bulk sends use the dedicated approved scripts."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="Owner command text, as received from iMessage.")
    parser.add_argument("--sender", default="", help="Sender phone number for owner allowlist checks.")
    parser.add_argument("--json", action="store_true", help="Print the full receipt JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    receipt = execute_owner_command(args.text, args.sender)
    if args.json:
        print(json.dumps(redact_sensitive(receipt), indent=2, sort_keys=True))
    else:
        print(receipt["reply"])


if __name__ == "__main__":
    main()
