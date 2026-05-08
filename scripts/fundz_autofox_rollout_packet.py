#!/usr/bin/env python3
"""Build a DF/AutoFox-ready rollout packet with FUNDz safety gates."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any

import fundz_semi_autonomous_bot as semi
from fundz_autonomy_daemon import risky_language_hits
from fundz_operational_state import build_operational_state, normalize_name, relative_label


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "autofox-rollout"
PACKET_JSON = OUTPUT_DIR / "df-autofox-rollout-packet.json"
PREVIEW_MD = OUTPUT_DIR / "df-autofox-rollout-preview.md"
IMPORT_CSV = OUTPUT_DIR / "df-autofox-rollout-import.csv"
EXECUTION_MD = OUTPUT_DIR / "df-autofox-rollout-execution.md"
LIVE_REVIEW_CSV = OUTPUT_DIR / "df-autofox-live-review.csv"
MAINTENANCE_CLEANUP_CSV = OUTPUT_DIR / "df-autofox-live-hold-cleanup.csv"
CONTROL_BOARD_CSV = ROOT / "data" / "local" / "command-center" / "fundz-client-communication-control-board.csv"
DISPUTE_FOX_DIR = ROOT / "data" / "dispute-fox"

ROUND_CAMPAIGNS: dict[int, dict[str, str]] = {
    1: {"workflow": "Client (step 04) - Round 1 Sent & Campaign", "autofox_id": "160038"},
    2: {"workflow": "Client (step 06) - Round 2 Sent & Campaign", "autofox_id": "160044"},
    3: {"workflow": "Client (step 08) - Round 3 Sent & Campaign", "autofox_id": "160054"},
    4: {"workflow": "Client (step 10) - Round 4 Sent & Campaign", "autofox_id": "160055"},
    5: {"workflow": "Client (step 12) - Round 5 Sent & Campaign", "autofox_id": "160061"},
    6: {"workflow": "Client (step 14) - Round 6 Sent & Campaign", "autofox_id": "160063"},
    7: {"workflow": "Client (step 16) - Round 7 Sent & Campaign", "autofox_id": "160065"},
    8: {"workflow": "Client (step 18) - Round 8 Sent & Campaign", "autofox_id": "160067"},
    9: {"workflow": "Client (step 20) - Round 9 Sent & Campaign", "autofox_id": "160069"},
    10: {"workflow": "Client (step 22) - Round 10 Sent & Campaign", "autofox_id": "160071"},
}

CSV_FIELDS = [
    "client_name",
    "client_key",
    "email",
    "status",
    "stage_in_process",
    "round",
    "df_email_ready",
    "mobile_app_sms_ready",
    "app_readiness",
    "autofox_workflow",
    "autofox_id",
    "customer_id",
    "customer_url",
    "recommended_df_action",
    "message",
]

BLOCKING_MAINTENANCE_DECISIONS = {
    "repair_bounced_email_route",
    "hold_live_billing_warning",
    "exclude_live_billing_or_payment_hold",
    "already_excluded_until_billing_clears",
    "exclude_archived_or_inactive",
    "hold_manual_live_review",
    "exclude_bounced_email_route",
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


def control_lookup(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or CONTROL_BOARD_CSV
    lookup: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        name_key = normalize_name(str(row.get("client_name") or ""))
        client_key = str(row.get("client_key") or "").strip().lower()
        if name_key:
            lookup[name_key] = row
        if client_key:
            lookup[client_key] = row
    return lookup


def customer_url_lookup(source_dir: Path | None = None) -> dict[str, dict[str, str]]:
    source_dir = source_dir or DISPUTE_FOX_DIR
    lookup: dict[str, dict[str, str]] = {}
    for path in source_dir.glob("*active-clients*.csv"):
        for row in read_csv_rows(path):
            customer_url = str(row.get("customer_url") or "").strip()
            customer_id = str(row.get("customer_id") or "").strip()
            if not customer_url and not customer_id:
                continue
            value = {"customer_url": customer_url, "customer_id": customer_id}
            name_key = normalize_name(str(row.get("client_name") or ""))
            client_key = str(row.get("client_key") or "").strip().lower()
            email_key = str(row.get("email") or "").strip().lower()
            if name_key:
                lookup[name_key] = value
            if client_key:
                lookup[client_key] = value
            if email_key:
                lookup[email_key] = value
    return lookup


def live_review_lookup(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or LIVE_REVIEW_CSV
    lookup: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        name_key = normalize_name(str(row.get("client_name") or ""))
        client_key = str(row.get("client_key") or "").strip().lower()
        email_key = str(row.get("email") or "").strip().lower()
        for key in (name_key, client_key, email_key):
            if key:
                lookup[key] = row
    return lookup


def maintenance_cleanup_lookup(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or MAINTENANCE_CLEANUP_CSV
    lookup: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        decision = str(row.get("cleanup_decision") or "").strip().lower()
        if decision not in BLOCKING_MAINTENANCE_DECISIONS:
            continue
        name_key = normalize_name(str(row.get("client_name") or ""))
        client_key = str(row.get("client_key") or "").strip().lower()
        for key in (name_key, client_key):
            if key:
                lookup[key] = row
    return lookup


def lookup_control(client: dict[str, Any], controls: dict[str, dict[str, str]]) -> dict[str, str]:
    return controls.get(str(client.get("client_key") or "").strip().lower()) or controls.get(
        normalize_name(str(client.get("client_name") or ""))
    ) or {}


def lookup_customer_url(client: dict[str, Any], customers: dict[str, dict[str, str]]) -> dict[str, str]:
    return (
        customers.get(str(client.get("client_key") or "").strip().lower())
        or customers.get(normalize_name(str(client.get("client_name") or "")))
        or customers.get(str(client.get("email") or "").strip().lower())
        or {}
    )


def lookup_live_review(client: dict[str, Any], reviews: dict[str, dict[str, str]]) -> dict[str, str]:
    return (
        reviews.get(str(client.get("client_key") or "").strip().lower())
        or reviews.get(normalize_name(str(client.get("client_name") or "")))
        or reviews.get(str(client.get("email") or "").strip().lower())
        or {}
    )


def lookup_maintenance_cleanup(client: dict[str, Any], cleanup_rows: dict[str, dict[str, str]]) -> dict[str, str]:
    return cleanup_rows.get(str(client.get("client_key") or "").strip().lower()) or cleanup_rows.get(
        normalize_name(str(client.get("client_name") or ""))
    ) or {}


def round_number(client: dict[str, Any]) -> int | None:
    number = client.get("dispute_round", {}).get("number") if isinstance(client.get("dispute_round"), dict) else None
    if isinstance(number, int):
        return number
    match = re.search(r"\bround\s+(\d+)\b", str(client.get("stage_in_process") or ""), re.I)
    return int(match.group(1)) if match else None


def prior_sent_batch(client: dict[str, Any], sent_lookup: dict[str, str]) -> str:
    return semi.sent_batch_for_client(client, sent_lookup)


def billing_bucket(client: dict[str, Any], billing_lookup: dict[str, str]) -> str:
    return semi.billing_risk_bucket_for_client(client, "Email", billing_lookup)


def hold_item(client: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "client_name": client.get("client_name", ""),
        "client_key": client.get("client_key", ""),
        "email": client.get("email", ""),
        "status": client.get("status", ""),
        "stage_in_process": client.get("stage_in_process", ""),
        "round": round_number(client),
        "reason": reason,
    }


def text_matches_any(text: str, terms: tuple[str, ...]) -> str:
    lower = text.lower()
    for term in terms:
        if term in lower:
            return term
    return ""


def first_text(row: dict[str, str], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def maintenance_cleanup_reason(row: dict[str, str]) -> str:
    decision = str(row.get("cleanup_decision") or "").strip()
    blocker = str(row.get("blocker_type") or "").strip()
    next_step = str(row.get("next_step") or "").strip()
    source_reason = str(row.get("source_reason") or "").strip()
    parts = [part for part in (decision, blocker) if part]
    label = " / ".join(parts) if parts else "maintenance cleanup block"
    detail = next_step or source_reason
    return f"maintenance cleanup block: {label}" + (f" - {detail}" if detail else "")


def hard_stop_reason(client: dict[str, Any], control: dict[str, str], live_review: dict[str, str]) -> str:
    status_sources = [
        ("client status", str(client.get("status") or "")),
        ("client stage", str(client.get("stage_in_process") or "")),
        ("control-board status", str(control.get("communication_status") or "")),
        (
            "DF live client status",
            first_text(live_review, "df_client_status", "client_status", "dashboard_status", "account_status"),
        ),
    ]
    for label, text in status_sources:
        if text_matches_any(text, ("archived", "deleted", "inactive", "cancelled", "canceled")):
            return f"{label}: {text}"

    email_status = first_text(
        live_review,
        "latest_email_status",
        "last_email_status",
        "email_status",
        "email_delivery_status",
        "df_email_status",
    )
    if text_matches_any(email_status, ("bounce", "bounced", "undeliver", "failed", "failure", "rejected", "invalid")):
        return f"DF latest email status: {email_status}"

    live_decision = first_text(live_review, "rollout_decision", "review_decision", "decision")
    if live_decision and text_matches_any(live_decision, ("hold", "block", "exclude", "no send", "no_send")):
        live_hold = first_text(live_review, "hold_reason", "reason")
        if live_hold:
            return f"live DF review hold: {live_hold}"
        return f"live DF review decision: {live_decision}"

    live_hold = first_text(live_review, "hold_reason", "reason")
    if live_hold:
        return f"live DF review hold: {live_hold}"

    return ""


def evaluate_client(
    client: dict[str, Any],
    controls: dict[str, dict[str, str]],
    sent_lookup: dict[str, str],
    billing_lookup: dict[str, str],
    customers: dict[str, dict[str, str]],
    live_reviews: dict[str, dict[str, str]],
    maintenance_cleanup: dict[str, dict[str, str]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not client.get("is_active_client"):
        return None, hold_item(client, "not an active DisputeFox client")

    action_type, action_reason = semi.action_type_for_client(client)
    if action_type != "draft_for_approval":
        return None, hold_item(client, action_reason)

    email = str(client.get("email") or "").strip().lower()
    if not email:
        return None, hold_item(client, "missing DisputeFox email")

    prior_batch = prior_sent_batch(client, sent_lookup)
    if prior_batch:
        return None, hold_item(client, f"already sent in prior receipt: {prior_batch}")

    control = lookup_control(client, controls)
    customer = lookup_customer_url(client, customers)
    live_review = lookup_live_review(client, live_reviews)
    stop_reason = hard_stop_reason(client, control, live_review)
    if stop_reason:
        return None, hold_item(client, stop_reason)

    cleanup_row = lookup_maintenance_cleanup(client, maintenance_cleanup)
    if cleanup_row:
        return None, hold_item(client, maintenance_cleanup_reason(cleanup_row))

    bucket = billing_bucket(client, billing_lookup)
    if bucket:
        return None, hold_item(client, f"billing-risk review queue: {bucket}")

    message = semi.safe_client_message(client)
    risky_hits = risky_language_hits(message)
    if risky_hits:
        return None, hold_item(client, f"risky-language hits: {', '.join(risky_hits)}")

    communication_status = str(control.get("communication_status") or "").lower()
    if communication_status.startswith(("blocked", "failed", "hold")):
        return None, hold_item(client, f"control-board status: {control.get('communication_status')}")
    if str(control.get("email_allowed") or "yes").lower().startswith("no"):
        return None, hold_item(client, "control-board email gate is no")

    app_readiness = str(control.get("app_readiness") or "Unknown - verify DF app status")
    campaign = ROUND_CAMPAIGNS.get(round_number(client) or 0, {})
    mobile_app_ready = app_readiness == "Installed / Logged In" and bool(campaign)
    recommended_action = (
        "Assign verified round campaign in DF/AutoFox; email and Mobile App SMS are allowed for this client."
        if mobile_app_ready
        else "Send DF email only now. Do not use Mobile App SMS until DF shows Installed / Logged In."
    )
    if not campaign:
        recommended_action += " No verified round 1-10 AutoFox campaign is mapped for this stage."

    item = {
        "client_name": client.get("client_name", ""),
        "client_key": client.get("client_key", ""),
        "email": email,
        "status": client.get("status", ""),
        "stage_in_process": client.get("stage_in_process", ""),
        "round": round_number(client),
        "df_email_ready": True,
        "mobile_app_sms_ready": mobile_app_ready,
        "app_readiness": app_readiness,
        "autofox_workflow": campaign.get("workflow", ""),
        "autofox_id": campaign.get("autofox_id", ""),
        "customer_id": customer.get("customer_id", ""),
        "customer_url": customer.get("customer_url", ""),
        "recommended_df_action": recommended_action,
        "message": message,
    }
    return item, None


def build_packet(size: int, scan_limit: int) -> dict[str, Any]:
    semi.load_env_file()
    state, queue = semi.run_once(limit=max(scan_limit, size))
    clients_by_key = semi.clients_by_key(state)
    controls = control_lookup()
    customers = customer_url_lookup()
    live_reviews = live_review_lookup()
    maintenance_cleanup = maintenance_cleanup_lookup()
    sent_lookup = semi.sent_batch_lookup()
    billing_lookup = semi.billing_risk_lookup()
    ready: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    seen: set[str] = set()

    for action in queue.get("actions", []):
        client_key = str(action.get("client_key") or "")
        if client_key in seen:
            continue
        seen.add(client_key)
        if action.get("action_type") != "draft_for_approval":
            continue
        client = clients_by_key.get(client_key)
        if not client:
            continue
        item, hold = evaluate_client(
            client,
            controls,
            sent_lookup,
            billing_lookup,
            customers,
            live_reviews,
            maintenance_cleanup,
        )
        if hold:
            held.append(hold)
            continue
        if item:
            ready.append(item)
            if len(ready) >= size:
                break

    packet = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "df_autofox_rollout_preview",
        "approval_required": True,
        "live_send_allowed": False,
        "requested_size": size,
        "selected": len(ready),
        "held_before_packet": len(held),
        "scan_limit": scan_limit,
        "live_review_observations": len({id(row) for row in live_reviews.values()}),
        "policy": (
            "FUNDz selects safe clients. DF/AutoFox is the send path. "
            "Email can proceed from DF after exact approval; Mobile App SMS requires Installed / Logged In proof."
        ),
        "items": ready,
        "held_candidates": held,
    }
    return packet


def write_preview(packet: dict[str, Any], path: Path = PREVIEW_MD) -> None:
    lines = [
        "# FUNDz DF/AutoFox Rollout Preview",
        "",
        f"Generated: {packet.get('created_at')}",
        f"Selected: {packet.get('selected', 0)}",
        f"Held before packet: {packet.get('held_before_packet', 0)}",
        f"Live safety observations: {packet.get('live_review_observations', 0)}",
        "",
        "Policy: DF/AutoFox is the sender. FUNDz only prepares this safe packet; live sends still need exact approval.",
        "",
        "## Ready For DF/AutoFox",
    ]
    if not packet.get("items"):
        lines.append("- None.")
    for item in packet.get("items", []):
        lines.extend(
            [
                "",
                f"### {item.get('client_name')}",
                f"- Stage: {item.get('stage_in_process')}",
                f"- DF email ready: {item.get('df_email_ready')}",
                f"- Mobile App SMS ready: {item.get('mobile_app_sms_ready')}",
                f"- App readiness: {item.get('app_readiness')}",
                f"- AutoFox workflow: {item.get('autofox_workflow') or 'not mapped for this round'}",
                f"- AutoFox ID: {item.get('autofox_id') or 'not mapped'}",
                f"- DF dashboard: {item.get('customer_url') or 'not found in active-client table'}",
                f"- Action: {item.get('recommended_df_action')}",
                f"- Message: {item.get('message')}",
            ]
        )
    lines.extend(["", "## Held Before Packet"])
    for item in packet.get("held_candidates", [])[:50]:
        lines.append(
            f"- {item.get('client_name')} | {item.get('status')} | {item.get('stage_in_process')} | {item.get('reason')}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_execution_checklist(packet: dict[str, Any], path: Path = EXECUTION_MD) -> None:
    lines = [
        "# FUNDz DF Email Execution Checklist",
        "",
        f"Generated: {packet.get('created_at')}",
        "",
        "Use this only for the exact packet below. Send DF Email only. Do not assign Mobile App SMS unless the client shows Installed / Logged In.",
        "",
        "## Before Sending",
        "- Confirm the client page matches the listed name.",
        "- Confirm the client is not archived/deleted/inactive on the live DF page.",
        "- Confirm no billing/payment warning is visible before sending.",
        "- Confirm the latest email status is not bounced/failed before sending.",
        "- Confirm this is email only; do not start AutoFox Mobile App SMS for these clients.",
        "- After each send, record proof/status before moving to the next client.",
        "",
        "## Exact Send List",
    ]
    for index, item in enumerate(packet.get("items", []), start=1):
        lines.extend(
            [
                "",
                f"### {index}. {item.get('client_name')}",
                f"- DF dashboard: {item.get('customer_url') or 'not found'}",
                f"- Stage: {item.get('stage_in_process')}",
                f"- Subject: FUNDz update",
                f"- Message: {item.get('message')}",
                "- Execution status: pending",
                "- Proof/receipt: pending",
            ]
        )
    lines.extend(
        [
            "",
            "## Stop Conditions",
            "- Any payment/billing warning appears.",
            "- DF page does not match the listed client.",
            "- Email send fails or lands in pending/in-progress without proof.",
            "- Any UI path would also trigger SMS/App SMS.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(packet: dict[str, Any]) -> dict[str, str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PACKET_JSON.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(IMPORT_CSV, packet.get("items", []), CSV_FIELDS)
    write_preview(packet, PREVIEW_MD)
    write_execution_checklist(packet, EXECUTION_MD)
    return {
        "packet": relative_label(PACKET_JSON),
        "preview": relative_label(PREVIEW_MD),
        "import_csv": relative_label(IMPORT_CSV),
        "execution": relative_label(EXECUTION_MD),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=5, help="Max ready clients to include.")
    parser.add_argument("--scan-limit", type=int, default=250, help="How many queue actions to scan.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packet = build_packet(size=max(args.size, 1), scan_limit=max(args.scan_limit, args.size, 1))
    outputs = write_outputs(packet)
    print(
        json.dumps(
            {
                "selected": packet.get("selected", 0),
                "held_before_packet": packet.get("held_before_packet", 0),
                **outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
