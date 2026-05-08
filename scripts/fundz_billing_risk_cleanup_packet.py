#!/usr/bin/env python3
"""Build a focused cleanup packet for billing-risk clients blocking DF rollout."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fundz_operational_state import normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
ROLLOUT_PACKET_JSON = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-rollout-packet.json"
BILLING_RISK_REVIEW_CSV = (
    ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"
)
OUTPUT_DIR = ROOT / "data" / "local" / "autofox-rollout"
CLEANUP_CSV = OUTPUT_DIR / "df-autofox-billing-risk-cleanup.csv"
CLEANUP_MD = OUTPUT_DIR / "df-autofox-billing-risk-cleanup.md"

FIELDS = [
    "client_name",
    "stage_in_process",
    "risk_level",
    "review_bucket",
    "cleanup_decision",
    "next_charge_date",
    "amount_due",
    "failure_types",
    "row_count",
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


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def billing_bucket_from_reason(reason: str) -> str:
    match = re.search(r"billing-risk review queue:\s*([a-z0-9_ -]+)", reason, re.I)
    return match.group(1).strip() if match else ""


def billing_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in rows:
        name_key = normalize_name(str(row.get("client_name") or ""))
        email_key = str(row.get("email") or "").strip().lower()
        if name_key:
            lookup[name_key] = row
        if email_key:
            lookup[email_key] = row
    return lookup


def cleanup_decision(row: dict[str, Any]) -> tuple[str, str]:
    bucket = str(row.get("review_bucket") or "")
    risk = str(row.get("risk_level") or "")
    if bucket == "urgent_due_now_or_past_due":
        return "hold_manual_billing_review", (
            "Hold normal rollout. Review payment state manually before any client-facing update."
        )
    if bucket == "date_sensitive_next_7_days" and risk == "high":
        return "owner_override_needed", (
            "Check billing before next charge date; only send if owner approves the exact client and message."
        )
    if bucket == "date_sensitive_next_7_days":
        return "exclude_until_cleared", "Exclude from rollout until billing/date-sensitive review is cleared."
    if bucket == "dual_failure_review":
        return "dedupe_review_once", (
            "Review once as a unique client/key; do not double-contact duplicate failure rows."
        )
    if bucket == "standard_high_risk_review":
        return "exclude_until_payment_clear", "Keep out of normal rollout until payment failure is resolved."
    if bucket == "missing_charge_date_review":
        return "fix_billing_data", "Verify missing billing date before any billing-warning workflow change."
    if bucket == "medium_monitor_review":
        return "monitor_exclude_from_rollout", "Monitor, but keep out of normal rollout until cleared."
    return "billing_review", "Review billing state before any normal outreach."


def build_cleanup_rows(packet: dict[str, Any], billing_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    lookup = billing_lookup(billing_rows)
    rows: list[dict[str, Any]] = []
    for index, held in enumerate(packet.get("held_candidates", [])):
        reason = str(held.get("reason") or "")
        bucket = billing_bucket_from_reason(reason)
        if not bucket:
            continue
        key = normalize_name(str(held.get("client_name") or ""))
        billing = dict(lookup.get(key, {}))
        billing.setdefault("review_bucket", bucket)
        decision, next_step = cleanup_decision(billing)
        rows.append(
            {
                "client_name": held.get("client_name", ""),
                "stage_in_process": held.get("stage_in_process", ""),
                "risk_level": billing.get("risk_level", ""),
                "review_bucket": billing.get("review_bucket", bucket),
                "cleanup_decision": decision,
                "next_charge_date": billing.get("next_charge_date", ""),
                "amount_due": billing.get("amount_due", ""),
                "failure_types": billing.get("failure_types", ""),
                "row_count": billing.get("row_count", ""),
                "next_step": next_step,
                "_packet_index": index,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            BUCKET_ORDER.get(str(row.get("review_bucket") or ""), 99),
            str(row.get("next_charge_date") or "9999-99-99"),
            int(row.get("_packet_index") or 0),
        ),
    )


def markdown_cell(value: Any) -> str:
    text = str(value or "")
    return text.replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, rows: list[dict[str, Any]], generated_at: str) -> None:
    decisions = Counter(str(row.get("cleanup_decision") or "unknown") for row in rows)
    buckets = Counter(str(row.get("review_bucket") or "unknown") for row in rows)
    lines = [
        "# DF AutoFox Billing-Risk Cleanup Packet",
        "",
        f"Generated: {generated_at}",
        "",
        "Use this for the billing-risk clients that specifically blocked the current DF email rollout.",
        "This packet does not approve billing-warning messages or normal outreach.",
        "",
        "## Summary",
        f"- Rollout blockers: {len(rows)}",
    ]
    for decision, count in sorted(decisions.items()):
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## Buckets"])
    for bucket, count in sorted(buckets.items(), key=lambda item: (BUCKET_ORDER.get(item[0], 99), item[0])):
        lines.append(f"- {bucket}: {count}")
    lines.extend(
        [
            "",
            "## Operating Rule",
            "- Clear or explicitly exclude billing-risk clients before they can re-enter normal rollout.",
            "- Review duplicate failure rows once per unique client/key.",
            "- Do not send billing-warning messages without exact owner approval at action time.",
            "",
            "## Cleanup Rows",
            "| Decision | Client | Stage | Bucket | Next charge | Amount | Failure types | Next step |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "cleanup_decision",
                    "client_name",
                    "stage_in_process",
                    "review_bucket",
                    "next_charge_date",
                    "amount_due",
                    "failure_types",
                    "next_step",
                )
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(
    rows: list[dict[str, Any]],
    csv_path: Path = CLEANUP_CSV,
    md_path: Path = CLEANUP_MD,
    generated_at: str | None = None,
) -> dict[str, str]:
    generated_at = generated_at or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    write_csv(csv_path, rows, FIELDS)
    write_markdown(md_path, rows, generated_at)
    return {"csv": relative_label(csv_path), "markdown": relative_label(md_path)}


def build_from_files(packet_path: Path, billing_path: Path) -> list[dict[str, Any]]:
    return build_cleanup_rows(read_json(packet_path), read_csv_rows(billing_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=ROLLOUT_PACKET_JSON, help="DF rollout packet JSON.")
    parser.add_argument("--billing", type=Path, default=BILLING_RISK_REVIEW_CSV, help="Billing risk review CSV.")
    parser.add_argument("--csv", type=Path, default=CLEANUP_CSV, help="Cleanup CSV output.")
    parser.add_argument("--markdown", type=Path, default=CLEANUP_MD, help="Cleanup Markdown output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_from_files(args.packet, args.billing)
    outputs = write_outputs(rows, args.csv, args.markdown)
    print(json.dumps({"rows": len(rows), **outputs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
