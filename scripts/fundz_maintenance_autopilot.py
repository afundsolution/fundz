#!/usr/bin/env python3
"""Run the safe FUNDz maintenance cleanup pipeline autonomously."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import log_autonomy_event, redact_sensitive
from fundz_operational_state import relative_label


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "maintenance-cleanup"
STATUS_MD = OUTPUT_DIR / "fundz-maintenance-autopilot-status.md"
STATUS_JSON = OUTPUT_DIR / "fundz-maintenance-autopilot-status.json"
AUTOPILOT_LOG = OUTPUT_DIR / "fundz-maintenance-autopilot.jsonl"
ROLLOUT_PACKET_JSON = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-rollout-packet.json"
MAINTENANCE_SUMMARY_JSON = OUTPUT_DIR / "fundz-maintenance-cleanup-summary.json"
DAILY_BOARD_MD = ROOT / "data" / "local" / "command-center" / "fundz-daily-board.md"


PIPELINE_STEPS = (
    ("scorefusion_billing_dashboard", ("scripts/scorefusion_billing_dashboard.py", "--today", "{today}")),
    ("live_hold_cleanup", ("scripts/fundz_live_hold_cleanup_packet.py",)),
    ("billing_risk_cleanup", ("scripts/fundz_billing_risk_cleanup_packet.py",)),
    ("maintenance_cleanup_board", ("scripts/fundz_maintenance_cleanup_board.py",)),
    ("rollout_safety_check", ("scripts/fundz_autofox_rollout_packet.py", "--size", "1", "--scan-limit", "1000")),
    ("command_center", ("scripts/fundz_command_center.py",)),
)


def command_for_step(template: tuple[str, ...], today: str) -> list[str]:
    return ["python3", *[part.format(today=today) for part in template]]


def run_command(command: list[str], *, cwd: Path = ROOT) -> dict[str, Any]:
    started = time.time()
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": result.returncode,
        "duration_seconds": round(time.time() - started, 3),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "ok": result.returncode == 0,
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def safety_findings(packet: dict[str, Any], maintenance_summary: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if packet.get("live_send_allowed") is True:
        findings.append("Unsafe: rollout packet says live_send_allowed=true.")
    if packet.get("approval_required") is not True:
        findings.append("Unsafe: rollout packet does not require approval.")
    if packet.get("selected", 0):
        findings.append(
            f"Review only: rollout safety check found {packet.get('selected')} possible candidate(s); no send is approved."
        )
    if not maintenance_summary:
        findings.append("Maintenance summary is missing.")
    return findings


def write_status(status: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_status = redact_sensitive(status)
    STATUS_JSON.write_text(json.dumps(safe_status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with AUTOPILOT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_status, sort_keys=True) + "\n")

    summary = status.get("maintenance_summary") or {}
    rollout = status.get("rollout_packet") or {}
    lines = [
        "# FUNDz Maintenance Autopilot Status",
        "",
        f"Generated: {status.get('generated_at')}",
        "",
        "This is maintenance cleanup only. It does not approve sends, SMS, billing-warning automation, or live client edits.",
        "",
        "## Run Status",
        f"- Overall: {'OK' if status.get('ok') else 'Needs review'}",
        f"- Steps: {status.get('successful_steps', 0)}/{status.get('total_steps', 0)}",
        f"- Today: {status.get('today')}",
        "",
        "## Maintenance Counts",
        f"- Billing source rows: {summary.get('billing_source_rows', 0)}",
        f"- Unique billing clients: {summary.get('billing_unique_clients', 0)}",
        f"- Archived/excluded clients: {summary.get('archived_excluded_clients', 0)}",
        f"- Bounced contact routes: {summary.get('bounced_contact_routes', 0)}",
        f"- Duplicate-review clients: {summary.get('duplicate_review_clients', 0)}",
        "",
        "## Safety Check",
        f"- Rollout selected: {rollout.get('selected', 0)}",
        f"- Held before packet: {rollout.get('held_before_packet', 0)}",
        f"- Approval required: {rollout.get('approval_required')}",
        f"- Live send allowed: {rollout.get('live_send_allowed')}",
    ]
    findings = status.get("safety_findings") or []
    if findings:
        lines.extend(["", "## Findings"])
        lines.extend(f"- {finding}" for finding in findings)
    lines.extend(
        [
            "",
            "## Outputs",
            f"- Maintenance board: {summary.get('board', 'missing')}",
            f"- Duplicate review: {summary.get('duplicate_csv', 'missing')}",
            f"- Daily board: {relative_label(DAILY_BOARD_MD)}",
        ]
    )
    STATUS_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run_pipeline(today: str, *, run_tests: bool = False) -> dict[str, Any]:
    started = time.time()
    steps: list[dict[str, Any]] = []
    for name, template in PIPELINE_STEPS:
        result = run_command(command_for_step(template, today))
        result["name"] = name
        steps.append(result)
        if not result["ok"]:
            break

    if run_tests and all(step["ok"] for step in steps):
        test_result = run_command(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"])
        test_result["name"] = "tests"
        steps.append(test_result)

    maintenance_summary = read_json(MAINTENANCE_SUMMARY_JSON)
    rollout_packet = read_json(ROLLOUT_PACKET_JSON)
    findings = safety_findings(rollout_packet, maintenance_summary)
    hard_failures = [step for step in steps if not step["ok"]]
    unsafe_findings = [finding for finding in findings if finding.startswith("Unsafe:")]
    status = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "today": today,
        "ok": not hard_failures and not unsafe_findings,
        "duration_seconds": round(time.time() - started, 3),
        "total_steps": len(steps),
        "successful_steps": sum(1 for step in steps if step["ok"]),
        "steps": steps,
        "maintenance_summary": maintenance_summary,
        "rollout_packet": {
            "selected": rollout_packet.get("selected", 0),
            "held_before_packet": rollout_packet.get("held_before_packet", 0),
            "approval_required": rollout_packet.get("approval_required"),
            "live_send_allowed": rollout_packet.get("live_send_allowed"),
            "created_at": rollout_packet.get("created_at"),
        },
        "safety_findings": findings,
        "daily_board_preview": "\n".join(read_text(DAILY_BOARD_MD).splitlines()[:8]),
    }
    write_status(status)
    log_autonomy_event(
        "maintenance_autopilot_completed",
        {
            "ok": status["ok"],
            "today": today,
            "successful_steps": status["successful_steps"],
            "total_steps": status["total_steps"],
            "status": relative_label(STATUS_MD),
            "safety_findings": findings,
        },
    )
    return status


def run_watch(today: str, interval: int, run_tests: bool) -> None:
    if os.getenv("FUNDZ_MAINTENANCE_AUTOPILOT_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        print("Maintenance autopilot watch is disabled. Set FUNDZ_MAINTENANCE_AUTOPILOT_ENABLED=true to watch.")
        return
    while True:
        status = run_pipeline(today, run_tests=run_tests)
        print(f"maintenance autopilot {'OK' if status['ok'] else 'needs review'}: {relative_label(STATUS_MD)}")
        time.sleep(max(interval, 60))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=date.today().isoformat(), help="Dashboard date in YYYY-MM-DD format.")
    parser.add_argument("--run-tests", action="store_true", help="Run the full local test suite after regeneration.")
    parser.add_argument("--watch", action="store_true", help="Run repeatedly when explicitly enabled by env var.")
    parser.add_argument("--interval", type=int, default=900, help="Watch interval in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.watch:
        run_watch(args.today, args.interval, args.run_tests)
        return
    status = run_pipeline(args.today, run_tests=args.run_tests)
    print(
        json.dumps(
            {
                "ok": status["ok"],
                "status": relative_label(STATUS_MD),
                "successful_steps": status["successful_steps"],
                "total_steps": status["total_steps"],
                "safety_findings": status["safety_findings"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
