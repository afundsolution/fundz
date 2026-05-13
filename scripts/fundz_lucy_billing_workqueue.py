#!/usr/bin/env python3
"""Build Lucy's A FUND Solution billing maintenance work queue from active FUNDz evidence."""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

from fundz_operational_state import relative_label


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_DIR = ROOT / "data" / "local" / "maintenance-cleanup"
ACTIVE_BILLING_ISSUES_CSV = MAINTENANCE_DIR / "fundz-active-billing-issues.csv"
OUTPUT_CSV = MAINTENANCE_DIR / "fundz-lucy-billing-workqueue.csv"
OUTPUT_MD = MAINTENANCE_DIR / "fundz-lucy-billing-workqueue.md"

FIELDS = [
    "owner",
    "status",
    "client_name",
    "billing_lane",
    "priority",
    "next_charge_date",
    "failure_types",
    "amount_due",
    "system_status",
    "system_stage_in_process",
    "system_next_import",
    "lucy_action",
    "proof_required",
    "escalate_to_brandon_when",
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


def priority_for(row: dict[str, str]) -> str:
    decision = str(row.get("decision") or "")
    next_charge = str(row.get("next_charge_date") or "")
    if decision == "duplicate_review_once":
        if next_charge <= "2026-05-15":
            return "P1"
        return "P2"
    return "P3"


def lucy_action_for(row: dict[str, str]) -> str:
    decision = str(row.get("decision") or "")
    if decision == "duplicate_review_once":
        return (
            "Review this client once, not once per failure row. Decide paid/active, archived/not active, "
            "DF or ScoreFusion error, or still billing issue."
        )
    return (
        "Verify whether the card-failure row is still true in billing/ScoreFusion evidence. "
        "Decide paid/active, archived/not active, vendor/system error, or still billing issue."
    )


def proof_required_for(row: dict[str, str]) -> str:
    decision = str(row.get("decision") or "")
    if decision == "duplicate_review_once":
        return "One clean proof note showing the single client-level decision and why duplicate rows should not create extra work."
    return "Proof of payment/active service, archive/inactive status, vendor/system error, or still-failed billing state."


def build_queue(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in rows:
        decision = str(row.get("decision") or "")
        if decision not in {"duplicate_review_once", "active_standard_billing_review"}:
            continue
        output.append(
            {
                "owner": "Lucy",
                "status": "needs_lucy_review",
                "client_name": str(row.get("client_name") or ""),
                "billing_lane": decision,
                "priority": priority_for(row),
                "next_charge_date": str(row.get("next_charge_date") or ""),
                "failure_types": str(row.get("failure_types") or ""),
                "amount_due": str(row.get("amount_due") or ""),
                "system_status": str(row.get("system_status") or ""),
                "system_stage_in_process": str(row.get("system_stage_in_process") or ""),
                "system_next_import": str(row.get("system_next_import") or ""),
                "lucy_action": lucy_action_for(row),
                "proof_required": proof_required_for(row),
                "escalate_to_brandon_when": (
                    "Only when the decision needs owner approval, money judgment, live billing edit, client contact, "
                    "or the proof is conflicting."
                ),
                "evidence": relative_label(ACTIVE_BILLING_ISSUES_CSV),
            }
        )
    return sorted(
        output,
        key=lambda item: (
            str(item.get("priority") or "P9"),
            str(item.get("next_charge_date") or "9999-99-99"),
            str(item.get("client_name") or "").lower(),
        ),
    )


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, rows: list[dict[str, str]], generated_at: str, csv_path: Path) -> None:
    duplicate_count = sum(1 for row in rows if row.get("billing_lane") == "duplicate_review_once")
    standard_count = sum(1 for row in rows if row.get("billing_lane") == "active_standard_billing_review")
    lines = [
        "# A FUND Solution Billing Maintenance Work Queue - Lucy",
        "",
        f"Generated: {generated_at}",
        "",
        "Owner: Lucy",
        "",
        "This queue is for A FUND Solution supervisor billing maintenance. FUNDz is the source workflow feeding the evidence. This queue does not approve client contact, payment reminders, billing edits, AutoFox/DF edits, or HighLevel sends.",
        "",
        "## Summary",
        f"- Total Lucy-owned A FUND Solution billing items: {len(rows)}",
        f"- Duplicate-review clients: {duplicate_count}",
        f"- Standard card-failure reviews: {standard_count}",
        f"- CSV: `{relative_label(csv_path)}`",
        "",
        "## Lucy Decision Options",
        "- `paid_active`: client paid and service is active.",
        "- `archived_or_not_active`: client should stay out of active billing work.",
        "- `vendor_or_system_error`: DF/ScoreFusion needs a fix or answer.",
        "- `still_billing_issue`: proof says the billing issue is still real.",
        "- `needs_brandon`: decision requires owner approval, live edit, client contact, or conflicting proof.",
        "",
        "## Batch Update Path",
        "- Record all owner/Lucy decisions once in `data/local/maintenance-cleanup/fundz-owner-billing-status-updates.csv`.",
        "- Required columns: `client_name`, `owner_update_status`, `owner_update_date`, `owner_update_note`, `source`.",
        "- After the list is complete, refresh the maintenance board and Command Center once, then verify the summary counts.",
        "",
        "## Rows",
        "| Priority | Client | Lane | Next charge | Failure | Stage | Import | Lucy action | Proof required |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "priority",
                    "client_name",
                    "billing_lane",
                    "next_charge_date",
                    "failure_types",
                    "system_stage_in_process",
                    "system_next_import",
                    "lucy_action",
                    "proof_required",
                )
            )
            + " |"
        )
    if not rows:
        lines.append("| - | No Lucy billing items | - | - | - | - | - | No action | No proof needed |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(rows: list[dict[str, str]], csv_path: Path, md_path: Path, generated_at: str | None = None) -> None:
    generated_at = generated_at or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    write_csv(csv_path, rows, FIELDS)
    write_markdown(md_path, rows, generated_at, csv_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-billing", type=Path, default=ACTIVE_BILLING_ISSUES_CSV)
    parser.add_argument("--csv", type=Path, default=OUTPUT_CSV)
    parser.add_argument("--markdown", type=Path, default=OUTPUT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = build_queue(read_csv_rows(args.active_billing))
    write_outputs(rows, args.csv, args.markdown)
    print(f"A FUND Solution billing items for Lucy: {len(rows)}")
    print(f"Markdown: {relative_label(args.markdown)}")
    print(f"CSV: {relative_label(args.csv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
