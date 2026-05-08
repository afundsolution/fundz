#!/usr/bin/env python3
"""Prepare or trigger AutoFox/Credit Tracker portal message workflow entries."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import highlevel_scorefusion_setup as setup
from fundz_autonomy_daemon import redact_sensitive


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data" / "local" / "semi-autonomous"
DEFAULT_PACKET = RUN_DIR / "expansion-batch-packet.json"
RECEIPT_DIR = RUN_DIR / "receipts"
CONTACT_URL = "https://services.leadconnectorhq.com/contacts/{contact_id}"
ADD_TAG_URL = "https://services.leadconnectorhq.com/contacts/{contact_id}/tags"
REMOVE_TAG_URL = "https://services.leadconnectorhq.com/contacts/{contact_id}/tags"
ADD_WORKFLOW_URL = "https://services.leadconnectorhq.com/contacts/{contact_id}/workflow/{workflow_id}"


def load_packet(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def approved_items(packet: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in packet.get("items", [])
        if item.get("resolution", {}).get("contact_id") and item.get("message")
    ]


def contact_id(item: dict[str, Any]) -> str:
    return str(item.get("resolution", {}).get("contact_id") or "").strip()


def portal_message(item: dict[str, Any]) -> str:
    return str(item.get("message") or "").strip()


def custom_fields_payload(message_field_id: str, message_field_key: str, item: dict[str, Any]) -> list[dict[str, str]]:
    if not message_field_id or not message_field_key:
        return []
    return [
        {
            "id": message_field_id,
            "key": message_field_key.removeprefix("contact."),
            "field_value": portal_message(item),
        }
    ]


def update_portal_message_field(token: str, item: dict[str, Any], message_field_id: str, message_field_key: str) -> dict[str, Any]:
    fields = custom_fields_payload(message_field_id, message_field_key, item)
    if not fields:
        return {"action": "skipped", "reason": "portal message custom field not configured"}
    status, payload = setup.request_json(
        CONTACT_URL.format(contact_id=contact_id(item)),
        "PUT",
        token,
        {"customFields": fields},
    )
    return {"action": "update_portal_message_field", "status": status, "ok": 200 <= int(status) < 300, "payload": payload}


def add_trigger_tag(token: str, item: dict[str, Any], tag: str) -> dict[str, Any]:
    if not tag:
        return {"action": "skipped", "reason": "portal trigger tag not configured"}
    status, payload = setup.request_json(
        ADD_TAG_URL.format(contact_id=contact_id(item)),
        "POST",
        token,
        {"tags": [tag]},
    )
    added = payload.get("tagsAdded", []) if isinstance(payload, dict) else []
    return {
        "action": "add_trigger_tag",
        "tag": tag,
        "status": status,
        "ok": 200 <= int(status) < 300,
        "newly_added": tag in added,
        "already_present": 200 <= int(status) < 300 and tag not in added,
        "payload": payload,
    }


def remove_trigger_tag(token: str, item: dict[str, Any], tag: str) -> dict[str, Any]:
    if not tag:
        return {"action": "skipped", "reason": "portal trigger tag not configured"}
    status, payload = setup.request_json(
        REMOVE_TAG_URL.format(contact_id=contact_id(item)),
        "DELETE",
        token,
        {"tags": [tag]},
    )
    return {"action": "remove_trigger_tag", "tag": tag, "status": status, "ok": 200 <= int(status) < 300, "payload": payload}


def add_to_workflow(token: str, item: dict[str, Any], workflow_id: str) -> dict[str, Any]:
    if not workflow_id:
        return {"action": "skipped", "reason": "portal workflow id not configured"}
    status, payload = setup.request_json(
        ADD_WORKFLOW_URL.format(contact_id=contact_id(item), workflow_id=workflow_id),
        "POST",
        token,
        {},
    )
    return {"action": "add_to_workflow", "workflow_id": workflow_id, "status": status, "ok": 200 <= int(status) < 300, "payload": payload}


def write_preview(packet: dict[str, Any], path: Path, trigger_tag: str, workflow_id: str) -> None:
    lines = [
        "# FUNDz AutoFox / Credit Tracker Portal Trigger Preview",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"Source batch: {packet.get('batch_id')}",
        f"Trigger tag: {trigger_tag or 'not configured'}",
        f"Workflow ID: {workflow_id or 'not configured'}",
        "",
        "## Items",
    ]
    for item in approved_items(packet):
        lines.extend(
            [
                "",
                f"### {item.get('client_name')}",
                f"- Contact resolved: {'yes' if contact_id(item) else 'no'}",
                f"- Message: {portal_message(item)}",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    setup.load_env_file()
    packet = load_packet(args.packet)
    trigger_tag = args.trigger_tag or os.getenv("AUTOFOX_PORTAL_TRIGGER_TAG", "").strip()
    workflow_id = args.workflow_id or os.getenv("AUTOFOX_PORTAL_WORKFLOW_ID", "").strip()
    message_field_id = args.message_field_id or os.getenv("AUTOFOX_PORTAL_MESSAGE_FIELD_ID", "").strip()
    message_field_key = args.message_field_key or os.getenv("AUTOFOX_PORTAL_MESSAGE_FIELD_KEY", "").strip()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    preview_path = RECEIPT_DIR / f"autofox-portal-trigger-preview-{stamp}.md"
    write_preview(packet, preview_path, trigger_tag, workflow_id)

    if args.preview:
        return {
            "mode": "preview",
            "items": len(approved_items(packet)),
            "preview_path": str(preview_path),
            "ready_for_live": bool(trigger_tag or workflow_id),
            "needs": [] if (trigger_tag or workflow_id) else ["AUTOFOX_PORTAL_TRIGGER_TAG or AUTOFOX_PORTAL_WORKFLOW_ID"],
        }

    if not args.approved_live_trigger:
        return {"mode": "blocked", "reason": "--live requires --approved-live-trigger", "preview_path": str(preview_path)}
    if not trigger_tag and not workflow_id:
        return {
            "mode": "blocked",
            "reason": "Configure AUTOFOX_PORTAL_TRIGGER_TAG or AUTOFOX_PORTAL_WORKFLOW_ID first.",
            "preview_path": str(preview_path),
        }

    token = setup.auth_token()
    results = []
    for item in approved_items(packet):
        item_results: list[dict[str, Any]] = []
        field_result = update_portal_message_field(token, item, message_field_id, message_field_key)
        item_results.append(field_result)
        if trigger_tag and args.force_retrigger:
            item_results.append(remove_trigger_tag(token, item, trigger_tag))
        if trigger_tag:
            item_results.append(add_trigger_tag(token, item, trigger_tag))
        if workflow_id:
            item_results.append(add_to_workflow(token, item, workflow_id))
        results.append({"client_name": item.get("client_name"), "contact_id": contact_id(item), "results": item_results})

    receipt = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "autofox_portal_trigger",
        "source_batch_id": packet.get("batch_id"),
        "trigger_tag": trigger_tag,
        "workflow_id": workflow_id,
        "message_field_configured": bool(message_field_id and message_field_key),
        "results": results,
    }
    receipt_path = RECEIPT_DIR / f"autofox-portal-trigger-result-{stamp}.json"
    receipt_path.write_text(json.dumps(redact_sensitive(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "mode": "live",
        "items": len(results),
        "receipt_path": str(receipt_path),
        "preview_path": str(preview_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--preview", action="store_true", help="Write a preview only. No live workflow/tag trigger.")
    parser.add_argument("--live", action="store_true", help="Trigger the configured AutoFox/Credit Tracker workflow/tag.")
    parser.add_argument("--approved-live-trigger", action="store_true", help="Required with --live after owner approval.")
    parser.add_argument("--trigger-tag", default="")
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--message-field-id", default="")
    parser.add_argument("--message-field-key", default="")
    parser.add_argument(
        "--force-retrigger",
        action="store_true",
        help="Remove the trigger tag before re-adding it. Requires explicit owner approval because it edits the contact tag list.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.preview and not args.live:
        args.preview = True
    print(json.dumps(run(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
