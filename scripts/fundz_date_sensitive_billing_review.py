#!/usr/bin/env python3
"""Build a local clearance packet for active date-sensitive billing reviews."""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fundz_operational_state import normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_DIR = ROOT / "data" / "local" / "maintenance-cleanup"
ACTIVE_BILLING_ISSUES_CSV = MAINTENANCE_DIR / "fundz-active-billing-issues.csv"
BILLING_RISK_REVIEW_CSV = (
    ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"
)
CLIENT_BILLING_ROSTER_CSV = (
    ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "client-billing-roster.csv"
)
OUTPUT_CSV = MAINTENANCE_DIR / "fundz-date-sensitive-billing-review-clearance.csv"
OUTPUT_MD = MAINTENANCE_DIR / "fundz-date-sensitive-billing-review-clearance.md"

FIELDS = [
    "client_name",
    "review_status",
    "clearance_status",
    "failure_type",
    "next_charge_date",
    "days_until_charge",
    "amount_due",
    "billing_status",
    "system_status",
    "system_stage_in_process",
    "system_next_import",
    "system_next_import_days",
    "owner_priority",
    "client_contact_allowed_now",
    "live_edit_allowed_now",
    "required_action",
    "proof_needed_to_clear",
    "evidence",
]


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


def safe_float(value: Any) -> float:
    try:
        return round(float(str(value or "0")), 2)
    except ValueError:
        return 0.0


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def row_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in rows:
        key = normalize_name(str(row.get("client_name") or ""))
        if key and key not in lookup:
            lookup[key] = row
    return lookup


def days_until(next_charge: str, today: date) -> int | None:
    parsed = parse_date(next_charge)
    return None if parsed is None else (parsed - today).days


def review_action(row: dict[str, str], billing_status: str) -> tuple[str, str, str, str]:
    failure = str(row.get("failure_types") or "").strip()
    if "Client Card Failure" in failure:
        return (
            "reviewed_payment_method_hold",
            "not_cleared_live_payment_proof_required",
            (
                "Check live ScoreFusion/DF billing for payment-method state. If still failed, keep the client on "
                "billing hold and decide the exact payment follow-up manually."
            ),
            "Fresh live ScoreFusion/DF proof that the card/payment method is fixed or a manual owner hold reason.",
        )
    if "Low Credits Failure" in failure:
        detail = (
            "Check ScoreFusion credit balance/config and verify the next import/monitoring charge can run. "
            "Treat this as internal funding/credit proof first, not a client outreach task."
        )
        if safe_float(row.get("amount_due")) == 0:
            detail += " Amount due is 0.00, so do not treat it as client money until live proof says otherwise."
        return (
            "reviewed_scorefusion_credit_hold",
            "not_cleared_credit_funding_proof_required",
            detail,
            "Fresh live ScoreFusion proof that credits/funding are sufficient and this failure no longer blocks monitoring.",
        )
    return (
        "reviewed_billing_hold",
        "not_cleared_live_proof_required",
        "Check live billing state before changing this row.",
        "Fresh live billing proof or a manual owner hold reason.",
    )


def owner_priority(row: dict[str, str], today: date) -> str:
    due_in = days_until(str(row.get("next_charge_date") or ""), today)
    failure = str(row.get("failure_types") or "")
    if due_in is not None and due_in <= 2:
        return "P1"
    if "Client Card Failure" in failure:
        return "P1"
    if due_in is not None and due_in <= 5:
        return "P2"
    return "P3"


def build_review_rows(
    active_rows: list[dict[str, str]],
    risk_rows: list[dict[str, str]],
    roster_rows: list[dict[str, str]],
    today: date,
) -> list[dict[str, Any]]:
    risk_by_name = row_lookup(risk_rows)
    roster_by_name = row_lookup(roster_rows)
    review_rows: list[dict[str, Any]] = []
    for row in active_rows:
        if str(row.get("decision") or "") != "active_date_sensitive_billing_review":
            continue
        key = normalize_name(str(row.get("client_name") or ""))
        risk = risk_by_name.get(key, {})
        roster = roster_by_name.get(key, {})
        billing_status = str(risk.get("billing_statuses") or roster.get("billing_status") or "")
        review_status, clearance_status, required_action, proof_needed = review_action(row, billing_status)
        due_in = days_until(str(row.get("next_charge_date") or ""), today)
        review_rows.append(
            {
                "client_name": str(row.get("client_name") or ""),
                "review_status": review_status,
                "clearance_status": clearance_status,
                "failure_type": str(row.get("failure_types") or ""),
                "next_charge_date": str(row.get("next_charge_date") or ""),
                "days_until_charge": "" if due_in is None else due_in,
                "amount_due": str(row.get("amount_due") or ""),
                "billing_status": billing_status,
                "system_status": str(row.get("system_status") or ""),
                "system_stage_in_process": str(row.get("system_stage_in_process") or ""),
                "system_next_import": str(row.get("system_next_import") or ""),
                "system_next_import_days": str(row.get("system_next_import_days") or ""),
                "owner_priority": owner_priority(row, today),
                "client_contact_allowed_now": "no",
                "live_edit_allowed_now": "no",
                "required_action": required_action,
                "proof_needed_to_clear": proof_needed,
                "evidence": (
                    f"{relative_label(ACTIVE_BILLING_ISSUES_CSV)}; "
                    f"{relative_label(BILLING_RISK_REVIEW_CSV)}; "
                    f"{relative_label(CLIENT_BILLING_ROSTER_CSV)}"
                ),
            }
        )
    return sorted(
        review_rows,
        key=lambda item: (
            str(item.get("owner_priority") or "P9"),
            str(item.get("next_charge_date") or "9999-99-99"),
            str(item.get("client_name") or "").lower(),
        ),
    )


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, rows: list[dict[str, Any]], generated_at: str, today: date, csv_path: Path) -> None:
    failures = Counter(str(row.get("failure_type") or "unknown") for row in rows)
    statuses = Counter(str(row.get("review_status") or "unknown") for row in rows)
    priorities = Counter(str(row.get("owner_priority") or "unknown") for row in rows)
    work_order = []
    if failures.get("Client Card Failure", 0):
        work_order.append("Handle P1 card failures first with live payment-method proof.")
    else:
        work_order.append("Card/payment-method failures are not in the active date-sensitive lane right now.")
    if failures.get("Low Credits Failure", 0):
        work_order.append(
            "Handle the low-credit failures by checking ScoreFusion credits/funding/config before treating them as client issues."
        )
    work_order.append("Rerun maintenance after live proof is updated so the board can drop anything that is truly cleared.")
    lines = [
        "# FUNDz Date-Sensitive Billing Review Clearance",
        "",
        f"Generated: {generated_at}",
        f"Today: {today.isoformat()}",
        "",
        "This clears the local review step only. It does not clear the live billing failure, approve client contact, start billing warnings, or edit live records.",
        "",
        "## Summary",
        f"- Date-sensitive active billing reviews checked: {len(rows)}",
        f"- Local review completed: {sum(statuses.values())}",
        "- Cleared as no issue: 0",
        f"- Client card failures needing live payment proof: {failures.get('Client Card Failure', 0)}",
        f"- Low-credit failures needing ScoreFusion credit/funding proof: {failures.get('Low Credits Failure', 0)}",
        f"- Client contact allowed now: {sum(1 for row in rows if row.get('client_contact_allowed_now') == 'yes')}",
        f"- Live edits allowed now: {sum(1 for row in rows if row.get('live_edit_allowed_now') == 'yes')}",
        f"- Output CSV: `{relative_label(csv_path)}`",
        "",
        "## Work Order",
        *[f"{index}. {item}" for index, item in enumerate(work_order, 1)],
        "",
        "## Priority Counts",
    ]
    for priority, count in sorted(priorities.items()):
        lines.append(f"- {priority}: {count}")
    lines.extend(
        [
            "",
            "## Rows",
            "| Priority | Client | Failure | Next charge | Due in | Amount | System import | Status | Required action |",
            "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "owner_priority",
                    "client_name",
                    "failure_type",
                    "next_charge_date",
                    "days_until_charge",
                    "amount_due",
                    "system_next_import",
                    "clearance_status",
                    "required_action",
                )
            )
            + " |"
        )
    if not rows:
        lines.append("| - | No active date-sensitive billing reviews | - | - | - | - | - | cleared locally | No date-sensitive billing action remains from this packet. |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(
    rows: list[dict[str, Any]],
    today: date,
    csv_path: Path = OUTPUT_CSV,
    md_path: Path = OUTPUT_MD,
    generated_at: str | None = None,
) -> dict[str, str]:
    generated_at = generated_at or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    write_csv(csv_path, rows, FIELDS)
    write_markdown(md_path, rows, generated_at, today, csv_path)
    return {"csv": relative_label(csv_path), "markdown": relative_label(md_path)}


def build_from_files(
    active_path: Path = ACTIVE_BILLING_ISSUES_CSV,
    risk_path: Path = BILLING_RISK_REVIEW_CSV,
    roster_path: Path = CLIENT_BILLING_ROSTER_CSV,
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or date.today()
    return build_review_rows(
        read_csv_rows(active_path),
        read_csv_rows(risk_path),
        read_csv_rows(roster_path),
        today,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-billing", type=Path, default=ACTIVE_BILLING_ISSUES_CSV)
    parser.add_argument("--risk-review", type=Path, default=BILLING_RISK_REVIEW_CSV)
    parser.add_argument("--roster", type=Path, default=CLIENT_BILLING_ROSTER_CSV)
    parser.add_argument("--today", default=date.today().isoformat())
    parser.add_argument("--csv", type=Path, default=OUTPUT_CSV)
    parser.add_argument("--markdown", type=Path, default=OUTPUT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date()
    rows = build_from_files(args.active_billing, args.risk_review, args.roster, today)
    outputs = write_outputs(rows, today, args.csv, args.markdown)
    print(f"Date-sensitive billing reviews checked: {len(rows)}")
    print(f"Markdown: {outputs['markdown']}")
    print(f"CSV: {outputs['csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
