#!/usr/bin/env python3
"""Run the safe local FUNDz autonomous operator loop."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import log_autonomy_event, redact_sensitive
from fundz_operational_state import relative_label


ROOT = Path(__file__).resolve().parents[1]
AUTONOMY_DIR = ROOT / "data" / "local" / "autonomy"
STATUS_MD = AUTONOMY_DIR / "fundz-autonomous-operator-status.md"
STATUS_JSON = AUTONOMY_DIR / "fundz-autonomous-operator-status.json"
RUN_LOG = AUTONOMY_DIR / "fundz-autonomous-operator.jsonl"
AUTONOMY_EVENTS_JSONL = AUTONOMY_DIR / "autonomy-events.jsonl"
MAINTENANCE_STATUS_JSON = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-autopilot-status.json"
MAINTENANCE_STATUS_MD = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-autopilot-status.md"
WORK_QUEUE_CSV = ROOT / "data" / "local" / "command-center" / "fundz-work-queue.csv"
DAILY_BOARD_MD = ROOT / "data" / "local" / "command-center" / "fundz-daily-board.md"
INTAKE_GOVERNOR_JSON = ROOT / "data" / "local" / "command-center" / "fundz-intake-governor.json"
PHONE_APP_INTAKE_JSON = ROOT / "data" / "local" / "command-center" / "fundz-phone-app-intake.json"

FALLBACK_LABEL = "com.afundsolution.fundz-imessage-fallback"
ALLOW_FALLBACK_ENV = "FUNDZ_ALLOW_IMESSAGE_FALLBACK_LAUNCHAGENT"
WATCHED_SCREEN_NAMES = ("fundz-bridge", "fundz-tunnel", "fundz-highlevel-poller")
WATCHED_PROCESS_MARKERS = (
    "scripts/fundz_credit_tracker_bridge.py",
    "cloudflared tunnel run fundz-credit-tracker",
    "scripts/fundz_highlevel_inbox_poller.py --daemon",
    "scripts/fundz_imessage_fallback.py",
)

SAFE_CHILD_ENV = {
    "CREDIT_TRACKER_DRY_RUN": "true",
    "FUNDZ_HIGHLEVEL_POLLER_LIVE": "false",
    "FUNDZ_ALLOW_AFTER_HOURS_SENDS": "false",
}

PIPELINE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("autonomy_review", ("scripts/fundz_autonomy_daemon.py", "--once")),
    ("maintenance_autopilot", ("scripts/fundz_maintenance_autopilot.py", "--today", "{today}")),
    ("intake_governor", ("scripts/fundz_intake_governor.py",)),
    ("intake_governor_visual", ("scripts/fundz_intake_governor_visual.py",)),
    ("phone_app_intake", ("scripts/fundz_phone_app_intake.py",)),
    ("command_center", ("scripts/fundz_command_center.py", "--limit", "10")),
)


def command_for_step(template: tuple[str, ...], today: str, *, run_tests: bool) -> list[str]:
    command = ["python3", *[part.format(today=today) for part in template]]
    if template and template[0] == "scripts/fundz_maintenance_autopilot.py" and run_tests:
        command.append("--run-tests")
    return command


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(SAFE_CHILD_ENV)
    return env


def run_command(command: list[str], *, timeout: int = 180) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=child_env(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        result = {
            "command": command,
            "returncode": completed.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": completed.stdout.strip()[-4000:],
            "stderr": completed.stderr.strip()[-4000:],
            "ok": completed.returncode == 0,
        }
    except subprocess.TimeoutExpired as error:
        result = {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": (error.stdout or "")[-4000:] if isinstance(error.stdout, str) else "",
            "stderr": (error.stderr or "")[-4000:] if isinstance(error.stderr, str) else "",
            "ok": False,
            "error": f"timed out after {timeout} seconds",
        }
    return redact_sensitive(result)


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_text(path: Path, limit: int = 12) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[:limit])
    except OSError:
        return ""


def latest_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            return item
    return {}


def work_queue_counts(path: Path | None = None) -> dict[str, int]:
    path = path or WORK_QUEUE_CSV
    if not path.exists():
        return {}
    counts: Counter[str] = Counter()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            status = (row.get("queue_status") or "Unknown").strip() or "Unknown"
            counts[status] += 1
    return dict(sorted(counts.items()))


def summarize_intake(path: Path | None = None) -> dict[str, Any]:
    path = path or INTAKE_GOVERNOR_JSON
    data = read_json(path)
    candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
    alerts = data.get("alerts") if isinstance(data.get("alerts"), list) else []
    return {
        "generated_at": data.get("generated_at"),
        "candidates": len(candidates),
        "safe_to_auto_create": sum(1 for item in candidates if item.get("can_auto_create") is True),
        "approval_needed": sum(1 for item in candidates if item.get("approval_needed") is True),
        "alerts": len(alerts),
    }


def summarize_phone_app_intake(path: Path | None = None) -> dict[str, Any]:
    path = path or PHONE_APP_INTAKE_JSON
    data = read_json(path)
    rows = data.get("intake_rows")
    if not isinstance(rows, list):
        rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    return {
        "generated_at": data.get("generated_at"),
        "intake_rows": len(rows),
        "approval_needed": sum(1 for item in rows if item.get("approval_needed") is True),
        "revenue_or_money_signals": sum(
            1
            for item in rows
            if str(item.get("classification") or item.get("category") or "").lower() in {"revenue", "money"}
        ),
    }


def quick_check(command: list[str], timeout: int = 6) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "stdout": "", "stderr": str(error), "returncode": None}
    return {
        "ok": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }


def runtime_check() -> dict[str, Any]:
    screen = quick_check(["screen", "-ls"])
    screen_output = f"{screen.get('stdout', '')}\n{screen.get('stderr', '')}"
    active_screens = [name for name in WATCHED_SCREEN_NAMES if name in screen_output]

    fallback_allowed = os.getenv(ALLOW_FALLBACK_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    process_markers = [
        marker for marker in WATCHED_PROCESS_MARKERS if not fallback_allowed or marker != "scripts/fundz_imessage_fallback.py"
    ]
    ps = quick_check(["ps", "-axo", "pid=,command="])
    process_lines = str(ps.get("stdout") or "").splitlines()
    active_processes = [
        line.strip()
        for line in process_lines
        if any(marker in line for marker in process_markers)
        and "fundz_autonomous_operator.py" not in line
    ]

    launchctl = quick_check(["launchctl", "print-disabled", f"gui/{os.getuid()}"])
    launchctl_output = f"{launchctl.get('stdout', '')}\n{launchctl.get('stderr', '')}"
    fallback_disabled = f'"{FALLBACK_LABEL}" => disabled' in launchctl_output or f"{FALLBACK_LABEL} => disabled" in launchctl_output
    fallback_state_ok = not launchctl.get("ok") or fallback_disabled or fallback_allowed
    return {
        "quiet": not active_screens and not active_processes and fallback_state_ok,
        "active_screens": active_screens,
        "active_processes": active_processes[:10],
        "fallback_launchagent_disabled": fallback_disabled,
        "fallback_launchagent_allowed": fallback_allowed,
        "launchctl_checked": launchctl.get("ok"),
    }


def safety_findings(maintenance: dict[str, Any], runtime: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    rollout = maintenance.get("rollout_packet") if isinstance(maintenance.get("rollout_packet"), dict) else {}
    if rollout.get("live_send_allowed") is True:
        findings.append("Unsafe: maintenance rollout packet says live_send_allowed=true.")
    if rollout and rollout.get("approval_required") is not True:
        findings.append("Unsafe: maintenance rollout packet does not require approval.")
    if runtime.get("active_screens"):
        findings.append(f"Unsafe: live FUNDz screen session(s) are running: {', '.join(runtime['active_screens'])}.")
    if runtime.get("active_processes"):
        findings.append("Unsafe: live FUNDz runtime process(es) appear to be running.")
    if (
        runtime.get("launchctl_checked")
        and runtime.get("fallback_launchagent_disabled") is not True
        and runtime.get("fallback_launchagent_allowed") is not True
    ):
        findings.append("Unsafe: FUNDz iMessage fallback LaunchAgent is enabled.")
    if not rollout:
        findings.append("Review: maintenance rollout packet was not found.")
    return findings


def write_status(status: dict[str, Any]) -> None:
    AUTONOMY_DIR.mkdir(parents=True, exist_ok=True)
    safe_status = redact_sensitive(status)
    STATUS_JSON.write_text(json.dumps(safe_status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_status, sort_keys=True) + "\n")

    findings = status.get("safety_findings") or []
    runtime = status.get("runtime") or {}
    maintenance = status.get("maintenance") or {}
    rollout = maintenance.get("rollout_packet") or {}
    intake = status.get("intake_governor") or {}
    phone = status.get("phone_app_intake") or {}
    lines = [
        "# FUNDz Autonomous Operator Status",
        "",
        f"Generated: {status.get('generated_at')}",
        "",
        "Mode: safe local autonomy. This refreshes boards, intake, maintenance cleanup, quarantine/proposal review, and tests when requested. It does not start live sends, assign campaigns, edit client records, or wire webhooks.",
        "",
        "## Overall",
        f"- Result: {'OK' if status.get('ok') else 'Needs review'}",
        f"- Steps: {status.get('successful_steps', 0)}/{status.get('total_steps', 0)}",
        f"- Runtime quiet: {runtime.get('quiet')}",
        f"- Dry-run enforced for child tasks: {status.get('safe_child_env', {}).get('CREDIT_TRACKER_DRY_RUN')}",
        "",
        "## Approval Gates",
        f"- Approval required: {rollout.get('approval_required')}",
        f"- Live send allowed: {rollout.get('live_send_allowed')}",
        f"- Rollout selected: {rollout.get('selected', 0)}",
        "",
        "## Intake",
        f"- Intake Governor candidates: {intake.get('candidates', 0)}",
        f"- Intake Governor approval-needed: {intake.get('approval_needed', 0)}",
        f"- Intake Governor alerts: {intake.get('alerts', 0)}",
        f"- Phone App intake rows: {phone.get('intake_rows', 0)}",
        f"- Phone App approval-needed: {phone.get('approval_needed', 0)}",
        "",
        "## Work Queue",
    ]
    queue_counts = status.get("work_queue_counts") or {}
    if queue_counts:
        lines.extend(f"- {key}: {value}" for key, value in queue_counts.items())
    else:
        lines.append("- Missing or empty.")
    if findings:
        lines.extend(["", "## Findings"])
        lines.extend(f"- {finding}" for finding in findings)
    lines.extend(
        [
            "",
            "## Outputs",
            f"- Operator status: {relative_label(STATUS_MD)}",
            f"- Maintenance autopilot: {relative_label(MAINTENANCE_STATUS_MD)}",
            f"- Daily board: {relative_label(DAILY_BOARD_MD)}",
            f"- Latest autonomy event: {json.dumps(status.get('latest_autonomy_event') or {}, ensure_ascii=True, sort_keys=True)}",
            "",
            "## Daily Board Preview",
            read_text(DAILY_BOARD_MD, limit=8) or "Missing daily board.",
        ]
    )
    STATUS_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run_pipeline(today: str, *, run_tests: bool = False) -> dict[str, Any]:
    started = time.time()
    steps: list[dict[str, Any]] = []
    for name, template in PIPELINE_STEPS:
        result = run_command(command_for_step(template, today, run_tests=run_tests), timeout=300 if run_tests else 180)
        result["name"] = name
        steps.append(result)

    maintenance = read_json(MAINTENANCE_STATUS_JSON)
    runtime = runtime_check()
    findings = safety_findings(maintenance, runtime)
    failed_steps = [step for step in steps if not step.get("ok")]
    unsafe_findings = [finding for finding in findings if finding.startswith("Unsafe:")]
    status = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "today": today,
        "ok": not failed_steps and not unsafe_findings,
        "duration_seconds": round(time.time() - started, 3),
        "total_steps": len(steps),
        "successful_steps": sum(1 for step in steps if step.get("ok")),
        "steps": steps,
        "safe_child_env": SAFE_CHILD_ENV,
        "runtime": runtime,
        "maintenance": {
            "ok": maintenance.get("ok"),
            "status": relative_label(MAINTENANCE_STATUS_MD),
            "rollout_packet": maintenance.get("rollout_packet") or {},
            "maintenance_summary": maintenance.get("maintenance_summary") or {},
        },
        "work_queue_counts": work_queue_counts(),
        "intake_governor": summarize_intake(),
        "phone_app_intake": summarize_phone_app_intake(),
        "latest_autonomy_event": latest_jsonl(AUTONOMY_EVENTS_JSONL),
        "safety_findings": findings,
    }
    write_status(status)
    log_autonomy_event(
        "autonomous_operator_completed",
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


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def run_watch(today: str, interval: int, run_tests: bool) -> None:
    if not env_bool("FUNDZ_AUTONOMOUS_OPERATOR_ENABLED", False):
        print("FUNDz autonomous operator watch is disabled. Set FUNDZ_AUTONOMOUS_OPERATOR_ENABLED=true to watch.")
        return
    while True:
        status = run_pipeline(today, run_tests=run_tests)
        print(f"autonomous operator {'OK' if status['ok'] else 'needs review'}: {relative_label(STATUS_MD)}")
        time.sleep(max(interval, 300))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=date.today().isoformat(), help="Dashboard date in YYYY-MM-DD format.")
    parser.add_argument("--once", action="store_true", help="Run one safe autonomous pass, then exit.")
    parser.add_argument("--watch", action="store_true", help="Run repeatedly when enabled by env var.")
    parser.add_argument("--interval", type=int, default=env_int("FUNDZ_AUTONOMOUS_OPERATOR_INTERVAL_SECONDS", 900))
    parser.add_argument("--run-tests", action="store_true", help="Run the local test suite through maintenance autopilot.")
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
