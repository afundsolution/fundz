#!/usr/bin/env python3
"""Build a focused cleanup packet for bounced email and live DF hold blockers."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fundz_operational_state import normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
ROLLOUT_PACKET_JSON = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-rollout-packet.json"
OUTPUT_DIR = ROOT / "data" / "local" / "autofox-rollout"
CLEANUP_CSV = OUTPUT_DIR / "df-autofox-live-hold-cleanup.csv"
CLEANUP_MD = OUTPUT_DIR / "df-autofox-live-hold-cleanup.md"

FIELDS = [
    "client_name",
    "client_key",
    "stage_in_process",
    "blocker_type",
    "cleanup_decision",
    "source_reason",
    "next_step",
]

DECISION_ORDER = {
    "repair_bounced_email_route": 0,
    "hold_live_billing_warning": 1,
    "exclude_live_billing_or_payment_hold": 2,
    "already_excluded_until_billing_clears": 3,
    "exclude_archived_or_inactive": 4,
    "hold_manual_live_review": 5,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def cleanup_classification(reason: str) -> tuple[str, str, str] | None:
    lower = reason.lower()
    if lower.startswith("maintenance cleanup block:"):
        if "exclude_bounced_email_route" in lower:
            return (
                "bounce_or_email_failure",
                "exclude_bounced_email_route",
                "Keep out of outreach until a verified replacement email route is recorded and a fresh live preflight clears it.",
            )
        if "repair_bounced_email_route" in lower:
            return (
                "bounce_or_email_failure",
                "repair_bounced_email_route",
                "Keep out of outreach. Verify/correct the DF email route and require one fresh live preflight before any send.",
            )
        if "exclude_live_billing_or_payment_hold" in lower:
            return (
                "live_billing_or_payment_hold",
                "exclude_live_billing_or_payment_hold",
                "Keep out of outreach. Reopen only with fresh live billing proof and a new one-client rollout preview.",
            )
        if "already_excluded_until_billing_clears" in lower:
            return (
                "billing_cleanup_live_hold",
                "already_excluded_until_billing_clears",
                "Keep excluded from outreach until the named billing failure is cleared or Brandon gives exact-client override.",
            )
        if "exclude_archived_or_inactive" in lower:
            return (
                "archived_or_inactive",
                "exclude_archived_or_inactive",
                "Keep out of normal outreach. Reopen only with exact owner instruction and fresh live status proof.",
            )
        if "hold_live_billing_warning" in lower:
            return (
                "live_billing_or_payment_hold",
                "hold_live_billing_warning",
                "Keep on live hold. Recheck DF billing/payment state before any client-facing update.",
            )
        if "hold_manual_live_review" in lower:
            return (
                "live_manual_hold",
                "hold_manual_live_review",
                "Keep on manual live hold until the blocker is reviewed and cleared.",
            )
    if "bounce-route excluded" in lower or "bounced email route excluded" in lower:
        return (
            "bounce_or_email_failure",
            "exclude_bounced_email_route",
            "Keep out of outreach until a verified replacement email route is recorded and a fresh live preflight clears it.",
        )
    if "final rollout exclusion" in lower and any(
        term in lower for term in ("payment", "billing", "card-fail", "card fail", "held-review", "held review")
    ):
        return (
            "live_billing_or_payment_hold",
            "exclude_live_billing_or_payment_hold",
            "Keep out of outreach. Reopen only with fresh live billing proof and a new one-client rollout preview.",
        )
    if "df latest email status" in lower or "bounce" in lower or "bounced" in lower:
        return (
            "bounce_or_email_failure",
            "repair_bounced_email_route",
            "Keep out of outreach. Verify/correct the DF email route and require one fresh live preflight before any send.",
        )
    if "df live client status" in lower and any(
        term in lower for term in ("archived", "inactive", "deleted", "cancelled", "canceled")
    ):
        return (
            "archived_or_inactive",
            "exclude_archived_or_inactive",
            "Keep out of normal outreach. Reopen only with exact owner instruction and fresh live status proof.",
        )
    if not lower.startswith("live df review hold:"):
        return None
    if "billing-risk cleanup decision" in lower:
        return (
            "billing_cleanup_live_hold",
            "already_excluded_until_billing_clears",
            "Keep excluded from outreach until the named billing failure is cleared or Brandon gives exact-client override.",
        )
    if any(term in lower for term in ("payment", "billing", "card-fail", "card fail", "held-review", "held review")):
        return (
            "live_billing_or_payment_hold",
            "hold_live_billing_warning",
            "Keep on live hold. Recheck DF billing/payment state before any client-facing update.",
        )
    return (
        "live_manual_hold",
        "hold_manual_live_review",
        "Keep on manual live hold until the blocker is reviewed and cleared.",
    )


def build_cleanup_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for held in packet.get("held_candidates", []):
        reason = str(held.get("reason") or "")
        classification = cleanup_classification(reason)
        if not classification:
            continue
        blocker_type, decision, next_step = classification
        client_key = str(held.get("client_key") or "").strip()
        client_name = str(held.get("client_name") or "").strip()
        dedupe_key = client_key or normalize_name(client_name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(
            {
                "client_name": client_name,
                "client_key": client_key,
                "stage_in_process": held.get("stage_in_process", ""),
                "blocker_type": blocker_type,
                "cleanup_decision": decision,
                "source_reason": reason,
                "next_step": next_step,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            DECISION_ORDER.get(str(row.get("cleanup_decision") or ""), 99),
            str(row.get("client_name") or "").lower(),
        ),
    )


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, rows: list[dict[str, Any]], generated_at: str) -> None:
    decisions = Counter(str(row.get("cleanup_decision") or "unknown") for row in rows)
    blockers = Counter(str(row.get("blocker_type") or "unknown") for row in rows)
    lines = [
        "# DF AutoFox Bounce + Live-Hold Cleanup Packet",
        "",
        f"Generated: {generated_at}",
        "",
        "Use this for bounced email and live DF hold blockers from the current rollout packet.",
        "This packet does not approve sends, SMS, billing-warning messages, or broad outreach.",
        "",
        "## Summary",
        f"- Cleanup rows: {len(rows)}",
    ]
    for decision, count in sorted(decisions.items(), key=lambda item: (DECISION_ORDER.get(item[0], 99), item[0])):
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## Blocker Types"])
    for blocker, count in sorted(blockers.items()):
        lines.append(f"- {blocker}: {count}")
    lines.extend(
        [
            "",
            "## Operating Rule",
            "- Bounced email must be repaired or excluded before any email retry.",
            "- Live payment, card-fail, billing, archived, or inactive holds stay out of outreach until fresh live proof clears them.",
            "- Do not convert any row here into a send row without a new one-client rollout preview.",
            "",
            "## Cleanup Rows",
            "| Decision | Client | Stage | Blocker | Next step | Reason |",
            "| --- | --- | --- | --- | --- | --- |",
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
                    "blocker_type",
                    "next_step",
                    "source_reason",
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


def build_from_files(packet_path: Path) -> list[dict[str, Any]]:
    return build_cleanup_rows(read_json(packet_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=ROLLOUT_PACKET_JSON, help="DF rollout packet JSON.")
    parser.add_argument("--csv", type=Path, default=CLEANUP_CSV, help="Cleanup CSV output.")
    parser.add_argument("--markdown", type=Path, default=CLEANUP_MD, help="Cleanup Markdown output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_from_files(args.packet)
    outputs = write_outputs(rows, args.csv, args.markdown)
    print(json.dumps({"rows": len(rows), **outputs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
