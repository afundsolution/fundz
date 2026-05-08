#!/usr/bin/env python3
"""Build a safe intake-governor review from scattered operational signals.

The Intake Governor is intentionally not a sending bot. It turns hidden intake
signals into decision-ready queue candidates while keeping personal/sensitive
content out of shared surfaces until Brandon approves it.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"

WORK_QUEUE_CSV = OUTPUT_DIR / "fundz-work-queue.csv"
GOVERNOR_ALERTS_CSV = OUTPUT_DIR / "fundz-governor-alerts.csv"
PHONE_TRIAGE_CSV = OUTPUT_DIR / "fundz-personal-phone-needs-reply-triage.csv"
PHONE_CANDIDATES_CSV = OUTPUT_DIR / "fundz-personal-phone-work-queue-candidates.csv"
COMMUNICATION_CONTROL_BOARD_CSV = OUTPUT_DIR / "fundz-client-communication-control-board.csv"

INTAKE_GOVERNOR_MD = OUTPUT_DIR / "fundz-intake-governor.md"
INTAKE_GOVERNOR_JSON = OUTPUT_DIR / "fundz-intake-governor.json"
INTAKE_CANDIDATES_CSV = OUTPUT_DIR / "fundz-intake-governor-candidates.csv"
INTAKE_ALERTS_CSV = OUTPUT_DIR / "fundz-intake-governor-alerts.csv"

BLOCKING_STATUSES = {"Blocked", "Failed", "Proof Needed", "Needs Brandon", "Hold"}
PERSONAL_PHONE_SENSITIVE_FLAGS = {"personal_phone_intake", "sensitive_content"}

INTAKE_CANDIDATE_FIELDS = [
    "intake_id",
    "source",
    "contact",
    "phone",
    "queue_status",
    "owner",
    "classification",
    "next_step",
    "proof_required",
    "approval_needed",
    "can_auto_create",
    "shared_safe",
    "reason",
    "evidence",
]

INTAKE_ALERT_FIELDS = [
    "alert_id",
    "severity",
    "source",
    "contact",
    "reason",
    "owner",
    "next_step",
    "evidence",
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def split_flags(value: str) -> set[str]:
    return {item.strip() for item in (value or "").split(";") if item.strip()}


def build_phone_candidates(
    triage_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    candidates: list[dict[str, str]] = []
    alerts: list[dict[str, str]] = []

    candidate_by_key = {
        (row.get("client_name", ""), row.get("evidence", "")): row
        for row in candidate_rows
    }

    for row in triage_rows:
        triage_id = row.get("triage_id", "")
        contact = row.get("contact", "")
        classification = row.get("classification", "")
        move_to_queue = row.get("move_to_work_queue", "")
        needs_decision = row.get("needs_brandon_decision", "")

        if move_to_queue == "no" and needs_decision == "no":
            continue

        matching_candidate = next(
            (
                candidate
                for key, candidate in candidate_by_key.items()
                if candidate.get("client_name") == contact or triage_id in candidate.get("evidence", "")
            ),
            {},
        )
        flags = split_flags(matching_candidate.get("flags", ""))
        sensitive = bool(flags & PERSONAL_PHONE_SENSITIVE_FLAGS) or "sensitive" in row.get("sanitized_summary", "").lower()

        candidates.append(
            {
                "intake_id": triage_id or matching_candidate.get("work_order_id") or f"PHONE-{len(candidates) + 1:03d}",
                "source": "personal_phone_triage",
                "contact": contact,
                "phone": row.get("phone", ""),
                "queue_status": matching_candidate.get("queue_status") or "Needs Brandon",
                "owner": matching_candidate.get("owner") or "Brandon",
                "classification": classification or "needs review",
                "next_step": matching_candidate.get("next_step") or row.get("recommended_action", ""),
                "proof_required": matching_candidate.get("proof_required") or "Brandon approval before shared queue action.",
                "approval_needed": "yes",
                "can_auto_create": "no",
                "shared_safe": "no" if sensitive else "approval_only",
                "reason": row.get("sanitized_summary", ""),
                "evidence": matching_candidate.get("evidence") or "data/local/command-center/fundz-personal-phone-needs-reply-triage.csv",
            }
        )
        alerts.append(
            {
                "alert_id": f"INTAKE-PHONE-{len(alerts) + 1:03d}",
                "severity": "decision",
                "source": "personal_phone_triage",
                "contact": contact,
                "reason": "Personal-phone intake has a possible business item that needs Brandon approval before shared handling.",
                "owner": "Brandon",
                "next_step": "Approve sanitized Work Queue row, or mark no-company-action.",
                "evidence": row.get("triage_id", ""),
            }
        )

    return candidates, alerts


def build_work_queue_alerts(work_queue_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    counts = Counter(row.get("queue_status", "") for row in work_queue_rows)

    for status in ("Failed", "Proof Needed", "Needs Brandon"):
        if counts.get(status, 0):
            alerts.append(
                {
                    "alert_id": f"INTAKE-WORKQUEUE-{status.upper().replace(' ', '-')}",
                    "severity": "high" if status == "Failed" else "decision",
                    "source": "work_queue",
                    "contact": "",
                    "reason": f"{counts[status]} Work Queue item(s) are {status}.",
                    "owner": "Governor",
                    "next_step": "Review before any browser or client-facing action.",
                    "evidence": "data/local/command-center/fundz-work-queue.csv",
                }
            )

    if counts.get("Blocked", 0):
        alerts.append(
            {
                "alert_id": "INTAKE-WORKQUEUE-BLOCKED",
                "severity": "watch",
                "source": "work_queue",
                "contact": "",
                "reason": f"{counts['Blocked']} Work Queue item(s) are blocked.",
                "owner": "Governor",
                "next_step": "Keep broad outreach paused until proof/system gates clear.",
                "evidence": "data/local/command-center/fundz-work-queue.csv",
            }
        )

    return alerts


def build_governor_alerts(alert_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    grouped: dict[tuple[str, str, str], dict[str, str]] = {}
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in alert_rows:
        reason = row.get("reason", "") or row.get("queue_status", "") or "governor alert"
        owner = row.get("owner", "") or "Governor"
        next_step = row.get("next_step", "") or "Review Governor alert."
        key = (reason, owner, next_step)
        counts[key] += 1
        grouped.setdefault(key, row)

    for index, (key, count) in enumerate(counts.items(), start=1):
        reason, owner, next_step = key
        row = grouped[key]
        alerts.append(
            {
                "alert_id": f"INTAKE-GOVERNOR-{index:03d}",
                "severity": "watch",
                "source": "governor_alerts",
                "contact": row.get("client_name", "") if count == 1 else "",
                "reason": f"{count} Governor alert(s): {reason}",
                "owner": owner,
                "next_step": next_step,
                "evidence": row.get("evidence", "") or "data/local/command-center/fundz-governor-alerts.csv",
            }
        )
    return alerts


def communication_board_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "communication_status": dict(Counter(row.get("communication_status", "") for row in rows)),
        "message_lane": dict(Counter(row.get("message_lane", "") for row in rows)),
        "mobile_app_sms_allowed": dict(Counter(row.get("mobile_app_sms_allowed", "") for row in rows)),
    }


def build_intake_governor(
    work_queue_csv: Path = WORK_QUEUE_CSV,
    governor_alerts_csv: Path = GOVERNOR_ALERTS_CSV,
    phone_triage_csv: Path = PHONE_TRIAGE_CSV,
    phone_candidates_csv: Path = PHONE_CANDIDATES_CSV,
    communication_board_csv: Path = COMMUNICATION_CONTROL_BOARD_CSV,
) -> dict[str, Any]:
    work_queue_rows = read_csv_rows(work_queue_csv)
    governor_rows = read_csv_rows(governor_alerts_csv)
    phone_triage_rows = read_csv_rows(phone_triage_csv)
    phone_candidate_rows = read_csv_rows(phone_candidates_csv)
    communication_rows = read_csv_rows(communication_board_csv)

    phone_candidates, phone_alerts = build_phone_candidates(phone_triage_rows, phone_candidate_rows)
    alerts = []
    alerts.extend(phone_alerts)
    alerts.extend(build_work_queue_alerts(work_queue_rows))
    alerts.extend(build_governor_alerts(governor_rows))

    status_counts = Counter(row.get("queue_status", "") for row in work_queue_rows)
    safe_to_add = [row for row in phone_candidates if row.get("can_auto_create") == "yes"]
    needs_approval = [row for row in phone_candidates if row.get("approval_needed") == "yes"]

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bot": {
            "name": "FUNDz Intake Governor",
            "type": "safe intake layer",
            "mission": "Convert hidden intake into decision-ready queue candidates without sending, replying, or exposing personal content.",
        },
        "summary": {
            "work_queue_rows": len(work_queue_rows),
            "blocking_work_queue_rows": sum(status_counts.get(status, 0) for status in BLOCKING_STATUSES),
            "phone_triage_rows": len(phone_triage_rows),
            "phone_candidates": len(phone_candidates),
            "safe_to_auto_create": len(safe_to_add),
            "needs_brandon_approval": len(needs_approval),
            "alerts": len(alerts),
        },
        "status_counts": dict(status_counts),
        "communication_board": communication_board_summary(communication_rows),
        "candidates": phone_candidates,
        "alerts": alerts,
        "rules": [
            "No client-facing sends or replies.",
            "No personal-phone message body goes to Google Sheets, Slack, or shared reports without fresh Brandon approval.",
            "Personal-phone candidates default to Needs Brandon.",
            "Security codes, vendor notices, and false positives stay out of the Work Queue.",
            "A candidate becomes shared work only after owner, next step, status, proof requirement, and evidence are present.",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# FUNDz Intake Governor",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Mission",
        "",
        report["bot"]["mission"],
        "",
        "## Current Read",
        "",
        f"- Work Queue rows: {summary['work_queue_rows']}",
        f"- Blocking Work Queue rows: {summary['blocking_work_queue_rows']}",
        f"- Phone triage rows: {summary['phone_triage_rows']}",
        f"- Intake candidates: {summary['phone_candidates']}",
        f"- Safe to auto-create: {summary['safe_to_auto_create']}",
        f"- Needs Brandon approval: {summary['needs_brandon_approval']}",
        f"- Alerts: {summary['alerts']}",
        "",
        "## Decision",
        "",
    ]
    if summary["needs_brandon_approval"]:
        lines.append("Do not move intake into the shared Work Queue automatically. Brandon approval is needed first.")
    else:
        lines.append("No Brandon intake decision is pending.")

    lines.extend(["", "## Candidates", ""])
    if not report["candidates"]:
        lines.append("- No intake candidates.")
    for candidate in report["candidates"]:
        lines.append(
            f"- {candidate['intake_id']} | {candidate['contact']} | {candidate['queue_status']} | "
            f"shared_safe={candidate['shared_safe']} | {candidate['next_step']}"
        )

    lines.extend(["", "## Alerts", ""])
    for alert in report["alerts"][:20]:
        lines.append(f"- {alert['severity']} | {alert['source']} | {alert['reason']} | owner={alert['owner']}")
    if len(report["alerts"]) > 20:
        lines.append(f"- ... {len(report['alerts']) - 20} more alert(s) in CSV.")

    lines.extend(["", "## Rules", ""])
    lines.extend(f"- {rule}" for rule in report["rules"])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    write_json(INTAKE_GOVERNOR_JSON, report)
    write_markdown(INTAKE_GOVERNOR_MD, report)
    write_csv(INTAKE_CANDIDATES_CSV, report["candidates"], INTAKE_CANDIDATE_FIELDS)
    write_csv(INTAKE_ALERTS_CSV, report["alerts"], INTAKE_ALERT_FIELDS)
    return {
        "markdown": INTAKE_GOVERNOR_MD,
        "json": INTAKE_GOVERNOR_JSON,
        "candidates": INTAKE_CANDIDATES_CSV,
        "alerts": INTAKE_ALERTS_CSV,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the FUNDz Intake Governor review.")
    parser.add_argument("--json", action="store_true", help="Print the report JSON to stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_intake_governor()
    paths = write_outputs(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print("FUNDz Intake Governor built:")
    for label, path in paths.items():
        print(f"- {label}: {path}")
    print(f"- candidates needing Brandon approval: {report['summary']['needs_brandon_approval']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
