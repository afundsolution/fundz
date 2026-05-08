#!/usr/bin/env python3
"""Send a signed test-only Credit Tracker webhook through the public tunnel."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from fundz_credit_tracker_bridge import load_env_file


DEFAULT_URL = "https://fundz.afundsolution.com/credit-tracker/webhook"


def signed_headers(body: bytes, secret: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-FUNDZ-Test-Only": "true",
        "User-Agent": "FUNDzWebhookProbe/1.0",
    }
    if secret:
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-FUNDZ-Signature"] = f"sha256={signature}"
    return headers


def build_payload() -> dict[str, str | bool]:
    stamp = time.strftime("%Y%m%d%H%M%S")
    return {
        "event_id": f"fundz-webhook-probe-{stamp}",
        "channel": "credit-tracker",
        "direction": "inbound",
        "type": "InboundMessage",
        "messageType": "SMS",
        "locationId": "TWntg8tCBSQQjwgPmU2I",
        "contact_id": "fundz-test-contact",
        "conversation_id": "fundz-test-conversation",
        "first_name": "Test",
        "phone": "+15555550123",
        "message": "Can I get an update?",
        "status": "active",
        "fundz_test_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    load_env_file()
    from os import getenv

    payload = build_payload()
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=body,
        headers=signed_headers(body, getenv("CREDIT_TRACKER_WEBHOOK_SECRET", "")),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        status = error.code
        response_body = error.read().decode("utf-8", errors="replace")

    result = {
        "ok": 200 <= status < 300,
        "status": status,
        "url": args.url,
        "test_only": True,
        "response": json.loads(response_body) if response_body.startswith("{") else response_body,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
