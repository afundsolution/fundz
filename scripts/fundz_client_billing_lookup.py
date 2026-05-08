#!/usr/bin/env python3
"""Answer a FUNDz client billing/monitoring question from local evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from fundz_operational_state import normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
CLIENT_STATE_SUMMARY_CSV = ROOT / "data" / "local" / "fundz-client-state-summary.csv"
BILLING_MAINTENANCE_CSV = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-billing-maintenance-review.csv"
DUPLICATE_BILLING_CSV = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-duplicate-billing-review.csv"
SCOREFUSION_ROSTER_CSV = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "client-billing-roster.csv"
SCOREFUSION_RISK_CSV = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"
ARCHIVE_REVIEW_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-archive-review.csv"
LIVE_HOLD_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-live-hold-cleanup.csv"
DF_MONITORING_PROOF_CSV = ROOT / "data" / "local" / "billing-intelligence" / "df-credit-monitoring-proof.csv"
AUTOPILOT_STATUS_MD = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-autopilot-status.md"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def lookup_by_name(path: Path, client_name: str) -> list[dict[str, str]]:
    wanted = normalize_name(client_name)
    rows: list[dict[str, str]] = []
    for row in read_csv_rows(path):
        row_name = normalize_name(str(row.get("client_name") or row.get("name") or ""))
        if row_name == wanted:
            rows.append(row)
    return rows


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def clean_row(row: dict[str, str], fields: tuple[str, ...]) -> dict[str, str]:
    return {field: str(row.get(field) or "") for field in fields if str(row.get(field) or "")}


def scorefusion_found(*row_groups: list[dict[str, str]]) -> bool:
    return any(group for group in row_groups)


def build_lookup(client_name: str) -> dict[str, Any]:
    state_rows = lookup_by_name(CLIENT_STATE_SUMMARY_CSV, client_name)
    maintenance_rows = lookup_by_name(BILLING_MAINTENANCE_CSV, client_name)
    duplicate_rows = lookup_by_name(DUPLICATE_BILLING_CSV, client_name)
    roster_rows = lookup_by_name(SCOREFUSION_ROSTER_CSV, client_name)
    risk_rows = lookup_by_name(SCOREFUSION_RISK_CSV, client_name)
    archive_rows = lookup_by_name(ARCHIVE_REVIEW_CSV, client_name)
    live_hold_rows = lookup_by_name(LIVE_HOLD_CSV, client_name)
    monitoring_rows = lookup_by_name(DF_MONITORING_PROOF_CSV, client_name)

    state = first(state_rows)
    maintenance = first(maintenance_rows)
    roster = first(roster_rows)
    archive = first(archive_rows)
    live_hold = first(live_hold_rows)
    monitoring = first(monitoring_rows)
    found_scorefusion = scorefusion_found(maintenance_rows, duplicate_rows, roster_rows, risk_rows, archive_rows)

    if found_scorefusion:
        scorefusion_status = "found_in_local_scorefusion_evidence"
        plain_status = "Local evidence found ScoreFusion billing/monitoring evidence for this client."
    elif state_rows:
        scorefusion_status = "not_found_check_alternate_monitoring_provider"
        plain_status = (
            "ScoreFusion evidence does not show an active ScoreFusion record. "
            "Check alternate monitoring provider such as MyScoreIQ."
        )
    else:
        scorefusion_status = "client_not_found_in_local_fundz_state"
        plain_status = "This client was not found in the local FUNDz client-state summary."

    result = {
        "client_name": client_name,
        "local_fundz_client_found": bool(state_rows),
        "local_scorefusion_status": scorefusion_status,
        "plain_status": plain_status,
        "fundz_state": clean_row(
            state,
            (
                "client_name",
                "is_active_client",
                "status",
                "stage_in_process",
                "dispute_round",
                "onboarding_percent",
                "flags",
                "recommended_next_action",
            ),
        ),
        "scorefusion_evidence": {
            "maintenance": clean_row(
                maintenance,
                (
                    "decision",
                    "risk_level",
                    "review_buckets",
                    "amount_due",
                    "row_count",
                    "duplicate_row_count",
                    "failure_types",
                    "next_charge_date",
                    "next_step",
                ),
            ),
            "roster": clean_row(
                roster,
                (
                    "next_charge_date",
                    "amount_due",
                    "billing_status",
                    "highlevel_pipeline_stage",
                    "notes_owner_action",
                ),
            ),
            "archive": clean_row(
                archive,
                (
                    "scorefusion_presence",
                    "billing_status",
                    "next_charge_date",
                    "amount_due",
                    "archive_decision",
                    "next_action",
                ),
            ),
            "live_hold": clean_row(
                live_hold,
                (
                    "blocker_type",
                    "cleanup_decision",
                    "next_step",
                ),
            ),
            "df_credit_monitoring": clean_row(
                monitoring,
                (
                    "monitoring_agency",
                    "app_status_provider",
                    "app_status",
                    "verified_at",
                    "proof_source",
                    "notes",
                ),
            ),
        },
        "duplicate_billing_rows_found": len(duplicate_rows),
        "risk_rows_found": len(risk_rows),
        "source_files": {
            "client_state": relative_label(CLIENT_STATE_SUMMARY_CSV),
            "billing_maintenance": relative_label(BILLING_MAINTENANCE_CSV),
            "scorefusion_roster": relative_label(SCOREFUSION_ROSTER_CSV),
            "df_credit_monitoring_proof": relative_label(DF_MONITORING_PROOF_CSV),
            "autopilot_status": relative_label(AUTOPILOT_STATUS_MD),
        },
        "live_proof_rule": "Use this as local evidence only. Fresh live DF/ScoreFusion or alternate-provider proof is required before account action.",
    }
    return result


def answer_text(result: dict[str, Any]) -> str:
    name = str(result.get("client_name") or "Client")
    fundz_state = result.get("fundz_state") or {}
    lines = [f"Local billing view for {name}:"]
    if fundz_state:
        lines.append(
            "- FUNDz/DisputeFox: "
            + ", ".join(
                part
                for part in (
                    str(fundz_state.get("status") or ""),
                    str(fundz_state.get("stage_in_process") or ""),
                    f"onboarding {fundz_state.get('onboarding_percent')}%" if fundz_state.get("onboarding_percent") else "",
                )
                if part
            )
        )
    lines.append(f"- ScoreFusion: {result.get('plain_status')}")
    evidence = result.get("scorefusion_evidence") or {}
    maintenance = evidence.get("maintenance") or {}
    roster = evidence.get("roster") or {}
    monitoring = evidence.get("df_credit_monitoring") or {}
    if monitoring:
        agency = monitoring.get("monitoring_agency")
        app_provider = monitoring.get("app_status_provider")
        app_status = monitoring.get("app_status")
        parts = []
        if agency:
            parts.append(f"monitoring agency {agency}")
        if app_provider or app_status:
            parts.append(" / ".join(part for part in (app_provider, app_status) if part))
        lines.append(f"- DF credit monitoring proof: {', '.join(parts)}")
    if maintenance:
        lines.append(f"- Billing bucket: {maintenance.get('decision', 'review')}")
        if maintenance.get("failure_types"):
            lines.append(f"- Failure type: {maintenance['failure_types']}")
        if maintenance.get("next_charge_date"):
            lines.append(f"- Next charge: {maintenance['next_charge_date']}")
        if maintenance.get("amount_due"):
            lines.append(f"- Amount due: {maintenance['amount_due']}")
    elif roster:
        lines.append(f"- Billing status: {roster.get('billing_status', 'local roster row found')}")
        if roster.get("next_charge_date"):
            lines.append(f"- Next charge: {roster['next_charge_date']}")
        if roster.get("amount_due"):
            lines.append(f"- Amount due: {roster['amount_due']}")
    lines.append(f"- Proof rule: {result.get('live_proof_rule')}")
    return "\n".join(lines)


def monitoring_reply_text(result: dict[str, Any]) -> str:
    name = str(result.get("client_name") or "Client")
    evidence = result.get("scorefusion_evidence") or {}
    monitoring = evidence.get("df_credit_monitoring") or {}
    status = str(result.get("local_scorefusion_status") or "")
    if monitoring:
        agency = str(monitoring.get("monitoring_agency") or "alternate provider")
        app_provider = str(monitoring.get("app_status_provider") or "DF app card")
        app_status = str(monitoring.get("app_status") or "status recorded")
        return f"{name}: No active ScoreFusion. DF has {agency} as the CMS; {app_provider} shows {app_status}."
    if status == "found_in_local_scorefusion_evidence":
        return f"{name}: local evidence found ScoreFusion billing/monitoring evidence."
    if status == "not_found_check_alternate_monitoring_provider":
        return f"{name}: No active ScoreFusion shown. Check alternate CMS."
    return f"I could not find {name} in the local FUNDz client-state summary. Send the full DF client name."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_name", help="Client name to look up.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of plain text.")
    parser.add_argument("--monitoring-reply", action="store_true", help="Print a compact owner-facing monitoring answer.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_lookup(args.client_name)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.monitoring_reply:
        print(monitoring_reply_text(result))
    else:
        print(answer_text(result))


if __name__ == "__main__":
    main()
