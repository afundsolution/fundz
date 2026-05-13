#!/usr/bin/env python3
"""Poll HighLevel conversations so FUNDz can work without a public webhook."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import classify_send_failure, quarantine_event, redact_sensitive, risky_language_hits, write_proposal
from fundz_credit_tracker_bridge import (
    contact_value,
    draft_bridge_reply,
    load_env_file,
    log_event,
    message_text,
    outbound_headers,
    send_reply,
    value_for,
)
from fundz_resolve_highlevel_contact import env_location_id, request_get


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "data" / "local" / "highlevel-inbox-poller"
SEEN_MESSAGES = STATE_DIR / "seen-messages.txt"
POLL_LOG = ROOT / "logs" / "highlevel-inbox-poller.jsonl"
REPLY_QUEUE = STATE_DIR / "classified-replies.jsonl"
CUSTOMER_MEMORY = STATE_DIR / "customer-memory.jsonl"
CUSTOMER_SUMMARIES = STATE_DIR / "customer-summaries.json"
REPLY_RECEIPTS = STATE_DIR / "reply-receipts.jsonl"
APP_PORTAL_PROOF_JSONL = STATE_DIR / "app-portal-event-proof.jsonl"
APP_PORTAL_PROOF_MD = STATE_DIR / "app-portal-event-proof.md"
MANUAL_IMPORT_DIR = ROOT / "data" / "local" / "highlevel-inbox-manual-imports"
MANUAL_QUEUE_CSV = STATE_DIR / "manual-inbox-workaround.csv"
MANUAL_QUEUE_MD = STATE_DIR / "manual-inbox-workaround.md"

DEFAULT_CONVERSATIONS_URL = "https://services.leadconnectorhq.com/conversations/search"

MANUAL_QUEUE_FIELDS = [
    "queue_id",
    "source",
    "contact",
    "phone",
    "email",
    "date",
    "direction",
    "message_preview",
    "classification",
    "needs_brandon_reply",
    "status",
    "owner",
    "next_step",
    "proof_required",
    "evidence",
]

REPLY_CLASS_PATTERNS = {
    "cancel": ("cancel", "cancellation", "stop service", "close my account"),
    "complaint": ("upset", "angry", "mad", "complaint", "not happy", "frustrated"),
    "billing": ("billing", "payment", "charged", "invoice", "refund", "card", "subscription"),
    "document_request": ("document", "upload", "agreement", "identification"),
    "app_access": ("app", "credit tracker", "portal", "login", "password"),
    "score_concern": ("score", "dropped", "went down", "decrease", "changed"),
    "dispute_update": ("dispute", "round", "bureau", "deleted", "removed", "next import", "import"),
    "question": ("?", "what", "when", "where", "why", "how", "update", "status"),
}

FOLLOW_UP_LABELS = {"billing", "cancel", "complaint", "document_request", "app_access", "score_concern", "dispute_update"}
SENSITIVE_OWNER_LABELS = {"billing", "cancel", "complaint", "document_request"}
LIVE_HOLD_LABELS = {"billing", "cancel", "complaint", "document_request", "app_access", "score_concern", "dispute_update"}
APP_PORTAL_SIGNAL_TERMS = {
    "app",
    "app message",
    "app_message",
    "credit tracker",
    "disputefox",
    "mobile app sms",
    "portal",
}


def text_matches_pattern(text: str, pattern: str) -> bool:
    if not pattern:
        return False
    if pattern == "?":
        return "?" in text
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(pattern.lower())}(?![A-Za-z0-9])", text.lower()))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def write_poll_log(kind: str, payload: dict[str, Any]) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "kind": kind,
        **redact_sensitive(payload),
    }
    line = json.dumps(entry, ensure_ascii=True, sort_keys=True)
    try:
        POLL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with POLL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        try:
            print(
                json.dumps(
                    {
                        "time": entry["time"],
                        "kind": "poll_log_write_failed",
                        "target": str(POLL_LOG),
                        "error": str(exc),
                        "event_kind": kind,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )
        except OSError:
            pass


def classify_inbound_reply(text: str) -> dict[str, Any]:
    lower = (text or "").lower()
    labels = [
        label
        for label, patterns in REPLY_CLASS_PATTERNS.items()
        if any(text_matches_pattern(lower, pattern) for pattern in patterns)
    ]
    if not labels:
        labels = ["no_action"]
    needs_owner = any(label in labels for label in SENSITIVE_OWNER_LABELS)
    needs_follow_up = any(label in labels for label in FOLLOW_UP_LABELS) or "question" in labels
    tone = customer_tone(text)
    safe_draft = ""
    if not needs_owner and (labels == ["question"] or "question" in labels):
        safe_draft = (
            "Thanks for checking in. I am reviewing the latest tracker details so we give you the right answer, "
            "not a guess. I will follow up with the next clear update."
        )
    elif not needs_owner and labels == ["no_action"]:
        safe_draft = "Received. Thank you."
    return {
        "labels": labels,
        "needs_brandon_reply": needs_owner,
        "needs_follow_up": needs_follow_up,
        "customer_tone": tone,
        "recommended_response_mode": recommended_response_mode(labels, needs_owner, tone),
        "safe_auto_reply_draft": safe_draft,
    }


def customer_tone(text: str) -> str:
    lower = (text or "").lower()
    if any(word in lower for word in ("angry", "mad", "upset", "frustrated", "cancel", "refund")):
        return "frustrated"
    if any(word in lower for word in ("worried", "nervous", "scared", "panic", "dropped", "went down")):
        return "anxious"
    if any(word in lower for word in ("thanks", "thank you", "appreciate")):
        return "positive"
    return "neutral"


def recommended_response_mode(labels: list[str], needs_owner: bool, tone: str) -> str:
    if needs_owner:
        return "owner_review_required"
    if tone in {"frustrated", "anxious"}:
        return "reassure_with_verified_facts"
    if "app_access" in labels:
        return "help_with_app_access"
    if "dispute_update" in labels or "score_concern" in labels:
        return "answer_from_tracker_context"
    if "question" in labels:
        return "answer_or_queue_verified_update"
    return "acknowledge"


def contact_memory_key(payload: dict[str, Any]) -> str:
    contact_id = contact_value(payload, "contact_id")
    if contact_id:
        return f"contact:{contact_id}"
    fallback = "|".join(
        str(contact_value(payload, key) or payload.get(key) or "")
        for key in ("phone", "email", "name")
    )
    digest = hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:16]
    return f"hashed-contact:{digest}"


def first_name_from_payload(payload: dict[str, Any]) -> str:
    raw = str(payload.get("first_name") or payload.get("name") or "").strip()
    return raw.split()[0] if raw else ""


def load_customer_summaries() -> dict[str, Any]:
    if not CUSTOMER_SUMMARIES.exists():
        return {}
    try:
        payload = json.loads(CUSTOMER_SUMMARIES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_customer_memory(payload: dict[str, Any], classification: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    key = contact_memory_key(payload)
    labels = classification.get("labels", [])
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    event = {
        "time": now,
        "contact_key": key,
        "contact_id": contact_value(payload, "contact_id"),
        "conversation_id": contact_value(payload, "conversation_id"),
        "first_name": first_name_from_payload(payload),
        "labels": labels,
        "customer_tone": classification.get("customer_tone", "neutral"),
        "needs_follow_up": bool(classification.get("needs_follow_up")),
        "needs_brandon_reply": bool(classification.get("needs_brandon_reply")),
        "recommended_response_mode": classification.get("recommended_response_mode", ""),
        "message_preview": message_text(payload)[:240],
    }
    with CUSTOMER_MEMORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_sensitive(event), ensure_ascii=True, sort_keys=True) + "\n")

    summaries = load_customer_summaries()
    previous = summaries.get(key, {}) if isinstance(summaries.get(key), dict) else {}
    prior_topics = previous.get("recent_topics", []) if isinstance(previous.get("recent_topics"), list) else []
    recent_topics = list(dict.fromkeys([*prior_topics, *labels]))[-8:]
    count = int(previous.get("message_count", 0) or 0) + 1
    summaries[key] = {
        "contact_key": key,
        "contact_id": contact_value(payload, "contact_id"),
        "first_name": first_name_from_payload(payload),
        "last_seen": now,
        "message_count": count,
        "recent_topics": recent_topics,
        "last_tone": classification.get("customer_tone", "neutral"),
        "last_response_mode": classification.get("recommended_response_mode", ""),
        "open_follow_up": bool(classification.get("needs_follow_up") or previous.get("open_follow_up")),
        "last_summary": build_memory_summary(labels, classification),
    }
    CUSTOMER_SUMMARIES.write_text(json.dumps(summaries, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_memory_summary(labels: list[str], classification: dict[str, Any]) -> str:
    if "billing" in labels:
        return "Customer asked about billing or payment; owner-safe billing review is required before a stronger reply."
    if "score_concern" in labels:
        return "Customer is worried about score movement; answer only from verified tracker/report context."
    if "app_access" in labels:
        return "Customer may need Credit Tracker app or portal help."
    if "dispute_update" in labels:
        return "Customer wants a dispute or round-status update from verified local records."
    if classification.get("customer_tone") == "frustrated":
        return "Customer tone is frustrated; respond calmly with facts, ownership, and a clear next step."
    return "Customer contacted FUNDz; keep context available for the next reply."


def app_portal_signals(payload: dict[str, Any]) -> list[str]:
    values = [
        payload.get("messageType"),
        payload.get("channel"),
        payload.get("source"),
        payload.get("type"),
        payload.get("lastMessageType"),
        payload.get("source_file"),
    ]
    haystack = " ".join(str(value or "") for value in values).lower()
    return sorted(term for term in APP_PORTAL_SIGNAL_TERMS if text_matches_pattern(haystack, term))


def is_app_portal_payload(payload: dict[str, Any], classification: dict[str, Any] | None = None) -> bool:
    labels = set((classification or {}).get("labels", []))
    return bool(app_portal_signals(payload) or "app_access" in labels)


def proof_row_has_message(path: Path, message_id: str) -> bool:
    if not message_id or not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("message_id") or "") == message_id:
            return True
    return False


def rebuild_app_portal_proof_markdown(path: Path | None = None, output: Path | None = None) -> None:
    path = path or APP_PORTAL_PROOF_JSONL
    output = output or APP_PORTAL_PROOF_MD
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    lines = [
        "# FUNDz App / Portal Event Proof",
        "",
        "Local evidence that HighLevel/manual intake observed Credit Tracker app, DisputeFox portal, or Mobile App SMS-style message events.",
        "",
        "No replies, sends, DF edits, AutoFox edits, campaign assignments, or billing edits are performed by this proof file.",
        "",
        f"- Captured events: {len(rows)}",
        f"- Needs Brandon review: {sum(1 for row in rows if row.get('needs_brandon_reply'))}",
        f"- Open follow-up: {sum(1 for row in rows if row.get('needs_follow_up'))}",
        "",
        "## Recent Events",
    ]
    for row in rows[-25:]:
        labels = ",".join(row.get("classification", []) or ["unclassified"])
        signals = ",".join(row.get("signals", []) or ["app/portal"])
        lines.append(
            f"- {row.get('last_message_date') or row.get('time')} | "
            f"{row.get('contact') or 'Unknown'} | {row.get('message_type') or 'unknown'} | "
            f"{labels} | {signals} | {row.get('proof_status')}"
        )
    if not rows:
        lines.append("- No app/portal events captured yet.")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_app_portal_proof(payload: dict[str, Any], classification: dict[str, Any], proof_status: str) -> None:
    if not is_app_portal_payload(payload, classification):
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    message_id = value_for(payload, ("message_id", "messageId", "event_id", "eventId"))
    if proof_row_has_message(APP_PORTAL_PROOF_JSONL, message_id):
        return
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "message_id": message_id,
        "contact_id": contact_value(payload, "contact_id"),
        "conversation_id": contact_value(payload, "conversation_id"),
        "contact": payload.get("name") or payload.get("first_name") or "",
        "direction": payload.get("direction") or "",
        "message_type": payload.get("messageType") or payload.get("lastMessageType") or payload.get("channel") or "",
        "source": payload.get("source") or "",
        "source_file": payload.get("source_file") or "",
        "last_message_date": payload.get("lastMessageDate") or "",
        "signals": app_portal_signals(payload),
        "classification": classification.get("labels", []),
        "needs_follow_up": bool(classification.get("needs_follow_up")),
        "needs_brandon_reply": bool(classification.get("needs_brandon_reply")),
        "proof_status": proof_status,
        "message_preview": message_text(payload)[:300],
    }
    with APP_PORTAL_PROOF_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_sensitive(row), ensure_ascii=True, sort_keys=True) + "\n")
    rebuild_app_portal_proof_markdown()


def reply_queue_has_message(message_id: str) -> bool:
    if not message_id or not REPLY_QUEUE.exists():
        return False
    try:
        lines = REPLY_QUEUE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("message_id") or "") == message_id:
            return True
    return False


def write_reply_queue(payload: dict[str, Any], classification: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    message_id = value_for(payload, ("message_id", "messageId", "event_id", "eventId"))
    if reply_queue_has_message(message_id):
        return
    write_customer_memory(payload, classification)
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "message_id": message_id,
        "contact_id": contact_value(payload, "contact_id"),
        "conversation_id": contact_value(payload, "conversation_id"),
        "name": payload.get("name") or payload.get("first_name") or "",
        "classification": classification,
        "customer_memory_key": contact_memory_key(payload),
        "message_preview": message_text(payload)[:500],
    }
    with REPLY_QUEUE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_sensitive(entry), ensure_ascii=True, sort_keys=True) + "\n")


def live_reply_hold_reason(classification: dict[str, Any]) -> str:
    labels = set(classification.get("labels", []))
    held = sorted(labels & LIVE_HOLD_LABELS)
    if classification.get("needs_brandon_reply"):
        return "owner review required for " + ", ".join(held or ["sensitive reply"])
    if held:
        return "verified customer-service context required for " + ", ".join(held)
    return ""


def write_reply_receipt(payload: dict[str, Any], reply: str, send_result: dict[str, Any], classification: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "message_id": value_for(payload, ("message_id", "messageId", "event_id", "eventId")),
        "contact_id": contact_value(payload, "contact_id"),
        "conversation_id": contact_value(payload, "conversation_id"),
        "client": payload.get("name") or payload.get("first_name") or "",
        "channel": payload.get("messageType") or payload.get("channel") or "",
        "sent": bool(send_result.get("sent")),
        "status": send_result.get("status") or send_result.get("status_code") or "",
        "classification": classification.get("labels", []),
        "reply_preview": reply[:240],
        "send_result": send_result,
    }
    with REPLY_RECEIPTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_sensitive(row), ensure_ascii=True, sort_keys=True) + "\n")


def seen_key(message_id: str) -> str:
    return f"highlevel:{message_id}"


def has_seen(message_id: str) -> bool:
    if not SEEN_MESSAGES.exists():
        return False
    return seen_key(message_id) in set(SEEN_MESSAGES.read_text(encoding="utf-8").splitlines())


def mark_seen(message_id: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with SEEN_MESSAGES.open("a", encoding="utf-8") as handle:
        handle.write(seen_key(message_id) + "\n")


def build_conversation_search_url(location_id: str, limit: int, status: str, extra_params: dict[str, str] | None = None) -> str:
    base_url = os.getenv("HIGHLEVEL_CONVERSATIONS_URL", DEFAULT_CONVERSATIONS_URL).strip() or DEFAULT_CONVERSATIONS_URL
    params = {
        "locationId": location_id,
        "limit": str(limit),
        "sort": os.getenv("HIGHLEVEL_INBOX_SORT", "desc"),
    }
    if status:
        params["status"] = status
    direction = os.getenv("HIGHLEVEL_INBOX_LAST_DIRECTION", "inbound").strip()
    if direction:
        params["lastMessageDirection"] = direction
    configured_extra = os.getenv("HIGHLEVEL_INBOX_EXTRA_PARAMS", "").strip()
    if configured_extra:
        params.update(dict(urllib.parse.parse_qsl(configured_extra, keep_blank_values=True)))
    if extra_params:
        params.update(extra_params)
    return base_url + "?" + urllib.parse.urlencode(params)


def extract_conversations(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("conversations", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_conversations(value)
            if nested:
                return nested
    return []


def conversation_message_id(conversation: dict[str, Any]) -> str:
    for key in ("lastMessageId", "last_message_id", "messageId", "message_id"):
        value = conversation.get(key)
        if value:
            return str(value)
    stable = "|".join(
        str(conversation.get(key) or "")
        for key in ("id", "conversationId", "contactId", "lastMessageDate", "lastMessageBody")
    )
    return stable


def normalize_message_type(raw: str) -> str:
    value = (raw or "").upper()
    if "EMAIL" in value:
        return "Email"
    if "WHATSAPP" in value:
        return "WhatsApp"
    if "APP" in value or "PORTAL" in value:
        return "App_Message"
    return "SMS"


def normalized_row_channel(row: dict[str, Any]) -> str:
    return row_value(row, "channel", "messageChannel", "message_channel")


def normalized_row_source(row: dict[str, Any], default: str = "") -> str:
    return row_value(row, "source", "messageSource", "message_source", "provider") or default


def contact_name(conversation: dict[str, Any]) -> str:
    contact = conversation.get("contact")
    if isinstance(contact, dict):
        name = contact.get("name") or " ".join(
            item
            for item in [str(contact.get("firstName", "")).strip(), str(contact.get("lastName", "")).strip()]
            if item
        )
        if name:
            return name
    return str(
        conversation.get("contactName")
        or conversation.get("fullName")
        or conversation.get("name")
        or conversation.get("firstName")
        or ""
    ).strip()


def nested_contact_value(conversation: dict[str, Any], key: str) -> str:
    contact = conversation.get("contact")
    if isinstance(contact, dict):
        value = contact.get(key)
        if value:
            return str(value)
    return str(conversation.get(key) or "").strip()


def normalize_conversation(conversation: dict[str, Any], location_id: str) -> dict[str, Any]:
    message_id = conversation_message_id(conversation)
    message_type = normalize_message_type(str(conversation.get("lastMessageType") or conversation.get("messageType") or ""))
    name = contact_name(conversation)
    channel = str(conversation.get("channel") or conversation.get("messageChannel") or "").strip()
    source = str(conversation.get("source") or conversation.get("messageSource") or "highlevel-poller").strip()
    payload = {
        "event_id": message_id,
        "message_id": message_id,
        "source": source,
        "channel": channel,
        "direction": "inbound",
        "type": "InboundMessage",
        "messageType": message_type,
        "locationId": str(conversation.get("locationId") or location_id),
        "conversation_id": str(conversation.get("id") or conversation.get("conversationId") or ""),
        "conversationId": str(conversation.get("id") or conversation.get("conversationId") or ""),
        "contact_id": str(conversation.get("contactId") or conversation.get("contact_id") or ""),
        "contactId": str(conversation.get("contactId") or conversation.get("contact_id") or ""),
        "message": str(conversation.get("lastMessageBody") or conversation.get("last_message_body") or ""),
        "lastMessageDate": str(conversation.get("lastMessageDate") or conversation.get("last_message_date") or ""),
        "first_name": name.split()[0] if name else "",
        "name": name,
        "phone": nested_contact_value(conversation, "phone"),
        "email": nested_contact_value(conversation, "email"),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def row_value(row: dict[str, Any], *keys: str) -> str:
    lookup = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value not in ("", None):
            return str(value).strip()
        normalized = key.strip().lower().replace(" ", "_")
        value = lookup.get(normalized)
        if value not in ("", None):
            return str(value).strip()
    return ""


def stable_manual_message_id(row: dict[str, Any], source: Path, index: int) -> str:
    explicit = row_value(row, "lastMessageId", "last_message_id", "messageId", "message_id", "event_id", "id")
    if explicit:
        return explicit
    fingerprint = json.dumps(row, sort_keys=True, default=str) + f"|{source.name}|{index}"
    return "manual-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]


def normalize_manual_row(row: dict[str, Any], source: Path, index: int, location_id: str) -> dict[str, Any]:
    message_id = stable_manual_message_id(row, source, index)
    name = row_value(row, "contact", "contactName", "contact_name", "name", "fullName", "full_name", "client")
    message = row_value(row, "lastMessageBody", "last_message_body", "last message", "last_message", "message", "body", "text")
    direction = row_value(row, "lastMessageDirection", "last_message_direction", "direction") or "inbound"
    payload = {
        "event_id": message_id,
        "message_id": message_id,
        "source": normalized_row_source(row, "highlevel-manual-import"),
        "source_file": str(source),
        "channel": normalized_row_channel(row),
        "direction": direction,
        "type": "InboundMessage",
        "messageType": normalize_message_type(row_value(row, "lastMessageType", "last_message_type", "messageType", "message_type", "channel", "type")),
        "locationId": row_value(row, "locationId", "location_id") or location_id,
        "conversation_id": row_value(row, "conversationId", "conversation_id", "conversation"),
        "conversationId": row_value(row, "conversationId", "conversation_id", "conversation"),
        "contact_id": row_value(row, "contactId", "contact_id", "contact id"),
        "contactId": row_value(row, "contactId", "contact_id", "contact id"),
        "message": message,
        "lastMessageDate": row_value(row, "lastMessageDate", "last_message_date", "date", "createdAt", "created_at", "time"),
        "first_name": name.split()[0] if name else "",
        "name": name,
        "phone": row_value(row, "phone", "phoneNumber", "phone_number", "mobile"),
        "email": row_value(row, "email", "emailAddress", "email_address"),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def read_manual_import_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = extract_conversations(payload)
        if rows:
            return rows
        return [payload] if isinstance(payload, dict) else []
    if suffix in {".txt", ".md"}:
        rows = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            text = line.strip()
            if text:
                rows.append({"message": text, "contact": path.stem, "line": line_number})
        return rows
    return []


def manual_status(payload: dict[str, Any], classification: dict[str, Any]) -> tuple[str, str, str]:
    direction = value_for(payload, ("direction", "lastMessageDirection", "messageDirection")).lower()
    if direction and "inbound" not in direction:
        return "Review", "No reply needed unless Brandon wants follow-up.", "FUNDz"
    if classification.get("needs_brandon_reply"):
        return "Needs Brandon", "Review sensitive reply before any client response.", "Brandon"
    if not contact_value(payload, "contact_id"):
        return "Needs Brandon", "Resolve the HighLevel contact before replying.", "Brandon"
    if "question" in classification.get("labels", []):
        return "Needs Reply", "Draft a reply in HighLevel after owner-safe review.", "FUNDz"
    return "Review", "Check whether this needs a reply or can be marked no-action.", "FUNDz"


def manual_queue_row(payload: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    status, next_step, owner = manual_status(payload, classification)
    labels = classification.get("labels", [])
    return {
        "queue_id": f"HLM-{value_for(payload, ('message_id', 'event_id'))}",
        "source": payload.get("source_file", "highlevel-manual-import"),
        "contact": payload.get("name", ""),
        "phone": contact_value(payload, "phone"),
        "email": contact_value(payload, "email"),
        "date": payload.get("lastMessageDate", ""),
        "direction": payload.get("direction", ""),
        "message_preview": message_text(payload)[:300],
        "classification": ";".join(labels),
        "needs_brandon_reply": "yes" if classification.get("needs_brandon_reply") else "no",
        "status": status,
        "owner": owner,
        "next_step": next_step,
        "proof_required": "HighLevel, DF, or Credit Tracker export row/screenshot showing the inbound message.",
        "evidence": payload.get("source_file", "manual import"),
    }


def write_manual_queue_outputs(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with MANUAL_QUEUE_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_QUEUE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANUAL_QUEUE_FIELDS})

    lines = [
        "# FUNDz HighLevel Inbox Workaround",
        "",
        "This file is built from local HighLevel, DF, or Credit Tracker inbox exports/copies when the API path is blocked or incomplete.",
        "",
        f"- Imported: {summary['imported']}",
        f"- Needs Brandon: {summary['needs_brandon']}",
        f"- Needs Reply: {summary['needs_reply']}",
        f"- Review: {summary['review']}",
        "",
        "No replies were sent.",
        "",
        "## Queue",
    ]
    for row in rows[:25]:
        lines.append(
            f"- {row['queue_id']} | {row['contact'] or 'Unknown'} | {row['status']} | "
            f"{row['classification'] or 'unclassified'} | {row['next_step']}"
        )
    if not rows:
        lines.append("- No manual HighLevel inbox rows found.")
    MANUAL_QUEUE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def poll_manual_imports(path: Path = MANUAL_IMPORT_DIR) -> dict[str, Any]:
    load_env_file()
    location_id = env_location_id() or ""
    paths = [path] if path.is_file() else sorted(item for item in path.glob("*") if item.is_file() and not item.name.startswith(("_", ".")))
    queue_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in paths:
        for index, row in enumerate(read_manual_import_file(source), start=1):
            payload = normalize_manual_row(row, source, index, location_id)
            message_id = value_for(payload, ("message_id", "event_id"))
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            classification = classify_inbound_reply(message_text(payload))
            row = manual_queue_row(payload, classification)
            write_app_portal_proof(payload, classification, "captured_from_manual_import_no_send")
            if row["status"] != "Review" and message_text(payload):
                write_reply_queue(payload, classification)
            queue_rows.append(row)

    summary = {
        "ok": True,
        "mode": "manual_import",
        "source": str(path),
        "imported": len(queue_rows),
        "needs_brandon": sum(1 for row in queue_rows if row["status"] == "Needs Brandon"),
        "needs_reply": sum(1 for row in queue_rows if row["status"] == "Needs Reply"),
        "review": sum(1 for row in queue_rows if row["status"] == "Review"),
        "sent": 0,
        "csv": str(MANUAL_QUEUE_CSV),
        "markdown": str(MANUAL_QUEUE_MD),
    }
    write_manual_queue_outputs(queue_rows, summary)
    write_poll_log("manual_import_complete", summary)
    return summary


def should_handle(payload: dict[str, Any]) -> tuple[bool, str]:
    direction = value_for(payload, ("direction", "lastMessageDirection", "messageDirection")).lower()
    if direction and "inbound" not in direction:
        return False, "last message is not inbound"
    if not contact_value(payload, "contact_id"):
        return False, "missing contact id"
    if not message_text(payload):
        return False, "missing message body"
    if has_seen(value_for(payload, ("message_id", "messageId", "event_id", "eventId"))):
        return False, "duplicate"
    return True, "ready"


def fetch_conversations(location_id: str, limit: int, status: str) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    url = build_conversation_search_url(location_id, limit, status)
    headers = outbound_headers()
    headers.setdefault("Accept", "application/json")
    status_code, body = request_get(url, headers, timeout=float(os.getenv("CREDIT_TRACKER_TIMEOUT", "12")))
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"raw": body}
    return status_code, payload if isinstance(payload, dict) else {"data": payload}, extract_conversations(payload)


def handle_payload(payload: dict[str, Any], live: bool) -> dict[str, Any]:
    message_id = value_for(payload, ("message_id", "messageId", "event_id", "eventId"))
    classification = classify_inbound_reply(message_text(payload))
    write_app_portal_proof(payload, classification, "captured_from_highlevel_poll_no_send" if not live else "captured_before_live_gate")
    allowed, reason = should_handle(payload)
    if not allowed:
        write_poll_log("message_ignored", {"reason": reason, "classification": classification, "payload": payload})
        if reason != "duplicate" and message_id:
            mark_seen(message_id)
        return {"handled": False, "reason": reason, "classification": classification}

    write_reply_queue(payload, classification)
    reply = draft_bridge_reply(payload)
    risky_hits = risky_language_hits(reply)
    if risky_hits:
        quarantine_event("poller reply contained risky language", payload, {"reply": reply, "risky_terms": risky_hits})
        write_proposal(
            "HighLevel poller generated risky reply language",
            classify_send_failure(error="risky generated reply"),
            [{"message_id": message_id, "reply": reply, "risky_terms": risky_hits}],
        )
        mark_seen(message_id)
        return {"handled": False, "reason": "risky reply blocked"}

    if not live:
        write_poll_log("reply_preview", {"message_id": message_id, "reply": reply, "classification": classification, "payload": payload})
        return {"handled": True, "sent": False, "preview": True, "reply": reply, "classification": classification}

    hold_reason = live_reply_hold_reason(classification)
    if hold_reason:
        write_poll_log("reply_hold", {"message_id": message_id, "reason": hold_reason, "classification": classification, "payload": payload})
        mark_seen(message_id)
        return {"handled": True, "sent": False, "held": True, "reason": hold_reason, "classification": classification}

    try:
        send_result = send_reply(payload, reply)
    except Exception as error:  # noqa: BLE001 - poller must preserve failures for owner review.
        write_poll_log("reply_failed", {"message_id": message_id, "error": str(error), "payload": payload})
        quarantine_event("poller reply send failed", payload, {"message_id": message_id, "error": str(error)})
        return {"handled": False, "reason": "reply send failed", "error": str(error)}

    mark_seen(message_id)
    write_poll_log("reply_sent", {"message_id": message_id, "send_result": send_result, "classification": classification})
    write_reply_receipt(payload, reply, send_result, classification)
    log_event("highlevel_poller_replied", {"event_id": message_id, "send_result": send_result})
    return {"handled": True, "sent": bool(send_result.get("sent")), "send_result": send_result, "reply": reply, "classification": classification}


def poll_once(limit: int, status: str, live: bool) -> dict[str, Any]:
    load_env_file()
    location_id = env_location_id()
    if not location_id:
        raise SystemExit("Missing CREDIT_TRACKER_LOCATION_ID.")
    if live and env_bool("CREDIT_TRACKER_DRY_RUN", True):
        raise SystemExit("CREDIT_TRACKER_DRY_RUN is true; refusing live HighLevel poller replies.")

    status_code, payload, conversations = fetch_conversations(location_id, limit, status)
    if not 200 <= status_code < 300:
        write_poll_log("poll_failed", {"status": status_code, "body": payload})
        raise SystemExit(f"HighLevel conversation poll failed with status {status_code}.")

    results = []
    for conversation in conversations:
        normalized = normalize_conversation(conversation, location_id)
        results.append(handle_payload(normalized, live=live))

    summary: dict[str, Any] = {
        "ok": True,
        "status": status_code,
        "fetched": len(conversations),
        "handled": sum(1 for result in results if result.get("handled")),
        "sent": sum(1 for result in results if result.get("sent")),
        "preview": sum(1 for result in results if result.get("preview")),
        "ignored": sum(1 for result in results if not result.get("handled")),
        "live": live,
    }
    write_poll_log("poll_complete", summary)
    return summary


def run_daemon(limit: int, status: str, interval: int, live: bool) -> None:
    write_poll_log("daemon_started", {"limit": limit, "status": status, "interval": interval, "live": live})
    while True:
        try:
            summary = poll_once(limit=limit, status=status, live=live)
            print(json.dumps(summary, sort_keys=True))
        except Exception as error:  # noqa: BLE001 - daemon should keep trying after transient API failures.
            write_poll_log("daemon_error", {"error": str(error)})
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        time.sleep(max(interval, 5))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Poll once, then exit.")
    parser.add_argument("--daemon", action="store_true", help="Poll forever.")
    parser.add_argument(
        "--manual-import",
        nargs="?",
        const=str(MANUAL_IMPORT_DIR),
        help="Classify a local HighLevel inbox export folder/file instead of using the API.",
    )
    parser.add_argument("--limit", type=int, default=env_int("HIGHLEVEL_INBOX_LIMIT", 20))
    parser.add_argument("--status", default=os.getenv("HIGHLEVEL_INBOX_STATUS", "unread"))
    parser.add_argument("--interval", type=int, default=env_int("HIGHLEVEL_INBOX_INTERVAL", 60))
    parser.add_argument("--live", action="store_true", help="Actually send safe FUNDz replies through HighLevel.")
    return parser.parse_args()


def main() -> None:
    load_env_file()
    args = parse_args()
    if args.manual_import:
        summary = poll_manual_imports(Path(args.manual_import))
        print(json.dumps(summary, indent=2, sort_keys=True))
        return
    live = args.live or env_bool("FUNDZ_HIGHLEVEL_POLLER_LIVE", False)
    if args.daemon:
        run_daemon(limit=args.limit, status=args.status, interval=args.interval, live=live)
        return
    summary = poll_once(limit=args.limit, status=args.status, live=live)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
