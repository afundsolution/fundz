#!/usr/bin/env python3
"""Build a FUNDz maintenance cleanup board from local billing and hold evidence."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from fundz_operational_state import normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
BILLING_RISK_REVIEW_CSV = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"
ARCHIVE_REVIEW_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-archive-review.csv"
LIVE_HOLD_CLEANUP_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-live-hold-cleanup.csv"
OUTPUT_DIR = ROOT / "data" / "local" / "maintenance-cleanup"
BOARD_MD = OUTPUT_DIR / "fundz-maintenance-cleanup-board.md"
SUMMARY_JSON = OUTPUT_DIR / "fundz-maintenance-cleanup-summary.json"
ACTIONS_CSV = OUTPUT_DIR / "fundz-maintenance-cleanup-actions.csv"
DUPLICATE_BILLING_CSV = OUTPUT_DIR / "fundz-duplicate-billing-review.csv"

ACTION_FIELDS = [
    "goal_number",
    "goal",
    "status",
    "item_count",
    "decision",
    "next_step",
    "evidence",
]

BILLING_ACTION_FIELDS = [
    "client_name",
    "decision",
    "risk_level",
    "review_buckets",
    "amount_due",
    "row_count",
    "duplicate_row_count",
    "email_count",
    "failure_types",
    "next_charge_date",
    "next_step",
]

BUCKET_ORDER = {
    "urgent_due_now_or_past_due": 0,
    "date_sensitive_next_7_days": 1,
    "dual_failure_review": 2,
    "standard_high_risk_review": 3,
    "missing_charge_date_review": 4,
    "medium_monitor_review": 5,
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_int(value: Any) -> int:
    try:
        return int(float(str(value or "0")))
    except ValueError:
        return 0


def safe_float(value: Any) -> float:
    try:
        return round(float(str(value or "0")), 2)
    except ValueError:
        return 0.0


def unique_join(values: list[str]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        output.append(text)
    return "; ".join(output)


def earliest_date(values: list[str]) -> str:
    dates = sorted(value for value in (str(item or "").strip() for item in values) if value)
    return dates[0] if dates else ""


def archive_names(archive_rows: list[dict[str, str]], live_hold_rows: list[dict[str, str]]) -> set[str]:
    names: set[str] = set()
    for row in archive_rows:
        if str(row.get("archive_decision") or "").startswith("archived"):
            name = normalize_name(str(row.get("client_name") or ""))
            if name:
                names.add(name)
    for row in live_hold_rows:
        if str(row.get("cleanup_decision") or "") == "exclude_archived_or_inactive":
            name = normalize_name(str(row.get("client_name") or ""))
            if name:
                names.add(name)
    return names


def grouped_billing_actions(
    billing_rows: list[dict[str, str]],
    archived_names: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in billing_rows:
        name = normalize_name(str(row.get("client_name") or ""))
        if name:
            grouped[name].append(row)

    actions: list[dict[str, Any]] = []
    duplicate_actions: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        display_name = str(rows[0].get("client_name") or key).strip()
        buckets = [str(row.get("review_bucket") or "") for row in rows]
        bucket_set = set(filter(None, buckets))
        risk = "high" if any(str(row.get("risk_level") or "").lower() == "high" for row in rows) else "medium"
        amount_due = round(sum(safe_float(row.get("amount_due")) for row in rows), 2)
        row_count = sum(max(safe_int(row.get("row_count")), 1) for row in rows)
        duplicate_row_count = sum(safe_int(row.get("duplicate_row_count")) for row in rows)
        emails = {str(row.get("email") or "").strip().lower() for row in rows if str(row.get("email") or "").strip()}
        duplicate_risk = duplicate_row_count > 0 or len(rows) > 1 or "dual_failure_review" in bucket_set

        if key in archived_names:
            decision = "archived_monitor_only"
            next_step = "Keep out of normal work queues; review billing only as account maintenance."
        elif "urgent_due_now_or_past_due" in bucket_set:
            decision = "active_urgent_billing_review"
            next_step = "Review payment state first; do not trigger billing-warning automation from this row."
        elif "date_sensitive_next_7_days" in bucket_set:
            decision = "active_date_sensitive_billing_review"
            next_step = "Review before the next charge date; keep out of automated work until cleared."
        elif duplicate_risk:
            decision = "duplicate_review_once"
            next_step = "Review one unique client once; do not treat duplicate failure rows as extra work."
        elif "missing_charge_date_review" in bucket_set:
            decision = "fix_missing_billing_date"
            next_step = "Fix missing billing date/status before using this row for decisions."
        elif "medium_monitor_review" in bucket_set:
            decision = "monitor_only"
            next_step = "Monitor as maintenance; do not promote to outreach."
        else:
            decision = "active_standard_billing_review"
            next_step = "Keep out of automated work until payment failure is cleared."

        action = {
            "client_name": display_name,
            "decision": decision,
            "risk_level": risk,
            "review_buckets": unique_join(buckets),
            "amount_due": f"{amount_due:.2f}",
            "row_count": row_count,
            "duplicate_row_count": duplicate_row_count,
            "email_count": len(emails),
            "failure_types": unique_join([str(row.get("failure_types") or "") for row in rows]),
            "next_charge_date": earliest_date([str(row.get("next_charge_date") or "") for row in rows]),
            "next_step": next_step,
            "_bucket_order": min((BUCKET_ORDER.get(bucket, 99) for bucket in bucket_set), default=99),
        }
        actions.append(action)
        if duplicate_risk:
            duplicate_actions.append(action)

    sort_key = lambda row: (
        row.get("_bucket_order", 99),
        str(row.get("next_charge_date") or "9999-99-99"),
        str(row.get("client_name") or "").lower(),
    )
    return sorted(actions, key=sort_key), sorted(duplicate_actions, key=sort_key)


def build_board(
    billing_rows: list[dict[str, str]],
    archive_rows: list[dict[str, str]],
    live_hold_rows: list[dict[str, str]],
) -> dict[str, Any]:
    archived = archive_names(archive_rows, live_hold_rows)
    billing_actions, duplicate_actions = grouped_billing_actions(billing_rows, archived)
    billing_decisions = Counter(str(row.get("decision") or "") for row in billing_actions)
    live_hold_decisions = Counter(str(row.get("cleanup_decision") or "") for row in live_hold_rows)
    bounce_rows = [row for row in live_hold_rows if str(row.get("blocker_type") or "") == "bounce_or_email_failure"]
    archived_live_hold_rows = [
        row for row in live_hold_rows if str(row.get("cleanup_decision") or "") == "exclude_archived_or_inactive"
    ]
    archived_billing_rows = [row for row in billing_actions if str(row.get("decision") or "") == "archived_monitor_only"]

    goal_rows = [
        {
            "goal_number": "1",
            "goal": "Billing cleanup",
            "status": "complete_local_classification",
            "item_count": len(billing_actions),
            "decision": "Separate active billing review from archived monitor-only rows.",
            "next_step": f"Work only the active billing review list; {len(archived_billing_rows)} archived billing row(s) stay monitor-only.",
            "evidence": f"{len(billing_rows)} source row(s), {len(billing_actions)} unique client name(s).",
        },
        {
            "goal_number": "2",
            "goal": "Archive cleanup",
            "status": "complete_local_exclusion",
            "item_count": len(archived),
            "decision": "Archived/inactive clients stay out of normal work queues.",
            "next_step": "Reopen only with exact owner instruction and fresh live status proof.",
            "evidence": f"{len(archive_rows)} archive-review row(s), {len(archived_live_hold_rows)} archived/inactive live-hold row(s).",
        },
        {
            "goal_number": "3",
            "goal": "Contact cleanup",
            "status": "complete_local_exclusion",
            "item_count": len(bounce_rows),
            "decision": "Bad or bounced email routes stay excluded.",
            "next_step": "Fix only when a verified replacement route exists; then require fresh live preflight.",
            "evidence": f"{len(bounce_rows)} bounced/contact-route row(s).",
        },
        {
            "goal_number": "4",
            "goal": "Duplicate cleanup",
            "status": "complete_local_dedupe",
            "item_count": len(duplicate_actions),
            "decision": "Duplicate billing failures are reviewed once per unique client name.",
            "next_step": "Use the duplicate billing review CSV; do not count duplicate failure rows as extra people.",
            "evidence": f"{sum(safe_int(row.get('duplicate_row_count')) for row in billing_actions)} duplicate source row(s).",
        },
        {
            "goal_number": "5",
            "goal": "Command center cleanup",
            "status": "ready_for_command_center",
            "item_count": 1,
            "decision": "Daily board should point to maintenance cleanup, not sending.",
            "next_step": "Rebuild command center after this board is generated.",
            "evidence": relative_label(BOARD_MD),
        },
    ]
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "billing_source_rows": len(billing_rows),
        "billing_unique_clients": len(billing_actions),
        "billing_decisions": dict(sorted(billing_decisions.items())),
        "archived_excluded_clients": len(archived),
        "archived_billing_rows": len(archived_billing_rows),
        "bounced_contact_routes": len(bounce_rows),
        "duplicate_review_clients": len(duplicate_actions),
        "live_hold_decisions": dict(sorted(live_hold_decisions.items())),
        "next_action": (
            "Use the maintenance cleanup board: active billing review first, archived/contact-route/duplicate rows stay excluded or review-once."
        ),
        "board": relative_label(BOARD_MD),
        "actions_csv": relative_label(ACTIONS_CSV),
        "duplicate_csv": relative_label(DUPLICATE_BILLING_CSV),
    }
    return {
        "summary": summary,
        "goal_rows": goal_rows,
        "billing_actions": billing_actions,
        "duplicate_actions": duplicate_actions,
    }


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, board: dict[str, Any]) -> None:
    summary = board["summary"]
    lines = [
        "# FUNDz Maintenance Cleanup Board",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "This is maintenance cleanup only. It does not approve sends, SMS, billing-warning automation, or live client record edits.",
        "",
        "## Summary",
        f"- Billing source rows: {summary['billing_source_rows']}",
        f"- Unique billing client names: {summary['billing_unique_clients']}",
        f"- Archived/excluded clients: {summary['archived_excluded_clients']}",
        f"- Archived billing rows marked monitor-only: {summary['archived_billing_rows']}",
        f"- Bounced contact routes: {summary['bounced_contact_routes']}",
        f"- Duplicate-review clients: {summary['duplicate_review_clients']}",
        "",
        "## Five Goals",
        "| # | Goal | Status | Count | Decision | Next step |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    for row in board["goal_rows"]:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in ("goal_number", "goal", "status", "item_count", "decision", "next_step")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Billing Decisions",
        ]
    )
    for decision, count in summary["billing_decisions"].items():
        lines.append(f"- {decision}: {count}")
    lines.extend(
        [
            "",
            "## Operating Rule",
            "- Active billing review is maintenance work, not outreach.",
            "- Archived/inactive clients stay out of normal work queues.",
            "- Bounced contact routes stay excluded until a verified replacement exists.",
            "- Duplicate failure rows are reviewed once per unique client name.",
            "- Rebuild the command center after this board changes.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(board: dict[str, Any]) -> dict[str, str]:
    write_json(SUMMARY_JSON, board["summary"])
    write_csv(ACTIONS_CSV, board["goal_rows"], ACTION_FIELDS)
    billing_rows = [{key: value for key, value in row.items() if not key.startswith("_")} for row in board["billing_actions"]]
    duplicate_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")} for row in board["duplicate_actions"]
    ]
    write_csv(OUTPUT_DIR / "fundz-billing-maintenance-review.csv", billing_rows, BILLING_ACTION_FIELDS)
    write_csv(DUPLICATE_BILLING_CSV, duplicate_rows, BILLING_ACTION_FIELDS)
    write_markdown(BOARD_MD, board)
    return {
        "board": relative_label(BOARD_MD),
        "summary": relative_label(SUMMARY_JSON),
        "actions": relative_label(ACTIONS_CSV),
        "duplicates": relative_label(DUPLICATE_BILLING_CSV),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--billing", type=Path, default=BILLING_RISK_REVIEW_CSV)
    parser.add_argument("--archive", type=Path, default=ARCHIVE_REVIEW_CSV)
    parser.add_argument("--live-hold", type=Path, default=LIVE_HOLD_CLEANUP_CSV)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    board = build_board(read_csv_rows(args.billing), read_csv_rows(args.archive), read_csv_rows(args.live_hold))
    outputs = write_outputs(board)
    print(json.dumps({"goals": len(board["goal_rows"]), **board["summary"], **outputs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
