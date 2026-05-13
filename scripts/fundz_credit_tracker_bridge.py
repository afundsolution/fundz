#!/usr/bin/env python3
"""Receive credit-tracker webhooks and send automatic FUNDz replies."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from email.utils import parseaddr
from urllib.parse import urlencode
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import (
    classify_send_failure,
    quarantine_event,
    redact_sensitive,
    risky_language_hits,
    write_proposal,
)
from fundz_credit_tracker_replies import draft_reply, is_credit_tracker_record, value_for
from fundz_operational_state import DEFAULT_CLIENT_INDEX, DEFAULT_OUTPUT, build_operational_state, find_client_matches, find_index_matches, index_entry_to_client, write_client_index, write_json, write_summary_csv, DEFAULT_SUMMARY_CSV


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.local"
LOG_DIR = ROOT / "logs"
STATE_DIR = ROOT / "data" / "local" / "credit-tracker-bridge"
EVENT_LOG = LOG_DIR / "credit-tracker-bridge.jsonl"
SEEN_EVENTS = STATE_DIR / "seen-events.txt"
SEND_KILL_SWITCH_JSON = ROOT / "data" / "local" / "command-center" / "fundz-send-kill-switch.json"

DEFAULT_REPLY_TEMPLATE = json.dumps(
    {
        "contact_id": "{contact_id}",
        "conversation_id": "{conversation_id}",
        "message": "{message}",
        "source": "fundz",
    }
)
DEFAULT_USER_AGENT = "FUNDzCreditTrackerBridge/1.0"
NO_ACCESS_REPLY_RE = re.compile(
    r"\b(?:i\s+don'?t\s+have|i\s+currently\s+don'?t\s+have|need\s+(?:their\s+)?case\s+id|confirm\s+they(?:'re| are)\s+a\s+current\s+client|escalate\s+to\s+brandon|flag\s+brandon)\b",
    re.I,
)


class OutboundHTTPError(RuntimeError):
    def __init__(self, status: int, body: str, transport: str):
        super().__init__(f"HTTP {status} via {transport}: {body[:300]}")
        self.status = status
        self.body = body
        self.transport = transport


class SendKillSwitchEnabled(RuntimeError):
    """Raised when a live outbound reply is blocked by the local kill switch."""


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def truthy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "test", "dry-run", "dry_run"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def send_kill_switch_enabled(path: Path | None = None) -> tuple[bool, str]:
    if env_bool("FUNDZ_SEND_KILL_SWITCH") or env_bool("FUNDZ_COMMAND_CENTER_KILL_SWITCH"):
        return True, "environment kill switch is enabled"
    state = read_json(path or SEND_KILL_SWITCH_JSON)
    if not isinstance(state, dict):
        return False, "kill switch file missing or unreadable; defaulting to approval gates"
    enabled = truthy_value(state.get("enabled"))
    return enabled, str(state.get("reason") or "command-center kill switch is on").strip()


def assert_live_sends_allowed() -> None:
    enabled, reason = send_kill_switch_enabled()
    if enabled:
        log_event("send_blocked_kill_switch", {"reason": reason})
        raise SendKillSwitchEnabled(f"FUNDz send kill switch is enabled: {reason}")


def webhook_live_reply_gate_reason() -> str:
    if not env_bool("FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED", False):
        return "controlled webhook reply approval flag is off"
    enabled, reason = send_kill_switch_enabled()
    if enabled:
        return "send kill switch is ON: " + reason
    return ""


def log_event(kind: str, payload: dict[str, Any]) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "kind": kind,
        **redact_sensitive(payload),
    }
    line = json.dumps(entry, ensure_ascii=True, sort_keys=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with EVENT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        try:
            print(
                json.dumps(
                    {
                        "time": entry["time"],
                        "kind": "log_write_failed",
                        "target": str(EVENT_LOG),
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


def event_id(payload: dict[str, Any], body: bytes) -> str:
    explicit = value_for(
        payload,
        (
            "event_id",
            "eventId",
            "message_id",
            "messageId",
            "id",
            "webhook_id",
            "webhookId",
        ),
    )
    if explicit:
        return explicit
    return hashlib.sha256(body).hexdigest()


def has_seen(event_key: str) -> bool:
    if not SEEN_EVENTS.exists():
        return False
    return event_key in set(SEEN_EVENTS.read_text(encoding="utf-8").splitlines())


def mark_seen(event_key: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with SEEN_EVENTS.open("a", encoding="utf-8") as handle:
        handle.write(event_key + "\n")


def verify_signature(body: bytes, signature: str | None) -> bool:
    secret = os.getenv("CREDIT_TRACKER_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    clean_signature = signature.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected, clean_signature)


def is_test_only_payload(payload: dict[str, Any], header_value: str | None = None) -> bool:
    return truthy_value(header_value) or any(
        truthy_value(value_for(payload, (key,)))
        for key in ("fundz_test_only", "test_only", "dry_run", "probe_only")
    )


def message_text(payload: dict[str, Any]) -> str:
    return value_for(payload, ("message", "body", "text", "content", "message_body", "messageBody"))


CLIENT_UPDATE_RE = re.compile(
    r"\b(?:update|status|details)\b(?:\s+(?:on|for|about))?\s+([A-Z][A-Za-z'*. -]+(?:\s+[A-Z][A-Za-z'*. -]+)+)",
    re.I,
)


def requested_client_name(payload: dict[str, Any]) -> str:
    explicit = value_for(payload, ("requested_client", "client_name", "customer_name", "target_client", "targetClient"))
    if explicit:
        return clean_requested_client_name(explicit)

    text = message_text(payload)
    match = CLIENT_UPDATE_RE.search(text)
    if not match:
        return ""
    return clean_requested_client_name(match.group(1))


def clean_requested_client_name(raw_name: str) -> str:
    name = re.sub(r"\s+", " ", raw_name).strip(" .?!,")
    name = re.sub(r"^(?:the|client|customer|record for)\s+", "", name, flags=re.I).strip()
    name = re.sub(r"\b(?:please|pls|thanks|thank you|asap|right now|today)\b.*$", "", name, flags=re.I).strip()
    ignored = {"me", "my file", "my account", "an update", "a update", "the update", "the client"}
    return "" if name.lower() in ignored else name


def compact_client_update(client: dict[str, Any]) -> str:
    history = client.get("send_history", {})
    dispute_items = client.get("dispute_items", {})
    flags = [str(flag).replace("_", " ") for flag in client.get("operational_flags", [])]
    next_move = str(client.get("recommended_next_action") or "Review client file.").rstrip(" .")
    pieces = [
        f"Here is the latest FUNDz update for {client.get('client_name') or 'that client'}",
        f"Status is {client.get('status') or 'unknown'}",
        f"Stage is {client.get('stage_in_process') or 'not shown'}",
        f"Next import is {client.get('next_import') or 'not shown'}",
        (
            "Dispute items are "
            f"{dispute_items.get('all_items', 0)} total, "
            f"{dispute_items.get('in_dispute_count', 0)} in dispute, "
            f"{dispute_items.get('deleted_count', 0)} deleted, "
            f"{dispute_items.get('repaired_count', 0)} repaired"
        ),
        f"Linked history shows {history.get('email_count', 0)} email(s) and {history.get('sms_count', 0)} SMS",
    ]
    if flags:
        pieces.append("Needs attention: " + ", ".join(flags))
    pieces.append(f"Next move: {next_move}")
    return ". ".join(pieces) + "."


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def rebuild_stored_client_data() -> tuple[dict[str, Any], dict[str, Any]]:
    state = build_operational_state()
    write_json(DEFAULT_OUTPUT, state)
    write_summary_csv(DEFAULT_SUMMARY_CSV, state["clients"])
    write_client_index(DEFAULT_CLIENT_INDEX, state)
    return state, load_json_file(DEFAULT_CLIENT_INDEX)


def stored_client_matches(client_name: str) -> list[dict[str, Any]]:
    index = load_json_file(DEFAULT_CLIENT_INDEX)
    index_matches = find_index_matches(index, client_name)
    if index_matches:
        return [index_entry_to_client(match) for match in index_matches]

    state = load_json_file(DEFAULT_OUTPUT)
    state_matches = find_client_matches(state, client_name)
    if state_matches:
        return state_matches

    state, index = rebuild_stored_client_data()
    index_matches = find_index_matches(index, client_name)
    if index_matches:
        return [index_entry_to_client(match) for match in index_matches]
    return find_client_matches(state, client_name)


def reply_violates_local_lookup_policy(reply: str) -> bool:
    return bool(NO_ACCESS_REPLY_RE.search(reply or ""))


def draft_bridge_reply(payload: dict[str, Any]) -> str:
    client_name = requested_client_name(payload)
    if not client_name:
        reply = draft_reply(payload)
        return "Send me the client name and I will check the stored FUNDz client index." if reply_violates_local_lookup_policy(reply) else reply

    matches = stored_client_matches(client_name)
    if len(matches) == 1:
        return compact_client_update(matches[0])
    if len(matches) > 1:
        names = ", ".join(str(client.get("client_name") or client.get("client_key")) for client in matches[:5])
        return f"I found multiple matching FUNDz records for {client_name}: {names}. Which one should I use?"
    return (
        f"I checked the latest local DisputeFox state and did not find a matching record for {client_name}. "
        "Send the client's email, phone, or case ID and I can narrow it down."
    )


def normalized_phone(value: str) -> str:
    return re.sub(r"[^\d+]", "", value or "")


def looks_like_e164_phone(value: str) -> bool:
    phone = normalized_phone(value)
    return bool(re.fullmatch(r"\+?[1-9]\d{9,14}", phone))


def looks_like_email(value: str) -> bool:
    _, parsed = parseaddr(value or "")
    return "@" in parsed and "." in parsed.rsplit("@", 1)[-1]


def outbound_message_type(payload: dict[str, Any]) -> str:
    default_type = os.getenv("CREDIT_TRACKER_DEFAULT_MESSAGE_TYPE", "SMS")
    raw_type = value_for(payload, ("messageType", "message_type", "channel", "type")) or default_type
    if raw_type == "InboundMessage":
        raw_type = value_for(payload, ("messageType", "message_type")) or default_type
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", raw_type).strip("_")
    mappings = {
        "sms": "SMS",
        "email": "Email",
        "whatsapp": "WhatsApp",
        "app": "App_Message",
        "app_message": "App_Message",
        "appmessage": "App_Message",
        "mobile_app_sms": "App_Message",
        "mobileappsms": "App_Message",
        "portal": "App_Message",
        "client_portal": "App_Message",
        "clientportal": "App_Message",
        "ig": "IG",
        "instagram": "IG",
        "fb": "FB",
        "facebook": "FB",
        "gmb": "GMB",
        "live_chat": "Live_Chat",
        "livechat": "Live_Chat",
        "custom": "Custom",
        "credit_tracker": default_type,
        "credittracker": default_type,
    }
    return mappings.get(normalized.lower(), normalized or default_type)


def should_auto_reply(payload: dict[str, Any]) -> tuple[bool, str]:
    if env_bool("CREDIT_TRACKER_REQUIRE_CHANNEL", True) and not is_credit_tracker_record(payload):
        return False, "payload does not look like a credit-tracker event"

    event_type = value_for(payload, ("type", "event_type", "eventType"))
    if event_type and event_type not in {"InboundMessage", "MessageCreate", "ContactMessage"}:
        message_type = value_for(payload, ("messageType", "message_type"))
        if not message_type:
            return False, f"ignoring unsupported event type: {event_type}"

    direction = value_for(payload, ("direction", "message_direction", "messageDirection", "type")).lower()
    if direction and any(word in direction for word in ("outbound", "sent", "agent", "owner")):
        return False, "ignoring outbound/team message"

    inbound_message = message_text(payload)
    if not inbound_message:
        return False, "no inbound client message found"

    stop_flags = (
        value_for(payload, ("dnd", "doNotDisturb", "do_not_disturb", "blocked", "optedOut", "opted_out")).lower(),
        json.dumps(payload.get("dndSettings", ""), default=str).lower(),
    )
    if any(flag in text for text in stop_flags for flag in ("true", "all", "sms", "email")):
        return False, "contact is marked do-not-disturb"

    message_type = outbound_message_type(payload)
    phone = contact_value(payload, "phone")
    email = contact_value(payload, "email")
    contact_id = contact_value(payload, "contact_id")
    if not contact_id:
        return False, "missing contact id"
    if message_type in {"SMS", "WhatsApp"} and not looks_like_e164_phone(phone):
        return False, "missing valid SMS-capable phone number"
    if message_type == "Email" and not looks_like_email(email):
        return False, "missing valid email address"

    if env_bool("CREDIT_TRACKER_REPLY_ONCE_PER_CONTACT", False):
        if contact_id and has_seen(f"contact:{contact_id}"):
            return False, "contact already received an automatic reply"

    return True, "ready"


def contact_value(payload: dict[str, Any], fallback: str) -> str:
    aliases = {
        "contact_id": ("contact_id", "contactId", "client_id", "clientId", "customer_id", "customerId"),
        "conversation_id": ("conversation_id", "conversationId", "thread_id", "threadId"),
        "phone": ("phone", "phone_number", "phoneNumber"),
        "email": ("email", "email_address", "emailAddress"),
    }
    return value_for(payload, aliases.get(fallback, (fallback,)))


PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


def replace_placeholders(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        return PLACEHOLDER_RE.sub(lambda match: values.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [replace_placeholders(item, values) for item in value]
    if isinstance(value, dict):
        return {key: replace_placeholders(item, values) for key, item in value.items()}
    return value


def build_outbound_payload(inbound: dict[str, Any], reply: str) -> dict[str, Any]:
    template = os.getenv("CREDIT_TRACKER_OUTBOUND_TEMPLATE", DEFAULT_REPLY_TEMPLATE)
    message_html = html.escape(reply).replace("\n", "<br>")
    values = {str(key): str(value) for key, value in inbound.items() if value not in (None, "")}
    values.update({
        "message": reply,
        "message_html": message_html,
        "contact_id": contact_value(inbound, "contact_id"),
        "conversation_id": contact_value(inbound, "conversation_id"),
        "phone": contact_value(inbound, "phone"),
        "email": contact_value(inbound, "email"),
        "email_subject": value_for(inbound, ("email_subject", "subject"))
        or os.getenv("CREDIT_TRACKER_DEFAULT_EMAIL_SUBJECT", "FUNDz update"),
        "client_first_name": value_for(inbound, ("first_name", "firstname", "client_first_name", "name")),
        "inbound_message": message_text(inbound),
        "message_type": outbound_message_type(inbound),
        "location_id": value_for(inbound, ("locationId", "location_id")),
        "reply_message_id": value_for(inbound, ("messageId", "message_id", "emailMessageId", "email_message_id")),
    })
    payload = replace_placeholders(json.loads(template), values)
    if not isinstance(payload, dict):
        raise ValueError("CREDIT_TRACKER_OUTBOUND_TEMPLATE must render to a JSON object")
    return payload


def outbound_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": os.getenv("CREDIT_TRACKER_USER_AGENT", DEFAULT_USER_AGENT),
    }
    token = get_live_access_token()
    if token:
        auth_scheme = os.getenv("CREDIT_TRACKER_AUTH_SCHEME", "Bearer")
        headers["Authorization"] = f"{auth_scheme} {token}".strip()

    extra_headers = os.getenv("CREDIT_TRACKER_OUTBOUND_HEADERS", "")
    if extra_headers:
        loaded = json.loads(extra_headers)
        if not isinstance(loaded, dict):
            raise ValueError("CREDIT_TRACKER_OUTBOUND_HEADERS must be a JSON object")
        headers.update({str(key): str(value) for key, value in loaded.items()})
    return headers


def post_json_urllib(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        try:
            body_bytes = error.read()
        except Exception:
            body_bytes = error.fp.read() if getattr(error, "fp", None) else b""
        body = body_bytes.decode("utf-8", errors="replace")
        raise OutboundHTTPError(error.code, body, "urllib") from error


def curl_config_lines(headers: dict[str, str]) -> str:
    lines = ["location", "silent", "show-error"]
    for key, value in headers.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'header = "{key}: {escaped}"')
    return "\n".join(lines) + "\n"


def post_json_curl(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
        config_file.write(curl_config_lines(headers))
        config_path = Path(config_file.name)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as payload_file:
        json.dump(payload, payload_file)
        payload_path = Path(payload_file.name)

    try:
        completed = subprocess.run(
            [
                "curl",
                "--config",
                str(config_path),
                "--request",
                "POST",
                "--url",
                url,
                "--data-binary",
                f"@{payload_path}",
                "--max-time",
                str(int(max(timeout, 1))),
                "--write-out",
                "\n%{http_code}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        config_path.unlink(missing_ok=True)
        payload_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        raise urllib.error.URLError(completed.stderr.strip() or f"curl exited with {completed.returncode}")

    body, _, status_text = completed.stdout.rpartition("\n")
    try:
        status = int(status_text.strip())
    except ValueError as error:
        raise urllib.error.URLError("curl did not return an HTTP status") from error
    if not 200 <= status < 300:
        raise OutboundHTTPError(status, body, "curl")
    return status, body


def cloudflare_signature_block(status: int, body: str) -> bool:
    lower = (body or "").lower()
    return status == 403 and (
        "browser_signature_banned" in lower
        or "error 1010" in lower
        or "cloudflare" in lower and "access denied" in lower
    )


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> tuple[int, str, str]:
    transport = os.getenv("CREDIT_TRACKER_HTTP_TRANSPORT", "auto").strip().lower() or "auto"
    if transport == "curl":
        status, body = post_json_curl(url, payload, headers, timeout)
        return status, body, "curl"
    if transport not in {"auto", "urllib"}:
        raise ValueError("CREDIT_TRACKER_HTTP_TRANSPORT must be auto, urllib, or curl")

    try:
        status, body = post_json_urllib(url, payload, headers, timeout)
        return status, body, "urllib"
    except OutboundHTTPError as error:
        if transport == "auto" and cloudflare_signature_block(error.status, error.body):
            log_event("reply_transport_retry", {"from": "urllib", "to": "curl", "reason": "cloudflare signature block"})
            status, body = post_json_curl(url, payload, headers, timeout)
            return status, body, "curl"
        raise


def refresh_access_token() -> str:
    api_key = os.getenv("CREDIT_TRACKER_FIREBASE_API_KEY", "")
    refresh_token = os.getenv("CREDIT_TRACKER_REFRESH_TOKEN", "")
    if not api_key or not refresh_token:
        raise RuntimeError("CREDIT_TRACKER_FIREBASE_API_KEY or CREDIT_TRACKER_REFRESH_TOKEN is missing")

    body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode("utf-8")
    request = urllib.request.Request(
        f"https://securetoken.googleapis.com/v1/token?key={api_key}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=float(os.getenv("CREDIT_TRACKER_TIMEOUT", "12"))) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    access_token = str(payload.get("access_token", "")).strip()
    if not access_token:
        raise RuntimeError("refresh flow did not return an access token")

    os.environ["CREDIT_TRACKER_API_TOKEN"] = access_token
    log_event("reply_token_refreshed", {"expires_in": payload.get("expires_in"), "user_id": payload.get("user_id")})
    return access_token


def get_live_access_token() -> str:
    token = os.getenv("CREDIT_TRACKER_API_TOKEN", "").strip()
    if token:
        return token
    if os.getenv("CREDIT_TRACKER_REFRESH_TOKEN", "").strip():
        return refresh_access_token()
    return ""


def send_reply(inbound: dict[str, Any], reply: str) -> dict[str, Any]:
    url = os.getenv("CREDIT_TRACKER_REPLY_URL", "")
    payload = build_outbound_payload(inbound, reply)

    if url and not env_bool("CREDIT_TRACKER_DRY_RUN", False):
        assert_live_sends_allowed()

    if not env_bool("CREDIT_TRACKER_DRY_RUN", False) and not get_live_access_token():
        raise RuntimeError("CREDIT_TRACKER_API_TOKEN is missing")

    if not url or env_bool("CREDIT_TRACKER_DRY_RUN", False):
        log_event("reply_dry_run", {"payload": payload})
        return {"sent": False, "dry_run": True, "payload": payload}

    retry_limit = max(env_int("FUNDZ_AUTONOMY_RETRY_LIMIT", 2), 0)
    timeout = float(os.getenv("CREDIT_TRACKER_TIMEOUT", "12"))
    last_error: Exception | None = None

    for attempt in range(retry_limit + 1):
        try:
            status, response_body, transport = post_json(url, payload, outbound_headers(), timeout)
            result = {
                "sent": True,
                "status": status,
                "body": response_body[:1000],
                "attempt": attempt + 1,
                "transport": transport,
            }
            if attempt:
                result["retried"] = True
            log_event("reply_sent", result)
            return result
        except OutboundHTTPError as error:
            body = error.body
            last_error = error
            log_event(
                "reply_failed",
                {
                    "status": error.status,
                    "body": body[:1000],
                    "payload": payload,
                    "attempt": attempt + 1,
                    "transport": error.transport,
                },
            )
            if error.status == 401 and os.getenv("CREDIT_TRACKER_REFRESH_TOKEN", "").strip():
                os.environ["CREDIT_TRACKER_API_TOKEN"] = ""
                if attempt < retry_limit:
                    continue
            if 400 <= error.status < 500:
                quarantine_event(
                    f"outbound API rejected reply with HTTP {error.status}",
                    inbound,
                    {"status": error.status, "body": body[:1000], "outbound_payload": payload, "transport": error.transport},
                )
                write_proposal(
                    "Outbound reply request needs review",
                    classify_send_failure(error.status, body=body),
                    [{"status": error.status, "body": body[:1000], "payload": payload, "transport": error.transport}],
                )
                raise
            if attempt >= retry_limit:
                quarantine_event(
                    f"outbound API failed after {attempt + 1} attempt(s)",
                    inbound,
                    {"status": error.status, "body": body[:1000], "outbound_payload": payload, "transport": error.transport},
                )
                write_proposal(
                    "Outbound provider failure needs review",
                    classify_send_failure(error.status, body=body),
                    [{"status": error.status, "body": body[:1000], "attempts": attempt + 1, "transport": error.transport}],
                )
                raise
            time.sleep(min(2 ** attempt, 10))
        except urllib.error.URLError as error:
            last_error = error
            reason = str(error.reason)
            log_event("send_failed", {"error": reason, "payload": payload, "attempt": attempt + 1})
            if attempt >= retry_limit:
                quarantine_event(
                    f"outbound API unavailable after {attempt + 1} attempt(s)",
                    inbound,
                    {"error": reason, "outbound_payload": payload},
                )
                write_proposal(
                    "Outbound API availability needs review",
                    classify_send_failure(error=reason),
                    [{"error": reason, "attempts": attempt + 1}],
                )
                raise
            time.sleep(min(2 ** attempt, 10))

    if last_error:
        raise last_error
    raise RuntimeError("reply send failed without a captured error")


def redact_for_response(data: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_sensitive(data)
    return redacted if isinstance(redacted, dict) else {"value": redacted}


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "FUNDzCreditTrackerBridge/1.0"

    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"", "/health"}:
            self.send_json(200, {"ok": True, "service": "fundz-credit-tracker-bridge"})
            return
        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/credit-tracker/webhook":
            self.send_json(404, {"ok": False, "error": "not found"})
            return

        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        signature = self.headers.get("X-FUNDZ-Signature") or self.headers.get("X-Credit-Tracker-Signature")
        if not verify_signature(body, signature):
            log_event("webhook_rejected", {"reason": "bad signature"})
            self.send_json(401, {"ok": False, "error": "bad signature"})
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(400, {"ok": False, "error": "invalid JSON"})
            return

        if not isinstance(payload, dict):
            self.send_json(400, {"ok": False, "error": "JSON body must be an object"})
            return

        test_only = is_test_only_payload(payload, self.headers.get("X-FUNDZ-Test-Only"))
        key = event_id(payload, body)
        if not test_only and has_seen(f"event:{key}"):
            self.send_json(200, {"ok": True, "duplicate": True})
            return

        allowed, reason = should_auto_reply(payload)
        if not allowed:
            log_event("webhook_ignored", {"event_id": key, "reason": reason, "payload": redact_for_response(payload)})
            if not test_only:
                quarantine_event(reason, payload, {"event_id": key, "decision": "ignored"})
                mark_seen(f"event:{key}")
            self.send_json(200, {"ok": True, "ignored": True, "reason": reason, "test_only": test_only})
            return

        reply = draft_bridge_reply(payload)
        risky_hits = risky_language_hits(reply)
        if risky_hits:
            if not test_only:
                quarantine_event(
                    "generated reply contained risky language",
                    payload,
                    {"event_id": key, "reply": reply, "risky_terms": risky_hits},
                )
                write_proposal(
                    "Risky reply language needs safer rules",
                    classify_send_failure(error="risky generated reply"),
                    [{"event_id": key, "reply": reply, "risky_terms": risky_hits}],
                    extra_tests=["Generated replies containing risky credit-repair claims are blocked before send."],
                )
            log_event("reply_blocked_risky_language", {"event_id": key, "risky_terms": risky_hits})
            if not test_only:
                mark_seen(f"event:{key}")
            self.send_json(200, {"ok": True, "ignored": True, "reason": "generated reply contained risky language", "test_only": test_only})
            return

        if test_only:
            log_event("webhook_test_only", {"event_id": key, "would_reply": True, "payload": redact_for_response(payload)})
            self.send_json(200, {"ok": True, "test_only": True, "would_reply": True, "reply_preview": reply})
            return

        gate_reason = webhook_live_reply_gate_reason()
        if gate_reason:
            log_event("reply_hold", {"event_id": key, "reason": gate_reason, "payload": redact_for_response(payload)})
            mark_seen(f"event:{key}")
            self.send_json(200, {"ok": True, "held": True, "reason": gate_reason})
            return

        try:
            send_result = send_reply(payload, reply)
        except Exception as error:  # noqa: BLE001 - bridge should log and return API failure details.
            log_event(
                "webhook_error",
                {"event_id": key, "error": str(error), "payload": redact_for_response(payload)},
            )
            quarantine_event("reply send failed", payload, {"event_id": key, "error": str(error)})
            self.send_json(502, {"ok": False, "error": "reply send failed"})
            return

        mark_seen(f"event:{key}")
        contact_id = contact_value(payload, "contact_id")
        if env_bool("CREDIT_TRACKER_REPLY_ONCE_PER_CONTACT", False) and contact_id:
            mark_seen(f"contact:{contact_id}")

        log_event(
            "webhook_replied",
            {
                "event_id": key,
                "client": value_for(payload, ("first_name", "firstname", "client_first_name", "name")) or "unknown",
                "send_result": send_result,
            },
        )
        self.send_json(200, {"ok": True, "reply": reply, "send_result": send_result})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - inherited API name.
        log_event("http", {"message": format % args})

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), BridgeHandler)
    log_event("bridge_started", {"host": host, "port": port})
    print(f"FUNDz credit tracker bridge listening on http://{host}:{port}")
    print("Webhook path: /credit-tracker/webhook")
    server.serve_forever()


def self_test() -> None:
    sample = {
        "event_id": "self-test",
        "channel": "credit-tracker",
        "direction": "inbound",
        "first_name": "Test",
        "contact_id": "contact-test",
        "conversation_id": "conversation-test",
        "message": "Can I get an update?",
        "phone": "+15555550123",
        "status": "active",
        "bureau": "Experian",
        "creditor": "Sample Bank",
    }
    allowed, reason = should_auto_reply(sample)
    if not allowed:
        raise SystemExit(f"Self-test failed: {reason}")
    reply = draft_bridge_reply(sample)
    result = send_reply(sample, reply)
    print(json.dumps({"reply": reply, "send_result": result}, indent=2))


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Run the FUNDz credit-tracker auto-reply bridge.")
    parser.add_argument("--host", default=os.getenv("FUNDZ_BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FUNDZ_BRIDGE_PORT", "8787")))
    parser.add_argument("--self-test", action="store_true", help="Build and send one dry-run/test reply, then exit.")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    run_server(args.host, args.port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
