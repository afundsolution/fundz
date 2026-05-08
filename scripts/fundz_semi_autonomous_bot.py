#!/usr/bin/env python3
"""Run FUNDz in semi-autonomous mode with human approval gates for live sends."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import redact_sensitive, risky_language_hits
from fundz_credit_tracker_bridge import (
    build_outbound_payload,
    load_env_file,
    looks_like_e164_phone,
    looks_like_email,
    send_reply,
    should_auto_reply,
)
from fundz_operational_state import (
    DEFAULT_OUTPUT,
    DEFAULT_SUMMARY_CSV,
    build_operational_state,
    relative_label,
    write_json,
    write_summary_csv,
)
from fundz_resolve_highlevel_contact import contact_summary, resolve_contact


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data" / "local" / "semi-autonomous"
ACTION_QUEUE = RUN_DIR / "fundz-action-queue.json"
ACTION_REPORT = RUN_DIR / "fundz-action-queue.md"
PILOT_PACKET = RUN_DIR / "pilot-packet.json"
BATCH_PACKET = RUN_DIR / "expansion-batch-packet.json"
BATCH_REPORT = RUN_DIR / "expansion-batch-preview.md"
BATCH_RECEIPT_DIR = RUN_DIR / "receipts"
READY_ROLLOUT_PRESET = "capped_ready_rollout"
BILLING_RISK_REVIEW_CSV = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"

SAFE_PILOT_MESSAGE = (
    "Hi {first_name}, this is a controlled FUNDz test message. "
    "Please reply received if you get this."
)
CREDIT_MONITORING_NOTE = (
    "In the meantime, you can also check Credit Karma or another credit monitoring service "
    "if you want to watch for changes sooner."
)
MESSAGE_TEMPLATES = {
    "next_round": [
        (
            "Hi {first}, quick FUNDz update: your file is due for the next dispute round. "
            "We are reviewing the latest import and will update you when the next round is ready. {credit_note}"
        ),
        (
            "Hi {first}, FUNDz update: your next dispute round is coming up now. "
            "We are checking the tracker details before the next step goes out. {credit_note}"
        ),
        (
            "Hi {first}, your file is in a next-round review window. "
            "We are checking the latest reporting details and will send the next clear update when it is ready. {credit_note}"
        ),
    ],
    "active_dispute_with_import": [
        (
            "Hi {first}, quick FUNDz update: your {round_label} is active. "
            "We are monitoring the tracker, with the next import showing in {next_days} day(s). {credit_note}"
        ),
        (
            "Hi {first}, your {round_label} is still active. "
            "We are watching the tracker and the next import currently shows in {next_days} day(s). {credit_note}"
        ),
    ],
    "active_dispute": [
        (
            "Hi {first}, quick FUNDz update: your {round_label} is active. "
            "We are monitoring the tracker and will update you when there is movement. {credit_note}"
        ),
        (
            "Hi {first}, your file is still in active dispute review. "
            "We are watching for tracker movement and will update you when there is a clear next step. {credit_note}"
        ),
    ],
    "default": [
        (
            "Hi {first}, quick FUNDz update: we are reviewing your file and will follow up "
            "when the next tracker update is ready."
        ),
        (
            "Hi {first}, FUNDz update: your file is still on our review list, and we will follow up "
            "when the next tracker update is ready."
        ),
    ],
}
PILOT_EMAIL_TEMPLATE = json.dumps(
    {
        "type": "{message_type}",
        "contactId": "{contact_id}",
        "subject": "{email_subject}",
        "html": "<p>{message_html}</p>",
        "message": "{message}",
    }
)
PILOT_SMS_TEMPLATE = json.dumps(
    {
        "type": "{message_type}",
        "contactId": "{contact_id}",
        "message": "{message}",
    }
)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def first_name(name: str) -> str:
    clean = (name or "there").strip()
    return clean.split()[0] if clean else "there"


def normalize_lookup_value(value: Any) -> str:
    text = re.sub(r"\s*\*\s*new\b", "", str(value or "").lower())
    text = re.sub(r"[^a-z0-9@._+-]+", " ", text).strip()
    return " ".join(text.split())


def stable_index(key: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def message_phase_for_client(client: dict[str, Any]) -> str:
    flags = set(client.get("operational_flags", []))
    if "due_for_next_round" in flags:
        return "next_round"
    if "in_dispute" in flags and isinstance(client.get("next_import_days"), int):
        return "active_dispute_with_import"
    if "in_dispute" in flags:
        return "active_dispute"
    return "default"


def safe_client_message(client: dict[str, Any]) -> str:
    first = first_name(str(client.get("client_name") or "there"))
    phase = message_phase_for_client(client)
    options = MESSAGE_TEMPLATES[phase]
    template = options[stable_index(str(client.get("client_key") or client.get("client_name") or ""), len(options))]
    return template.format(
        first=first,
        round_label=str(client.get("dispute_round", {}).get("label") or "dispute round").lower(),
        next_days=client.get("next_import_days"),
        credit_note=CREDIT_MONITORING_NOTE,
    )


def action_priority_score(client: dict[str, Any]) -> int:
    flags = set(client.get("operational_flags", []))
    score = 0
    if "payment_attention" in flags:
        score += 95
    if "due_for_next_round" in flags:
        score += 80
    if "missing_next_import" in flags:
        score += 70
    if "setup_incomplete" in flags or "onboarding_incomplete" in flags:
        score += 60
    if "no_send_history_linked" in flags:
        score += 45
    if "in_dispute" in flags:
        score += 25
    next_days = client.get("next_import_days")
    if isinstance(next_days, int) and next_days <= 3:
        score += 15
    return score


def action_type_for_client(client: dict[str, Any]) -> tuple[str, str]:
    flags = set(client.get("operational_flags", []))
    if "payment_attention" in flags:
        return "owner_review", "Payment/billing attention detected before any client follow-up."
    if "setup_incomplete" in flags or "onboarding_incomplete" in flags:
        return "owner_review", "Onboarding is incomplete; keep this out of autonomous sends."
    if "missing_next_import" in flags:
        return "owner_review", "Next import is missing and should be checked in DisputeFox."
    if "due_for_next_round" in flags:
        return "draft_for_approval", "Client is due for next round; draft only until owner approves."
    if "in_dispute" in flags:
        return "monitor", "Dispute is active; monitor unless the owner requests an update."
    return "monitor", "No immediate semi-autonomous action needed."


def build_action_queue(state: dict[str, Any], limit: int = 250) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for client in state.get("clients", []):
        if not client.get("is_active_client"):
            continue
        action_type, reason = action_type_for_client(client)
        draft = ""
        if action_type in {"draft_for_approval", "monitor"}:
            draft = safe_client_message(client)
        risky_hits = risky_language_hits(draft) if draft else []
        if risky_hits:
            action_type = "blocked"
            reason = "Draft contained risky language and was blocked before approval."

        actions.append(
            {
                "client_key": client.get("client_key"),
                "client_name": client.get("client_name"),
                "status": client.get("status"),
                "next_import": client.get("next_import"),
                "stage_in_process": client.get("stage_in_process"),
                "flags": client.get("operational_flags", []),
                "action_type": action_type,
                "reason": reason,
                "draft": draft,
                "risky_hits": risky_hits,
                "send_allowed_without_owner": False,
                "priority_score": action_priority_score(client),
                "message_phase": message_phase_for_client(client),
            }
        )

    priority = {
        "blocked": 0,
        "owner_review": 1,
        "draft_for_approval": 2,
        "monitor": 3,
    }
    actions.sort(key=lambda item: (priority.get(str(item["action_type"]), 9), -int(item.get("priority_score", 0)), str(item["client_name"]).lower()))
    actions = actions[: max(limit, 0)]
    counts: dict[str, int] = {}
    for action in actions:
        key = str(action["action_type"])
        counts[key] = counts.get(key, 0) + 1

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "semi-autonomous",
        "policy": "Draft, monitor, audit, and prepare only. Live sends require explicit pilot approval.",
        "summary": counts,
        "actions": actions,
    }


def write_action_queue(queue: dict[str, Any], json_path: Path = ACTION_QUEUE, md_path: Path = ACTION_REPORT) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# FUNDz Semi-Autonomous Action Queue",
        "",
        f"Generated: {queue.get('generated_at')}",
        "",
        "## Summary",
    ]
    for key, count in queue.get("summary", {}).items():
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Top Actions"])
    for action in queue.get("actions", [])[:25]:
        lines.append(
            f"- {action['action_type']} | {action.get('client_name')} | "
            f"{action.get('status')} | {action.get('reason')}"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_once(limit: int = 250) -> tuple[dict[str, Any], dict[str, Any]]:
    state = build_operational_state()
    write_json(DEFAULT_OUTPUT, state)
    write_summary_csv(DEFAULT_SUMMARY_CSV, state["clients"])
    queue = build_action_queue(state, limit=limit)
    write_action_queue(queue)
    return state, queue


def pilot_payload(args: argparse.Namespace, message: str) -> dict[str, Any]:
    payload = {
        "event_id": f"fundz-pilot-{int(time.time())}",
        "channel": "credit-tracker",
        "direction": "inbound",
        "first_name": first_name(args.pilot_name),
        "contact_id": args.pilot_contact_id,
        "conversation_id": args.pilot_conversation_id or "fundz-controlled-pilot",
        "message": "Controlled FUNDz pilot check.",
        "status": "active",
        "messageType": args.pilot_channel,
    }
    if args.pilot_channel == "Email":
        payload["email_subject"] = os.getenv("FUNDZ_PILOT_EMAIL_SUBJECT", "FUNDz test message")
    if args.pilot_phone:
        payload["phone"] = args.pilot_phone
    if args.pilot_email:
        payload["email"] = args.pilot_email
    return payload


def configure_pilot_outbound_template(args: argparse.Namespace) -> None:
    if args.pilot_channel == "Email":
        os.environ["CREDIT_TRACKER_OUTBOUND_TEMPLATE"] = PILOT_EMAIL_TEMPLATE
    else:
        os.environ["CREDIT_TRACKER_OUTBOUND_TEMPLATE"] = PILOT_SMS_TEMPLATE


def configure_channel_outbound_template(channel: str) -> None:
    if channel == "Email":
        os.environ["CREDIT_TRACKER_OUTBOUND_TEMPLATE"] = PILOT_EMAIL_TEMPLATE


def clients_by_key(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(client.get("client_key")): client for client in state.get("clients", [])}


def batch_size_limit() -> int:
    return max(env_int("FUNDZ_BATCH_MAX_SIZE", 5), 1)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def send_window_status(now: datetime | None = None) -> tuple[bool, str]:
    if env_bool("FUNDZ_ALLOW_AFTER_HOURS_SENDS", False):
        return True, "after-hours override enabled"
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False, "weekend live sends are blocked by FUNDz safety policy"
    if now.hour < 9 or now.hour >= 21:
        return False, "live sends are allowed only from 9 AM to 9 PM local time"
    return True, "inside approved live-send window"


def capped_batch_size(requested: int) -> int:
    return min(max(requested, 1), batch_size_limit())


def contact_method_for_channel(client: dict[str, Any], channel: str) -> str:
    if channel == "Email":
        return str(client.get("email") or "").strip().lower()
    history = client.get("send_history", {})
    for recipient in history.get("recipients", []):
        value = str(recipient or "").strip()
        if looks_like_e164_phone(value):
            return value
    for sms in history.get("recent_sms", []):
        value = str(sms.get("sent_to") or "").strip()
        if looks_like_e164_phone(value):
            return value
    return ""


def billing_risk_lookup(path: Path | None = None) -> dict[str, str]:
    path = path or BILLING_RISK_REVIEW_CSV
    if not path.exists():
        return {}
    lookup: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            bucket = str(row.get("review_bucket") or "billing-risk review").strip() or "billing-risk review"
            for key in (
                normalize_lookup_value(row.get("client_name")),
                normalize_lookup_value(row.get("client_key")),
                str(row.get("email") or "").strip().lower(),
            ):
                if key:
                    lookup[key] = bucket
    return lookup


def billing_risk_bucket_for_client(
    client: dict[str, Any],
    channel: str,
    lookup: dict[str, str],
) -> str:
    if not lookup:
        return ""
    for key in (
        normalize_lookup_value(client.get("client_name")),
        normalize_lookup_value(client.get("client_key")),
        contact_method_for_channel(client, channel).lower(),
    ):
        if key and key in lookup:
            return lookup[key]
    return ""


def read_json_dict(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def sent_batch_lookup(receipts_dir: Path | None = None) -> dict[str, str]:
    receipts_dir = receipts_dir or BATCH_RECEIPT_DIR
    lookup: dict[str, str] = {}
    if not receipts_dir.exists():
        return lookup
    for path in receipts_dir.glob("*-result.json"):
        result = read_json_dict(path)
        if not result:
            continue
        batch_id = str(result.get("batch_id") or path.stem.removesuffix("-result"))
        rows = result.get("results")
        if not isinstance(rows, list):
            rows = [result] if result.get("client_name") else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            provider_result = row.get("result") if isinstance(row.get("result"), dict) else {}
            if not (row.get("sent") or provider_result.get("sent")):
                continue
            for key in (
                normalize_lookup_value(row.get("client_name")),
                normalize_lookup_value(row.get("client_key")),
            ):
                if key:
                    lookup[key] = batch_id
    return lookup


def sent_batch_for_client(client: dict[str, Any], lookup: dict[str, str]) -> str:
    if not lookup:
        return ""
    for key in (
        normalize_lookup_value(client.get("client_name")),
        normalize_lookup_value(client.get("client_key")),
    ):
        if key and key in lookup:
            return lookup[key]
    return ""


def batch_item_subject(client: dict[str, Any], action: dict[str, Any]) -> str:
    subject = os.getenv("FUNDZ_BATCH_EMAIL_SUBJECT", "").strip()
    if subject:
        return subject
    if action.get("action_type") == "draft_for_approval":
        return "FUNDz update"
    return "FUNDz status update"


def build_batch_id(items: list[dict[str, Any]]) -> str:
    names = "|".join(str(item.get("client_name", "")) for item in items)
    digest = hashlib.sha256(names.encode("utf-8")).hexdigest()[:8]
    return f"fundz-batch-{time.strftime('%Y%m%d-%H%M%S')}-{digest}"


def action_matches_requested(action: dict[str, Any], requested: list[str]) -> bool:
    if not requested:
        return True
    haystack = " ".join(
        str(action.get(key) or "").lower()
        for key in ("client_name", "client_key", "status", "stage_in_process")
    )
    return any(item.lower() in haystack for item in requested)


def action_matches_preset(action: dict[str, Any], preset: str) -> bool:
    action_type = str(action.get("action_type") or "")
    flags = set(action.get("flags", []))
    if preset == "safe_expansion":
        return action_type == "draft_for_approval"
    if preset == "tiny_pilot":
        return action_type == "draft_for_approval"
    if preset == READY_ROLLOUT_PRESET:
        return action_type == "draft_for_approval"
    if preset == "urgent_action_needed":
        return action_type == "owner_review" or bool(flags & {"payment_attention", "missing_next_import", "setup_incomplete", "onboarding_incomplete"})
    if preset == "long_running_stable":
        return action_type == "monitor" and "in_dispute" in flags
    return action_type == "draft_for_approval"


def batch_candidates(
    state: dict[str, Any],
    queue: dict[str, Any],
    channel: str,
    size: int,
    requested_clients: list[str] | None = None,
    preset: str = "safe_expansion",
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    requested_clients = requested_clients or []
    client_lookup = clients_by_key(state)
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for action in queue.get("actions", []):
        if not action_matches_preset(action, preset):
            continue
        if action.get("risky_hits"):
            continue
        if not action_matches_requested(action, requested_clients):
            continue
        client = client_lookup.get(str(action.get("client_key")))
        if not client:
            continue
        if not contact_method_for_channel(client, channel):
            continue
        candidates.append((action, client))
        if len(candidates) >= size:
            break
    return candidates


def resolve_batch_contact(
    client: dict[str, Any],
    channel: str,
    location_id: str,
    enabled: bool,
) -> dict[str, Any]:
    contact_value = contact_method_for_channel(client, channel)
    if not contact_value:
        return {"ok": False, "resolved": False, "contact_id": "", "reason": f"missing {channel.lower()} contact method"}
    if channel == "Email" and not looks_like_email(contact_value):
        return {"ok": False, "resolved": False, "contact_id": "", "reason": "invalid email contact method"}
    if channel == "SMS" and not looks_like_e164_phone(contact_value):
        return {"ok": False, "resolved": False, "contact_id": "", "reason": "invalid SMS contact method"}
    if not enabled:
        return {
            "ok": False,
            "resolved": False,
            "contact_id": "",
            "reason": "contact resolution not requested",
            "lookup_available": True,
        }

    result = resolve_contact(
        email=contact_value if channel == "Email" else "",
        phone=contact_value if channel == "SMS" else "",
        location_id=location_id,
    )
    summary = contact_summary(result.get("contact"))
    contact_id = str(summary.get("id") or "").strip()
    if not result.get("ok") or not contact_id:
        return {
            "ok": False,
            "resolved": False,
            "contact_id": "",
            "reason": result.get("error") or "HighLevel contact was not found.",
        }
    return {"ok": True, "resolved": True, "contact_id": contact_id, "contact": summary}


def batch_payload(
    batch_id: str,
    action: dict[str, Any],
    client: dict[str, Any],
    channel: str,
    contact_id: str,
) -> dict[str, Any]:
    payload = {
        "event_id": f"{batch_id}:{client.get('client_key')}",
        "channel": "credit-tracker",
        "direction": "inbound",
        "first_name": first_name(str(action.get("client_name") or client.get("client_name") or "there")),
        "contact_id": contact_id,
        "conversation_id": batch_id,
        "message": "Controlled FUNDz expansion batch check.",
        "status": "active",
        "messageType": channel,
    }
    if channel == "Email":
        payload["email"] = contact_method_for_channel(client, channel)
        payload["email_subject"] = batch_item_subject(client, action)
    if channel == "SMS":
        payload["phone"] = contact_method_for_channel(client, channel)
    return payload


def build_batch_item(
    batch_id: str,
    action: dict[str, Any],
    client: dict[str, Any],
    channel: str,
    location_id: str,
    resolve_contacts: bool,
) -> dict[str, Any]:
    message = str(action.get("draft") or safe_client_message(client))
    risky_hits = risky_language_hits(message)
    resolution = resolve_batch_contact(client, channel, location_id, resolve_contacts)
    payload = batch_payload(batch_id, action, client, channel, str(resolution.get("contact_id") or ""))
    allowed, reason = should_auto_reply(payload)
    outbound_preview: dict[str, Any] = {}
    send_ready = bool(resolution.get("ok") and allowed and not risky_hits)
    if send_ready:
        outbound_preview = build_outbound_payload(payload, message)
    blocked_reason = ""
    if risky_hits:
        blocked_reason = "risky language detected"
    elif not resolution.get("ok"):
        blocked_reason = str(resolution.get("reason") or "contact was not resolved")
    elif not allowed:
        blocked_reason = reason

    return {
        "client_key": client.get("client_key"),
        "client_name": action.get("client_name") or client.get("client_name"),
        "status": client.get("status"),
        "stage_in_process": client.get("stage_in_process"),
        "next_import": client.get("next_import"),
        "flags": client.get("operational_flags", []),
        "channel": channel,
        "contact_method_present": bool(contact_method_for_channel(client, channel)),
        "resolution": resolution,
        "send_ready": send_ready,
        "blocked_reason": blocked_reason,
        "do_not_send_because": [] if send_ready else [blocked_reason or "not ready for approved live send"],
        "risky_hits": risky_hits,
        "message": message,
        "message_phase": message_phase_for_client(client),
        "payload": payload,
        "outbound_payload_preview": outbound_preview,
    }


def write_batch_report(packet: dict[str, Any], path: Path | None = None) -> None:
    path = path or BATCH_REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    ready_count = sum(1 for item in packet.get("items", []) if item.get("send_ready"))
    lines = [
        "# FUNDz Expansion Batch Preview",
        "",
        f"Batch ID: {packet.get('batch_id')}",
        f"Generated: {packet.get('created_at')}",
        f"Channel: {packet.get('channel')}",
        f"Selected: {len(packet.get('items', []))}",
        f"Ready after safety checks: {ready_count}",
        f"Skipped before approval packet: {len(packet.get('skipped_candidates', []))}",
        "",
        "Policy: preview first; live sends require explicit approval at action time.",
        "",
        "## Messages",
    ]
    for item in packet.get("items", []):
        status = "READY" if item.get("send_ready") else "BLOCKED"
        reason = item.get("blocked_reason") or "ready for approval"
        lines.extend(
            [
                "",
                f"### {status}: {item.get('client_name')}",
                f"- Status: {item.get('status') or 'unknown'}",
                f"- Stage: {item.get('stage_in_process') or 'unknown'}",
                f"- Reason: {reason}",
                f"- Message: {item.get('message')}",
            ]
        )
    skipped = packet.get("skipped_candidates", [])
    if skipped:
        lines.extend(["", "## Skipped Before Approval Packet"])
        for item in skipped:
            lines.append(
                f"- {item.get('client_name')} | {item.get('status') or 'unknown'} | "
                f"{item.get('reason') or 'not ready'}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_batch_preview(args: argparse.Namespace) -> dict[str, Any]:
    load_env_file()
    configure_channel_outbound_template(args.batch_channel)
    requested_size = 1 if args.batch_preset == "tiny_pilot" else args.batch_size
    size = capped_batch_size(requested_size)
    ready_only = args.batch_preset == READY_ROLLOUT_PRESET
    scan_size = (
        max(
            size * env_int("FUNDZ_READY_ROLLOUT_SCAN_MULTIPLIER", 20),
            env_int("FUNDZ_READY_ROLLOUT_MIN_SCAN", 100),
            size,
            len(args.batch_client or []),
        )
        if ready_only
        else size
    )
    state, queue = run_once(limit=max(args.limit, scan_size * 2))
    requested = args.batch_client or []
    selected = batch_candidates(state, queue, args.batch_channel, scan_size, requested_clients=requested, preset=args.batch_preset)
    batch_id = build_batch_id([action for action, _client in selected])
    items: list[dict[str, Any]] = []
    skipped_candidates: list[dict[str, Any]] = []
    sent_batches = sent_batch_lookup() if ready_only else {}
    billing_risk = billing_risk_lookup() if ready_only else {}
    for action, client in selected:
        prior_batch = sent_batch_for_client(client, sent_batches)
        if ready_only and prior_batch:
            skipped_candidates.append(
                {
                    "client_key": client.get("client_key"),
                    "client_name": client.get("client_name"),
                    "status": client.get("status"),
                    "stage_in_process": client.get("stage_in_process"),
                    "reason": f"already sent in prior batch receipt: {prior_batch}",
                }
            )
            continue
        risk_bucket = billing_risk_bucket_for_client(client, args.batch_channel, billing_risk)
        if ready_only and risk_bucket:
            skipped_candidates.append(
                {
                    "client_key": client.get("client_key"),
                    "client_name": client.get("client_name"),
                    "status": client.get("status"),
                    "stage_in_process": client.get("stage_in_process"),
                    "reason": f"billing-risk review queue: {risk_bucket}",
                }
            )
            continue
        item = build_batch_item(
            batch_id,
            action,
            client,
            args.batch_channel,
            args.batch_location_id,
            args.resolve_contact,
        )
        if ready_only and not item.get("send_ready"):
            skipped_candidates.append(
                {
                    "client_key": item.get("client_key"),
                    "client_name": item.get("client_name"),
                    "status": item.get("status"),
                    "stage_in_process": item.get("stage_in_process"),
                    "reason": item.get("blocked_reason") or "not ready for approved live send",
                }
            )
            continue
        items.append(item)
        if ready_only and len(items) >= size:
            break
    packet = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "batch_preview",
        "batch_id": batch_id,
        "channel": args.batch_channel,
        "requested_size": args.batch_size,
        "capped_size": size,
        "batch_preset": args.batch_preset,
        "max_batch_size": batch_size_limit(),
        "approval_required": True,
        "live_send_allowed": False,
        "approval_note": "Live expansion batches transmit client messages to the configured outbound provider.",
        "ready_only": ready_only,
        "skipped_candidates": skipped_candidates,
        "selection": {
            "action_type": "draft_for_approval",
            "requested_clients": requested,
            "resolve_contact": bool(args.resolve_contact),
            "preset": args.batch_preset,
            "candidate_scan_limit": scan_size,
        },
        "items": items,
    }
    BATCH_PACKET.parent.mkdir(parents=True, exist_ok=True)
    BATCH_PACKET.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_batch_report(packet)
    return {
        "prepared": True,
        "batch_id": batch_id,
        "packet": str(BATCH_PACKET),
        "report": str(BATCH_REPORT),
        "selected": len(items),
        "send_ready": sum(1 for item in items if item.get("send_ready")),
        "capped_size": size,
        "skipped_candidates": len(skipped_candidates),
    }


def batch_result_paths(batch_id: str) -> tuple[Path, Path]:
    BATCH_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    return (
        BATCH_RECEIPT_DIR / f"{batch_id}-result.json",
        BATCH_RECEIPT_DIR / f"{batch_id}-receipt.md",
    )


def batch_was_attempted(batch_id: str) -> bool:
    result_path, _receipt_path = batch_result_paths(batch_id)
    return result_path.exists()


def write_batch_receipt(result: dict[str, Any], receipt_path: Path) -> None:
    sent_count = sum(1 for item in result.get("results", []) if item.get("sent"))
    failed_count = sum(1 for item in result.get("results", []) if item.get("blocked") or item.get("failed"))
    skipped_count = sum(1 for item in result.get("results", []) if item.get("skipped"))
    lines = [
        "# FUNDz Expansion Batch Receipt",
        "",
        f"Batch ID: {result.get('batch_id')}",
        f"Created: {result.get('created_at')}",
        f"Approved live send: {result.get('approved_batch_send')}",
        f"Sent: {sent_count}",
        f"Failed/blocked: {failed_count}",
        f"Skipped: {skipped_count}",
        "",
        "## Results",
    ]
    for item in result.get("results", []):
        if item.get("sent"):
            outcome = "sent"
        elif item.get("skipped"):
            outcome = "skipped"
        elif item.get("blocked"):
            outcome = "blocked"
        else:
            outcome = "failed"
        lines.append(f"- {outcome}: {item.get('client_name')} | {item.get('reason') or item.get('status') or ''}")
    receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_batch_live(args: argparse.Namespace) -> dict[str, Any]:
    load_env_file()
    packet_path = Path(args.batch_packet)
    if not packet_path.exists():
        return {"sent": 0, "blocked": True, "reason": f"batch packet not found: {packet_path}"}
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if packet.get("mode") != "batch_preview":
        return {"sent": 0, "blocked": True, "reason": "batch packet is not a preview packet"}
    if not args.approved_batch_send:
        return {"sent": 0, "blocked": True, "reason": "--batch-live requires --approved-batch-send after human approval"}
    if os.getenv("CREDIT_TRACKER_DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}:
        return {"sent": 0, "blocked": True, "reason": "CREDIT_TRACKER_DRY_RUN is still true; refusing live batch send"}
    window_ok, window_reason = send_window_status()
    if not window_ok:
        return {"sent": 0, "blocked": True, "reason": window_reason}

    batch_id = str(packet.get("batch_id") or "")
    if not batch_id:
        return {"sent": 0, "blocked": True, "reason": "batch packet is missing a batch_id"}
    if batch_was_attempted(batch_id):
        return {"sent": 0, "blocked": True, "reason": "this batch was already attempted; prepare a new preview first"}

    items = packet.get("items", [])
    if len(items) > batch_size_limit():
        return {"sent": 0, "blocked": True, "reason": "batch exceeds the configured safety size limit"}

    configure_channel_outbound_template(str(packet.get("channel") or args.batch_channel))
    results: list[dict[str, Any]] = []
    stop_remaining = False
    for item in items:
        client_name = str(item.get("client_name") or "unknown")
        if stop_remaining:
            results.append({"client_name": client_name, "sent": False, "skipped": True, "reason": "skipped after prior failure"})
            continue
        if not item.get("send_ready"):
            results.append(
                {
                    "client_name": client_name,
                    "sent": False,
                    "blocked": True,
                    "reason": item.get("blocked_reason") or "item was not ready for live send",
                }
            )
            continue
        try:
            result = send_reply(item["payload"], item["message"])
            results.append({"client_name": client_name, "sent": bool(result.get("sent")), "status": result.get("status"), "result": result})
        except Exception as error:  # noqa: BLE001 - batch runner must preserve per-contact evidence and fail closed.
            results.append({"client_name": client_name, "sent": False, "failed": True, "reason": str(error)})
            if not args.batch_continue_on_failure:
                stop_remaining = True

    result = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "batch_result",
        "batch_id": batch_id,
        "approved_batch_send": True,
        "packet": str(packet_path),
        "results": results,
        "sent": sum(1 for item in results if item.get("sent")),
        "blocked_or_failed": sum(1 for item in results if item.get("blocked") or item.get("failed")),
        "skipped": sum(1 for item in results if item.get("skipped")),
    }
    result_path, receipt_path = batch_result_paths(batch_id)
    result_path.write_text(json.dumps(redact_sensitive(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_batch_receipt(redact_sensitive(result), receipt_path)
    return {
        "sent": result["sent"],
        "blocked_or_failed": result["blocked_or_failed"],
        "skipped": result["skipped"],
        "result_path": str(result_path),
        "receipt_path": str(receipt_path),
    }


def resolve_pilot_contact_id(args: argparse.Namespace) -> dict[str, Any]:
    if not args.resolve_contact and args.pilot_contact_id.lower() != "auto":
        return {"ok": True, "contact_id": args.pilot_contact_id, "resolved": False}

    result = resolve_contact(email=args.pilot_email, phone=args.pilot_phone, location_id=args.pilot_location_id)
    summary = contact_summary(result.get("contact"))
    contact_id = str(summary.get("id") or "").strip()
    if not result.get("ok") or not contact_id:
        return {
            "ok": False,
            "contact_id": "",
            "resolved": False,
            "reason": result.get("error") or "HighLevel contact was not found.",
        }
    args.pilot_contact_id = contact_id
    return {"ok": True, "contact_id": contact_id, "resolved": True, "contact": summary}


def prepare_pilot(args: argparse.Namespace) -> dict[str, Any]:
    message = args.pilot_message or SAFE_PILOT_MESSAGE.format(first_name=first_name(args.pilot_name))
    payload = pilot_payload(args, message)
    allowed, reason = should_auto_reply(payload)
    risky_hits = risky_language_hits(message)
    outbound_payload: dict[str, Any] = {}
    if allowed and not risky_hits:
        outbound_payload = build_outbound_payload(payload, message)

    packet = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "pilot_prepare",
        "live_send_allowed": False,
        "approval_required": True,
        "approval_note": "Live pilot sends transmit this message/contact to the configured outbound provider.",
        "allowed_by_safety_rules": allowed and not risky_hits,
        "blocked_reason": "" if allowed and not risky_hits else reason or "risky language detected",
        "risky_hits": risky_hits,
        "message": message,
        "payload": payload,
        "outbound_payload_preview": outbound_payload,
    }
    PILOT_PACKET.parent.mkdir(parents=True, exist_ok=True)
    PILOT_PACKET.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet


def run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    load_env_file()
    resolved = resolve_pilot_contact_id(args)
    if not resolved.get("ok"):
        return {"sent": False, "blocked": True, "reason": resolved.get("reason"), "resolved": resolved}

    configure_pilot_outbound_template(args)
    packet = prepare_pilot(args)
    packet["resolved_contact"] = resolved
    PILOT_PACKET.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not packet["allowed_by_safety_rules"]:
        return {"sent": False, "blocked": True, "reason": packet["blocked_reason"], "packet": str(PILOT_PACKET)}

    if args.pilot_live and not args.approved_live_send:
        return {
            "sent": False,
            "blocked": True,
            "reason": "--pilot-live requires --approved-live-send after human approval.",
            "packet": str(PILOT_PACKET),
        }

    if args.pilot_dry_run:
        os.environ["CREDIT_TRACKER_DRY_RUN"] = "true"
    elif os.getenv("CREDIT_TRACKER_DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}:
        return {
            "sent": False,
            "blocked": True,
            "reason": "CREDIT_TRACKER_DRY_RUN is still true; refusing live pilot send.",
            "packet": str(PILOT_PACKET),
        }
    else:
        window_ok, window_reason = send_window_status()
        if not window_ok:
            return {
                "sent": False,
                "blocked": True,
                "reason": window_reason,
                "packet": str(PILOT_PACKET),
            }

    try:
        result = send_reply(packet["payload"], packet["message"])
    except Exception as error:  # noqa: BLE001 - pilot runner must fail closed and leave evidence.
        save_result = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "approved_live_send": bool(args.approved_live_send),
            "sent": False,
            "blocked": True,
            "error": str(error),
            "packet": redact_sensitive(packet),
        }
        result_path = RUN_DIR / f"pilot-result-{int(time.time())}.json"
        result_path.write_text(json.dumps(save_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "sent": False,
            "blocked": True,
            "reason": str(error),
            "result_path": str(result_path),
            "packet": str(PILOT_PACKET),
        }

    save_result = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "approved_live_send": bool(args.approved_live_send),
        "result": result,
        "packet": redact_sensitive(packet),
    }
    result_path = RUN_DIR / f"pilot-result-{int(time.time())}.json"
    result_path.write_text(json.dumps(save_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"sent": bool(result.get("sent")), "dry_run": bool(result.get("dry_run")), "result": result, "result_path": str(result_path)}


def require_pilot_fields(args: argparse.Namespace) -> None:
    missing = []
    if not args.pilot_name:
        missing.append("--pilot-name")
    if not args.pilot_contact_id and not args.resolve_contact:
        missing.append("--pilot-contact-id")
    if args.pilot_channel == "SMS" and not args.pilot_phone:
        missing.append("--pilot-phone")
    if args.pilot_channel == "Email" and not args.pilot_email:
        missing.append("--pilot-email")
    if missing:
        raise SystemExit("Missing required pilot field(s): " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Build state and action queue once.")
    parser.add_argument("--watch", action="store_true", help="Keep rebuilding state and queue on an interval.")
    parser.add_argument("--interval-seconds", type=int, default=int(os.getenv("FUNDZ_SEMI_AUTONOMOUS_INTERVAL_SECONDS", "300")))
    parser.add_argument("--limit", type=int, default=250, help="Maximum action queue rows to write.")
    parser.add_argument("--pilot-dry-run", action="store_true", help="Prepare and dry-run one controlled pilot message.")
    parser.add_argument("--pilot-live", action="store_true", help="Send one controlled pilot message only with approval.")
    parser.add_argument("--approved-live-send", action="store_true", help="Required with --pilot-live after human approval.")
    parser.add_argument("--pilot-name", default="")
    parser.add_argument("--pilot-contact-id", default="")
    parser.add_argument("--pilot-conversation-id", default="")
    parser.add_argument("--pilot-channel", choices=("SMS", "Email"), default="SMS")
    parser.add_argument("--pilot-phone", default="")
    parser.add_argument("--pilot-email", default="")
    parser.add_argument("--pilot-message", default="")
    parser.add_argument("--resolve-contact", action="store_true", help="Resolve HighLevel contact ID from email/phone before pilot.")
    parser.add_argument("--pilot-location-id", default="", help="Optional HighLevel location ID for contact resolution.")
    parser.add_argument("--batch-preview", action="store_true", help="Prepare a 3-to-5 contact expansion preview. No live sends.")
    parser.add_argument("--batch-live", action="store_true", help="Send a prepared expansion batch only after approval.")
    parser.add_argument("--approved-batch-send", action="store_true", help="Required with --batch-live after human approval.")
    parser.add_argument("--batch-size", type=int, default=env_int("FUNDZ_BATCH_SIZE", 3), help="Requested expansion size; capped by FUNDZ_BATCH_MAX_SIZE.")
    parser.add_argument(
        "--batch-preset",
        choices=("safe_expansion", "tiny_pilot", "urgent_action_needed", "long_running_stable", READY_ROLLOUT_PRESET),
        default=os.getenv("FUNDZ_BATCH_PRESET", "safe_expansion"),
        help="Select the preview queue strategy. Live sends remain approval-gated.",
    )
    parser.add_argument("--batch-channel", choices=("SMS", "Email"), default=os.getenv("FUNDZ_BATCH_CHANNEL", "Email"))
    parser.add_argument("--batch-location-id", default="", help="Optional HighLevel location ID for batch contact resolution.")
    parser.add_argument("--batch-packet", default=str(BATCH_PACKET), help="Prepared batch packet to send.")
    parser.add_argument("--batch-client", action="append", default=[], help="Optional client name/key filter. Can be repeated.")
    parser.add_argument("--batch-continue-on-failure", action="store_true", help="Continue sending the batch after a provider failure.")
    return parser.parse_args()


def print_once_summary(state: dict[str, Any], queue: dict[str, Any]) -> None:
    summary = state.get("summary", {})
    print("FUNDz semi-autonomous mode is ready.")
    print(f"- Active clients: {summary.get('active_clients', 0)}")
    print(f"- Due next round: {summary.get('due_for_next_round', 0)}")
    print(f"- In dispute: {summary.get('in_dispute', 0)}")
    print(f"- Action queue: {relative_label(ACTION_QUEUE)}")
    print(f"- Action report: {relative_label(ACTION_REPORT)}")
    for key, count in queue.get("summary", {}).items():
        print(f"- {key}: {count}")


def main() -> None:
    args = parse_args()
    if args.pilot_dry_run or args.pilot_live:
        require_pilot_fields(args)
        result = run_pilot(args)
        print(json.dumps(redact_sensitive(result), indent=2, sort_keys=True))
        return
    if args.batch_preview:
        result = build_batch_preview(args)
        print(json.dumps(redact_sensitive(result), indent=2, sort_keys=True))
        return
    if args.batch_live:
        result = run_batch_live(args)
        print(json.dumps(redact_sensitive(result), indent=2, sort_keys=True))
        return

    if args.watch:
        interval = max(args.interval_seconds, 30)
        print(f"FUNDz semi-autonomous bot rebuilding every {interval} seconds.")
        while True:
            state, queue = run_once(limit=args.limit)
            print_once_summary(state, queue)
            time.sleep(interval)

    state, queue = run_once(limit=args.limit)
    print_once_summary(state, queue)


if __name__ == "__main__":
    main()
