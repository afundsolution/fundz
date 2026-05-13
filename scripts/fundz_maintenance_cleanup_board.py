#!/usr/bin/env python3
"""Build a FUNDz maintenance cleanup board from local billing and hold evidence."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from fundz_operational_state import normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
DISPUTEFOX_DIR = ROOT / "data" / "dispute-fox"
BILLING_RISK_REVIEW_CSV = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"
ARCHIVE_REVIEW_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-archive-review.csv"
LIVE_HOLD_CLEANUP_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-live-hold-cleanup.csv"
OUTPUT_DIR = ROOT / "data" / "local" / "maintenance-cleanup"
BOARD_MD = OUTPUT_DIR / "fundz-maintenance-cleanup-board.md"
SUMMARY_JSON = OUTPUT_DIR / "fundz-maintenance-cleanup-summary.json"
ACTIONS_CSV = OUTPUT_DIR / "fundz-maintenance-cleanup-actions.csv"
DUPLICATE_BILLING_CSV = OUTPUT_DIR / "fundz-duplicate-billing-review.csv"
ACTIVE_BILLING_ISSUES_CSV = OUTPUT_DIR / "fundz-active-billing-issues.csv"
NON_ACTIVE_BILLING_CSV = OUTPUT_DIR / "fundz-non-active-billing-review.csv"
OWNER_BILLING_STATUS_UPDATES_CSV = OUTPUT_DIR / "fundz-owner-billing-status-updates.csv"
STALE_NEXT_IMPORT_THRESHOLD_DAYS = -30

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
    "system_activity_bucket",
    "system_status",
    "system_stage_in_process",
    "system_next_import",
    "system_next_import_days",
    "system_match_source",
    "owner_update_status",
    "owner_update_date",
    "owner_update_note",
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


def latest_active_clients_full() -> Path | None:
    matches = sorted(DISPUTEFOX_DIR.glob("disputefox-active-clients-full-*.csv"))
    return matches[-1] if matches else None


def parse_next_import_days(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if text == "today":
        return 0
    if text == "tomorrow":
        return 1
    match = re.match(r"^(-?\d+)\s+days?$", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def active_client_indexes(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_name: dict[str, dict[str, str]] = {}
    by_email: dict[str, dict[str, str]] = {}
    for row in rows:
        name = normalize_name(str(row.get("client_name") or ""))
        email = str(row.get("email") or "").strip().lower()
        if name and name not in by_name:
            by_name[name] = row
        if email and email not in by_email:
            by_email[email] = row
    return by_name, by_email


def match_active_client(
    billing_rows: list[dict[str, str]],
    name_key: str,
    active_by_name: dict[str, dict[str, str]],
    active_by_email: dict[str, dict[str, str]],
) -> tuple[dict[str, str] | None, str]:
    for row in billing_rows:
        email = str(row.get("email") or "").strip().lower()
        if email and email in active_by_email:
            return active_by_email[email], "email"
    if name_key in active_by_name:
        return active_by_name[name_key], "name"
    return None, ""


def system_activity_status(active_row: dict[str, str] | None) -> tuple[str, int | None]:
    if not active_row:
        return "not_in_active_system", None
    next_days = parse_next_import_days(active_row.get("next_import"))
    if next_days is None:
        return "active_system_missing_next_import", None
    if next_days <= STALE_NEXT_IMPORT_THRESHOLD_DAYS:
        return "stale_next_import_not_active", next_days
    return "active_recent_next_import", next_days


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


def owner_billing_update_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in rows:
        key = normalize_name(str(row.get("client_name") or ""))
        status = str(row.get("owner_update_status") or "").strip()
        if key and status:
            lookup[key] = row
    return lookup


def owner_update_decision(owner_update: dict[str, str]) -> tuple[str, str] | None:
    status = str(owner_update.get("owner_update_status") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if status == "paid":
        return (
            "owner_reported_paid_monitor_only",
            "Owner reported paid; keep out of billing issue work pending the next billing-system refresh.",
        )
    if status in {"paid_active", "paid_service_active"}:
        return (
            "owner_reported_paid_active_monitor_only",
            "Owner reported paid and service active; keep out of billing issue work pending the next billing-system refresh.",
        )
    if status in {"archived", "archived_or_not_active"}:
        return (
            "owner_reported_archived_monitor_only",
            "Owner reported archived; keep out of active billing issue work pending the next DisputeFox export refresh.",
        )
    if status == "df_error_pending_fix":
        return (
            "df_error_pending_fix_monitor_only",
            "Owner reported this is a DF error and DF has been emailed; hold out of billing issue work until DF fixes or answers.",
        )
    if status == "vendor_or_system_error":
        return (
            "vendor_or_system_error_monitor_only",
            "Owner reported a vendor/system error; hold out of billing issue work until DF, ScoreFusion, or the source system fixes or answers.",
        )
    if status == "needs_brandon":
        return (
            "needs_brandon_billing_hold",
            "Owner review is required before this billing row can move; do not automate, edit, or contact from this row.",
        )
    if status == "still_billing_issue":
        return (
            "owner_confirmed_still_billing_issue",
            "Owner/proof confirms this billing issue is still real; keep it on the active issue side, but do not automate outreach.",
        )
    return None


def grouped_billing_actions(
    billing_rows: list[dict[str, str]],
    archived_names: set[str],
    active_client_rows: list[dict[str, str]] | None = None,
    owner_billing_updates: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in billing_rows:
        name = normalize_name(str(row.get("client_name") or ""))
        if name:
            grouped[name].append(row)

    active_filter_enabled = active_client_rows is not None
    active_by_name, active_by_email = active_client_indexes(active_client_rows or [])
    owner_updates = owner_billing_update_lookup(owner_billing_updates or [])
    actions: list[dict[str, Any]] = []
    duplicate_actions: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        display_name = str(rows[0].get("client_name") or key).strip()
        active_row, match_source = match_active_client(rows, key, active_by_name, active_by_email)
        owner_update = owner_updates.get(key, {})
        owner_decision = owner_update_decision(owner_update)
        system_bucket, system_next_days = system_activity_status(active_row)
        buckets = [str(row.get("review_bucket") or "") for row in rows]
        bucket_set = set(filter(None, buckets))
        risk = "high" if any(str(row.get("risk_level") or "").lower() == "high" for row in rows) else "medium"
        amount_due = round(sum(safe_float(row.get("amount_due")) for row in rows), 2)
        row_count = sum(max(safe_int(row.get("row_count")), 1) for row in rows)
        duplicate_row_count = sum(safe_int(row.get("duplicate_row_count")) for row in rows)
        emails = {str(row.get("email") or "").strip().lower() for row in rows if str(row.get("email") or "").strip()}
        duplicate_risk = duplicate_row_count > 0 or len(rows) > 1 or "dual_failure_review" in bucket_set

        if owner_decision:
            decision, next_step = owner_decision
        elif key in archived_names:
            decision = "archived_monitor_only"
            next_step = "Keep out of normal work queues; review billing only as account maintenance."
        elif active_filter_enabled and system_bucket == "not_in_active_system":
            decision = "not_in_active_system_monitor_only"
            next_step = "Do not put on the billing issue side; this billing row is not matched to the active DisputeFox export."
        elif active_filter_enabled and system_bucket == "stale_next_import_not_active":
            decision = "stale_next_import_monitor_only"
            next_step = (
                f"Do not put on the billing issue side; active export shows next import "
                f"{active_row.get('next_import', '') if active_row else ''}, at or older than the -30-day stale rule."
            )
        elif active_filter_enabled and system_bucket == "active_system_missing_next_import":
            decision = "active_system_missing_next_import_review"
            next_step = "Matched active export, but next import is missing; verify status/date before billing issue work."
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
            "system_activity_bucket": system_bucket if active_filter_enabled else "not_checked",
            "system_status": str((active_row or {}).get("status") or ""),
            "system_stage_in_process": str((active_row or {}).get("stage_in_process") or ""),
            "system_next_import": str((active_row or {}).get("next_import") or ""),
            "system_next_import_days": "" if system_next_days is None else system_next_days,
            "system_match_source": match_source,
            "owner_update_status": str(owner_update.get("owner_update_status") or ""),
            "owner_update_date": str(owner_update.get("owner_update_date") or ""),
            "owner_update_note": str(owner_update.get("owner_update_note") or ""),
            "next_step": next_step,
            "_bucket_order": min((BUCKET_ORDER.get(bucket, 99) for bucket in bucket_set), default=99),
        }
        actions.append(action)
        if decision == "duplicate_review_once":
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
    active_client_rows: list[dict[str, str]] | None = None,
    active_client_source: Path | None = None,
    owner_billing_updates: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    archived = archive_names(archive_rows, live_hold_rows)
    billing_actions, duplicate_actions = grouped_billing_actions(
        billing_rows,
        archived,
        active_client_rows,
        owner_billing_updates,
    )
    billing_decisions = Counter(str(row.get("decision") or "") for row in billing_actions)
    live_hold_decisions = Counter(str(row.get("cleanup_decision") or "") for row in live_hold_rows)
    bounce_rows = [row for row in live_hold_rows if str(row.get("blocker_type") or "") == "bounce_or_email_failure"]
    archived_live_hold_rows = [
        row for row in live_hold_rows if str(row.get("cleanup_decision") or "") == "exclude_archived_or_inactive"
    ]
    archived_billing_rows = [row for row in billing_actions if str(row.get("decision") or "") == "archived_monitor_only"]
    active_issue_decisions = {
        "active_urgent_billing_review",
        "active_date_sensitive_billing_review",
        "active_standard_billing_review",
        "duplicate_review_once",
        "fix_missing_billing_date",
        "owner_confirmed_still_billing_issue",
    }
    non_active_decisions = {
        "archived_monitor_only",
        "not_in_active_system_monitor_only",
        "stale_next_import_monitor_only",
        "active_system_missing_next_import_review",
        "monitor_only",
        "owner_reported_paid_monitor_only",
        "owner_reported_paid_active_monitor_only",
        "owner_reported_archived_monitor_only",
        "df_error_pending_fix_monitor_only",
        "vendor_or_system_error_monitor_only",
        "needs_brandon_billing_hold",
    }
    active_billing_issue_rows = [row for row in billing_actions if str(row.get("decision") or "") in active_issue_decisions]
    non_active_billing_rows = [row for row in billing_actions if str(row.get("decision") or "") in non_active_decisions]
    stale_next_import_rows = [row for row in billing_actions if str(row.get("decision") or "") == "stale_next_import_monitor_only"]
    not_in_active_system_rows = [
        row for row in billing_actions if str(row.get("decision") or "") == "not_in_active_system_monitor_only"
    ]
    active_missing_next_import_rows = [
        row for row in billing_actions if str(row.get("decision") or "") == "active_system_missing_next_import_review"
    ]
    owner_updated_rows = [
        row
        for row in billing_actions
        if str(row.get("decision") or "")
        in {
            "owner_reported_paid_monitor_only",
            "owner_reported_paid_active_monitor_only",
            "owner_reported_archived_monitor_only",
            "df_error_pending_fix_monitor_only",
            "vendor_or_system_error_monitor_only",
            "needs_brandon_billing_hold",
        }
    ]

    goal_rows = [
        {
            "goal_number": "1",
            "goal": "Billing cleanup",
            "status": "complete_local_classification",
            "item_count": len(active_billing_issue_rows),
            "decision": "Put only active-system clients inside the billing issue side.",
            "next_step": (
                f"Work {len(active_billing_issue_rows)} active billing issue client(s); "
                f"{len(non_active_billing_rows)} stale/not-found/missing-status client(s) stay out of billing issues."
            ),
            "evidence": (
                f"{len(billing_rows)} source row(s), {len(billing_actions)} unique client name(s), "
                f"active source {relative_label(active_client_source) if active_client_source else 'not checked'}."
            ),
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
            "evidence": f"{sum(safe_int(row.get('duplicate_row_count')) for row in active_billing_issue_rows)} active duplicate source row(s).",
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
        "active_billing_issue_clients": len(active_billing_issue_rows),
        "non_active_billing_clients": len(non_active_billing_rows),
        "stale_next_import_billing_clients": len(stale_next_import_rows),
        "not_in_active_system_billing_clients": len(not_in_active_system_rows),
        "active_system_missing_next_import_clients": len(active_missing_next_import_rows),
        "owner_updated_billing_clients": len(owner_updated_rows),
        "active_next_import_threshold_days": STALE_NEXT_IMPORT_THRESHOLD_DAYS,
        "active_clients_source": relative_label(active_client_source) if active_client_source else "",
        "billing_decisions": dict(sorted(billing_decisions.items())),
        "archived_excluded_clients": len(archived),
        "archived_billing_rows": len(archived_billing_rows),
        "bounced_contact_routes": len(bounce_rows),
        "duplicate_review_clients": len(duplicate_actions),
        "live_hold_decisions": dict(sorted(live_hold_decisions.items())),
        "next_action": (
            "Use the active billing issue list first; stale, not-found, archived, and missing-system-status rows stay out of billing issues."
        ),
        "board": relative_label(BOARD_MD),
        "actions_csv": relative_label(ACTIONS_CSV),
        "duplicate_csv": relative_label(DUPLICATE_BILLING_CSV),
        "active_billing_issues_csv": relative_label(ACTIVE_BILLING_ISSUES_CSV),
        "non_active_billing_csv": relative_label(NON_ACTIVE_BILLING_CSV),
        "owner_billing_status_updates_csv": relative_label(OWNER_BILLING_STATUS_UPDATES_CSV),
    }
    return {
        "summary": summary,
        "goal_rows": goal_rows,
        "billing_actions": billing_actions,
        "duplicate_actions": duplicate_actions,
        "active_billing_issue_rows": active_billing_issue_rows,
        "non_active_billing_rows": non_active_billing_rows,
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
        f"- Active billing issue clients: {summary['active_billing_issue_clients']}",
        f"- Non-active/stale/not-found billing clients excluded from issue side: {summary['non_active_billing_clients']}",
        f"- Stale next-import billing clients (-30 days or older): {summary['stale_next_import_billing_clients']}",
        f"- Not found in active system export: {summary['not_in_active_system_billing_clients']}",
        f"- Active export rows missing next import: {summary['active_system_missing_next_import_clients']}",
        f"- Owner-updated billing clients removed from issue side: {summary['owner_updated_billing_clients']}",
        f"- Active client source: {summary['active_clients_source'] or 'not checked'}",
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
            "- Billing issue side includes only rows matched to the active system export with next import newer than the -30-day stale rule.",
            "- Clients not found in the active export, stale at -30 days or older, or missing system next-import proof stay out of billing issue work.",
            "- Owner-reported paid, archived, vendor/system-error, or needs-Brandon rows stay out of billing issue work pending the next system refresh, vendor answer, or owner decision.",
            "- Owner-confirmed still-billing-issue rows stay active, but do not approve outreach or live edits from this board.",
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
    active_billing_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in board["active_billing_issue_rows"]
    ]
    non_active_billing_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in board["non_active_billing_rows"]
    ]
    write_csv(OUTPUT_DIR / "fundz-billing-maintenance-review.csv", billing_rows, BILLING_ACTION_FIELDS)
    write_csv(DUPLICATE_BILLING_CSV, duplicate_rows, BILLING_ACTION_FIELDS)
    write_csv(ACTIVE_BILLING_ISSUES_CSV, active_billing_rows, BILLING_ACTION_FIELDS)
    write_csv(NON_ACTIVE_BILLING_CSV, non_active_billing_rows, BILLING_ACTION_FIELDS)
    write_markdown(BOARD_MD, board)
    return {
        "board": relative_label(BOARD_MD),
        "summary": relative_label(SUMMARY_JSON),
        "actions": relative_label(ACTIONS_CSV),
        "duplicates": relative_label(DUPLICATE_BILLING_CSV),
        "active_billing_issues": relative_label(ACTIVE_BILLING_ISSUES_CSV),
        "non_active_billing": relative_label(NON_ACTIVE_BILLING_CSV),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--billing", type=Path, default=BILLING_RISK_REVIEW_CSV)
    parser.add_argument("--archive", type=Path, default=ARCHIVE_REVIEW_CSV)
    parser.add_argument("--live-hold", type=Path, default=LIVE_HOLD_CLEANUP_CSV)
    parser.add_argument("--active-clients", type=Path, default=None)
    parser.add_argument("--owner-updates", type=Path, default=OWNER_BILLING_STATUS_UPDATES_CSV)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    active_client_source = args.active_clients or latest_active_clients_full()
    active_client_rows = read_csv_rows(active_client_source) if active_client_source else None
    board = build_board(
        read_csv_rows(args.billing),
        read_csv_rows(args.archive),
        read_csv_rows(args.live_hold),
        active_client_rows,
        active_client_source,
        read_csv_rows(args.owner_updates),
    )
    outputs = write_outputs(board)
    print(json.dumps({"goals": len(board["goal_rows"]), **board["summary"], **outputs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
