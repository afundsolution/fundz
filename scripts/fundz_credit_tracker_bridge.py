#!/usr/bin/env python3
"""Receive credit-tracker webhooks and send automatic FUNDz replies."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fundz_credit_tracker_replies import draft_reply, is_credit_tracker_record, value_for


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.local"
LOG_DIR = ROOT / "logs"
STATE_DIR = ROOT / "data" / "local" / "credit-tracker-bridge"
EVENT_LOG = LOG_DIR / "credit-tracker-bridge.jsonl"
SEEN_EVENTS = STATE_DIR / "seen-events.txt"

DEFAULT_REPLY_TEMPLATE = json.dumps(
    {
        "contact_id": "{contact_id}",
        "conversation_id": "{conversation_id}",
        "message": "{message}",
        "source": "fundz",
    }
)


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


def log_event(kind: str, payload: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "kind": kind,
        **payload,
    }
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")


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


def message_text(payload: dict[str, Any]) -> str:
    return value_for(payload, ("message", "body", "text", "content", "message_body", "messageBody"))


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

    if env_bool("CREDIT_TRACKER_REPLY_ONCE_PER_CONTACT", False):
        contact_id = contact_value(payload, "contact_id")
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
    values = {str(key): str(value) for key, value in inbound.items() if value not in (None, "")}
    values.update({
        "message": reply,
        "contact_id": contact_value(inbound, "contact_id"),
        "conversation_id": contact_value(inbound, "conversation_id"),
        "phone": contact_value(inbound, "phone"),
        "email": contact_value(inbound, "email"),
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
    headers = {"Content-Type": "application/json"}
    token = os.getenv("CREDIT_TRACKER_API_TOKEN", "")
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


def send_reply(inbound: dict[str, Any], reply: str) -> dict[str, Any]:
    url = os.getenv("CREDIT_TRACKER_REPLY_URL", "")
    payload = build_outbound_payload(inbound, reply)

    if not url or env_bool("CREDIT_TRACKER_DRY_RUN", False):
        log_event("reply_dry_run", {"payload": payload})
        return {"sent": False, "dry_run": True, "payload": payload}

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=outbound_headers(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("CREDIT_TRACKER_TIMEOUT", "12"))) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            result = {"sent": True, "status": response.status, "body": response_body[:1000]}
            log_event("reply_sent", result)
            return result
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        log_event("reply_failed", {"status": error.code, "body": body[:1000]})
        raise


def redact_for_response(data: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(data)
    for key in list(redacted):
        if re.search(r"token|secret|authorization|api_key", key, flags=re.I):
            redacted[key] = "[redacted]"
    return redacted


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

        key = event_id(payload, body)
        if has_seen(f"event:{key}"):
            self.send_json(200, {"ok": True, "duplicate": True})
            return

        allowed, reason = should_auto_reply(payload)
        if not allowed:
            log_event("webhook_ignored", {"event_id": key, "reason": reason, "payload": redact_for_response(payload)})
            mark_seen(f"event:{key}")
            self.send_json(200, {"ok": True, "ignored": True, "reason": reason})
            return

        reply = draft_reply(payload)
        try:
            send_result = send_reply(payload, reply)
        except Exception as error:  # noqa: BLE001 - bridge should log and return API failure details.
            log_event("webhook_error", {"event_id": key, "error": str(error)})
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
        "status": "active",
        "bureau": "Experian",
        "creditor": "Sample Bank",
    }
    allowed, reason = should_auto_reply(sample)
    if not allowed:
        raise SystemExit(f"Self-test failed: {reason}")
    reply = draft_reply(sample)
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
