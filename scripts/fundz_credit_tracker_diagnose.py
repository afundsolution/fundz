#!/usr/bin/env python3
"""Diagnose whether a credit-tracker payload is safe for auto-reply."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fundz_credit_tracker_bridge import (
    build_outbound_payload,
    draft_reply,
    load_env_file,
    outbound_message_type,
    should_auto_reply,
)


def read_payload(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Payload file must contain a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain why FUNDz would send or skip an auto-reply.")
    parser.add_argument("payload", help="Path to a JSON payload file")
    args = parser.parse_args()

    load_env_file()
    payload = read_payload(Path(args.payload))
    allowed, reason = should_auto_reply(payload)
    result = {
        "allowed": allowed,
        "reason": reason,
        "message_type": outbound_message_type(payload),
    }
    if allowed:
        reply = draft_reply(payload)
        result["reply"] = reply
        result["outbound_payload"] = build_outbound_payload(payload, reply)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
