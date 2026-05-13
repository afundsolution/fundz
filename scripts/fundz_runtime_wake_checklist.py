#!/usr/bin/env python3
"""Build the no-wake runtime proof checklist before any controlled reply."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"
CHECKLIST_JSON = OUTPUT_DIR / "fundz-runtime-wake-proof-checklist.json"
CHECKLIST_MD = OUTPUT_DIR / "fundz-runtime-wake-proof-checklist.md"
SEND_KILL_SWITCH_JSON = OUTPUT_DIR / "fundz-send-kill-switch.json"
APP_PORTAL_PROOF_JSONL = ROOT / "data" / "local" / "highlevel-inbox-poller" / "app-portal-event-proof.jsonl"
REPLY_RECEIPTS_JSONL = ROOT / "data" / "local" / "highlevel-inbox-poller" / "reply-receipts.jsonl"
BRIDGE_LOG = ROOT / "logs" / "credit-tracker-bridge.jsonl"


LIVE_SCREEN_NAMES = {"fundz-bridge", "fundz-tunnel", "fundz-highlevel-poller"}
ALLOWED_REPORTING_SCREEN_NAMES = {"fundz-command-center"}
LIVE_PROCESS_MARKERS = (
    ("fundz_credit_tracker_bridge.py",),
    ("fundz_highlevel_inbox_poller.py", "--daemon"),
    ("cloudflared", "tunnel"),
    ("cloudflared", "fundz-credit-tracker"),
)


def load_env_file(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env.local"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def quick_check(command: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": str(error)}
    except subprocess.TimeoutExpired as error:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": error.stdout or "",
            "stderr": error.stderr or f"timeout after {timeout}s",
        }
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def active_screen_names() -> list[str]:
    result = quick_check(["screen", "-ls"])
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if "\t" not in line and "." not in stripped:
            continue
        for name in LIVE_SCREEN_NAMES | ALLOWED_REPORTING_SCREEN_NAMES:
            if f".{name}" in stripped or stripped.endswith(name):
                names.append(name)
    return sorted(set(names))


def active_live_processes() -> list[str]:
    result = quick_check(["ps", "-axo", "pid=,command="])
    if not result["ok"]:
        return []
    matches: list[str] = []
    for line in str(result.get("stdout", "")).splitlines():
        if "fundz_runtime_wake_checklist.py" in line:
            continue
        for marker in LIVE_PROCESS_MARKERS:
            if all(part in line for part in marker):
                matches.append(line.strip())
                break
    return matches


def kill_switch_status() -> dict[str, Any]:
    state = read_json(SEND_KILL_SWITCH_JSON) or {}
    enabled = bool(state.get("enabled", False))
    return {
        "path": str(SEND_KILL_SWITCH_JSON.relative_to(ROOT)),
        "exists": SEND_KILL_SWITCH_JSON.exists(),
        "enabled": enabled,
        "status": "on_blocks_live_replies" if enabled else "off_approval_gates_still_required",
        "reason": str(state.get("reason") or "").strip(),
    }


def file_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "exists": False, "bytes": 0, "modified_at": ""}
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "bytes": stat.st_size,
        "modified_at": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(stat.st_mtime)),
    }


def current_gate_state() -> dict[str, Any]:
    load_env_file()
    return {
        "credit_tracker_dry_run": env_bool("CREDIT_TRACKER_DRY_RUN", True),
        "highlevel_poller_live": env_bool("FUNDZ_HIGHLEVEL_POLLER_LIVE", False),
        "highlevel_controlled_reply_approved": env_bool("FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED", False),
        "webhook_controlled_reply_approved": env_bool("FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED", False),
        "allow_after_hours_sends": env_bool("FUNDZ_ALLOW_AFTER_HOURS_SENDS", False),
    }


def build_checklist() -> dict[str, Any]:
    screens = active_screen_names()
    live_processes = active_live_processes()
    live_screens = [name for name in screens if name in LIVE_SCREEN_NAMES]
    reporting_screens = [name for name in screens if name in ALLOWED_REPORTING_SCREEN_NAMES]
    kill_switch = kill_switch_status()
    env_state = current_gate_state()
    blockers: list[str] = []
    warnings: list[str] = []

    if live_screens:
        blockers.append("Live bridge/tunnel/poller screen session is already awake; run `make inactive` unless Brandon explicitly approved this wake.")
    if live_processes:
        blockers.append("Live runtime process marker detected; inspect process list and park it before relying on this checklist.")
    if not kill_switch["enabled"]:
        warnings.append("Command-center kill switch is off. That is only acceptable inside an approved action window.")
    if not env_state["credit_tracker_dry_run"]:
        blockers.append("CREDIT_TRACKER_DRY_RUN is false outside this no-wake checklist run.")
    for flag in ("highlevel_poller_live", "highlevel_controlled_reply_approved", "webhook_controlled_reply_approved"):
        if env_state[flag]:
            blockers.append(f"{flag.upper()} is already true; approval flags should be false until the exact action window.")

    status = "READY_FOR_APPROVED_WAKE_PROOF" if not blockers else "BLOCKED_REVIEW_RUNTIME"
    if reporting_screens and status == "READY_FOR_APPROVED_WAKE_PROOF":
        status = "READY_FOR_APPROVED_WAKE_PROOF_REPORTING_AWAKE"

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "no_wake_performed": True,
        "send_performed": False,
        "runtime": {
            "active_screens": screens,
            "live_screens": live_screens,
            "allowed_reporting_screens": reporting_screens,
            "live_processes": live_processes,
        },
        "kill_switch": kill_switch,
        "env_gates": env_state,
        "proof_files": {
            "app_portal_proof": file_status(APP_PORTAL_PROOF_JSONL),
            "reply_receipts": file_status(REPLY_RECEIPTS_JSONL),
            "bridge_log": file_status(BRIDGE_LOG),
        },
        "blockers": blockers,
        "warnings": warnings,
        "approval_packet_required": [
            "Named client and exact inbound app/portal source.",
            "Exact reply copy or exact approved reply category.",
            "Exact action window and route: HighLevel poller or Credit Tracker webhook.",
            "Cap of one reply unless Brandon approves a different cap in writing.",
            "Receipt owner and rollback owner named before wake.",
        ],
        "pre_wake_local_steps": [
            "Run `make inactive` if any live bridge/tunnel/poller runtime is awake.",
            "Run `make runtime-wake-checklist` and confirm status is READY_FOR_APPROVED_WAKE_PROOF or READY_FOR_APPROVED_WAKE_PROOF_REPORTING_AWAKE.",
            "Confirm app/portal inbound proof exists or is the exact inbound being tested.",
            "Confirm the command-center kill switch is on while waiting, then turn it off only for the approved action window.",
        ],
        "wake_proof_steps_after_approval": [
            "Wake only the approved route: `scripts/fundz_highlevel_poller_start.sh` for poller or bridge plus `scripts/fundz_named_tunnel_setup.sh` for webhook.",
            "Verify local bridge health if webhook route is used: `curl -fsS http://127.0.0.1:8787/health`.",
            "Verify public webhook health if tunnel route is used: `curl -fsS https://fundz.afundsolution.com/health`.",
            "Run `make webhook-probe` only for webhook route; it is test-only and must not send.",
            "Run HighLevel preview before live poller reply: `CREDIT_TRACKER_DRY_RUN=true FUNDZ_HIGHLEVEL_POLLER_LIVE=false scripts/fundz_highlevel_inbox_poller.py --once --limit 5`.",
            "Confirm exactly one approval flag is true for the approved route and `CREDIT_TRACKER_DRY_RUN=false` only inside the window.",
            "After the approved reply, confirm receipt in `data/local/highlevel-inbox-poller/reply-receipts.jsonl` or `logs/credit-tracker-bridge.jsonl`.",
            "Run `make inactive`, restore dry-run, restore approval flags to false, and regenerate `make runtime-wake-checklist` plus `make command-center`.",
        ],
        "not_authorized_by_this_checklist": [
            "No live reply.",
            "No client/lead send.",
            "No webhook wiring.",
            "No HighLevel, billing, DF, AutoFox, campaign, or archive edit.",
        ],
    }


def write_markdown(checklist: dict[str, Any], path: Path = CHECKLIST_MD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runtime = checklist["runtime"]
    env_gates = checklist["env_gates"]
    proof_files = checklist["proof_files"]
    lines = [
        "# FUNDz Runtime Wake Proof Checklist",
        "",
        f"Generated: {checklist['generated_at']}",
        f"Status: {checklist['status']}",
        "",
        "This is a no-wake proof surface. It does not start the bridge, tunnel, poller, webhook, or any send path.",
        "",
        "## Current Runtime",
        f"- Active screens: {', '.join(runtime['active_screens']) if runtime['active_screens'] else 'none'}",
        f"- Live bridge/tunnel/poller screens: {', '.join(runtime['live_screens']) if runtime['live_screens'] else 'none'}",
        f"- Allowed reporting screens: {', '.join(runtime['allowed_reporting_screens']) if runtime['allowed_reporting_screens'] else 'none'}",
        f"- Live process markers: {len(runtime['live_processes'])}",
        "",
        "## Gate State",
        f"- Kill switch: {checklist['kill_switch']['status']}",
        f"- `CREDIT_TRACKER_DRY_RUN`: {env_gates['credit_tracker_dry_run']}",
        f"- `FUNDZ_HIGHLEVEL_POLLER_LIVE`: {env_gates['highlevel_poller_live']}",
        f"- `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED`: {env_gates['highlevel_controlled_reply_approved']}",
        f"- `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED`: {env_gates['webhook_controlled_reply_approved']}",
        "",
        "## Blockers",
    ]
    lines.extend(f"- {item}" for item in checklist["blockers"] or ["None in local no-wake posture."])
    lines.append("")
    lines.append("## Warnings")
    lines.extend(f"- {item}" for item in checklist["warnings"] or ["None."])
    lines.extend(["", "## Proof Files"])
    for label, info in proof_files.items():
        exists = "exists" if info["exists"] else "missing"
        lines.append(f"- {label}: `{info['path']}` ({exists}, {info['bytes']} bytes)")
    lines.extend(["", "## Approval Packet Required"])
    lines.extend(f"- {item}" for item in checklist["approval_packet_required"])
    lines.extend(["", "## Pre-Wake Local Steps"])
    lines.extend(f"- {item}" for item in checklist["pre_wake_local_steps"])
    lines.extend(["", "## Wake Proof Steps After Brandon Approval"])
    lines.extend(f"- {item}" for item in checklist["wake_proof_steps_after_approval"])
    lines.extend(["", "## This Checklist Does Not Authorize"])
    lines.extend(f"- {item}" for item in checklist["not_authorized_by_this_checklist"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(checklist: dict[str, Any]) -> None:
    CHECKLIST_JSON.parent.mkdir(parents=True, exist_ok=True)
    CHECKLIST_JSON.write_text(json.dumps(checklist, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(checklist, CHECKLIST_MD)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-only", action="store_true", help="write JSON only")
    args = parser.parse_args()
    checklist = build_checklist()
    if args.json_only:
        CHECKLIST_JSON.parent.mkdir(parents=True, exist_ok=True)
        CHECKLIST_JSON.write_text(json.dumps(checklist, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        write_outputs(checklist)
    print(json.dumps({"status": checklist["status"], "path": str(CHECKLIST_MD.relative_to(ROOT))}, indent=2))
    if checklist["blockers"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
