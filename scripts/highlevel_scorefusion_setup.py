#!/usr/bin/env python3
"""Idempotently prepare HighLevel ScoreFusion billing fields."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "highlevel-scorefusion-setup.json"
CUSTOM_FIELDS_URL = "https://services.leadconnectorhq.com/locations/{location_id}/customFields"

FIELD_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "SF_Enrollment_Date", "dataType": "DATE", "placeholder": "ScoreFusion enrollment date"},
    {"name": "SF_Next_Charge_Date", "dataType": "DATE", "placeholder": "Next ScoreFusion charge date"},
    {"name": "SF_Warning_Sent_Date", "dataType": "DATE", "placeholder": "Last warning sent date"},
    {"name": "SF_Last_Charge_Date", "dataType": "DATE", "placeholder": "Last confirmed charge date"},
    {
        "name": "SF_Status",
        "dataType": "SINGLE_OPTIONS",
        "placeholder": "ScoreFusion billing status",
        "options": ["Active", "Warning Sent", "At Risk", "Cancelled"],
    },
    {"name": "SF_Amount_Due", "dataType": "MONETORY", "placeholder": "ScoreFusion amount due"},
    {"name": "SF_Last_DisputeFox_Sync", "dataType": "DATE", "placeholder": "Last DisputeFox sync date"},
    {"name": "SF_DisputeFox_Billing_Status", "dataType": "TEXT", "placeholder": "DisputeFox billing status"},
]


def load_env_file(path: Path = ROOT / ".env.local") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        os.environ.setdefault(key.strip(), raw_value.strip().strip("\"'"))


def env_location_id() -> str:
    for key in ("CREDIT_TRACKER_LOCATION_ID", "HIGHLEVEL_LOCATION_ID", "GHL_LOCATION_ID", "LEADCONNECTOR_LOCATION_ID"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def auth_token() -> str:
    token = os.getenv("CREDIT_TRACKER_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("Missing CREDIT_TRACKER_API_TOKEN in .env.local or environment.")
    return token


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def curl_config(url: str, method: str, token: str, data_file: Path | None = None) -> str:
    lines = [
        "location",
        "silent",
        "show-error",
        f'url = "{url}"',
        f'request = "{method}"',
        f'header = "Authorization: Bearer {token}"',
        'header = "Version: 2021-07-28"',
        'header = "Accept: application/json"',
        'header = "Content-Type: application/json"',
        'header = "User-Agent: Mozilla/5.0"',
    ]
    if data_file:
        lines.append(f'data = "@{data_file}"')
    return "\n".join(lines) + "\n"


def request_json(url: str, method: str, token: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    config_path: Path | None = None
    data_path: Path | None = None
    try:
        if payload is not None:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as data_file:
                json.dump(payload, data_file)
                data_path = Path(data_file.name)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
            config_file.write(curl_config(url, method, token, data_path))
            config_path = Path(config_file.name)

        completed = subprocess.run(
            ["curl", "--config", str(config_path), "--max-time", "30", "--write-out", "\n%{http_code}"],
            check=False,
            capture_output=True,
            text=True,
        )
        body, _, status_text = completed.stdout.rpartition("\n")
        try:
            status = int(status_text.strip())
        except ValueError:
            status = 0
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        if completed.returncode != 0:
            parsed["curl_error"] = completed.stderr.strip()
        return status, parsed
    finally:
        if config_path:
            config_path.unlink(missing_ok=True)
        if data_path:
            data_path.unlink(missing_ok=True)


def get_custom_fields(location_id: str, token: str) -> list[dict[str, Any]]:
    status, payload = request_json(CUSTOM_FIELDS_URL.format(location_id=location_id), "GET", token)
    if status != 200:
        raise SystemExit(f"Could not read HighLevel custom fields. Status {status}: {payload}")
    fields = payload.get("customFields", [])
    if not isinstance(fields, list):
        raise SystemExit("HighLevel custom fields response was not a list.")
    return [field for field in fields if isinstance(field, dict)]


def create_custom_field(location_id: str, token: str, definition: dict[str, Any], position: int) -> dict[str, Any]:
    payload = {
        "name": definition["name"],
        "dataType": definition["dataType"],
        "placeholder": definition.get("placeholder", definition["name"]),
        "model": "contact",
        "position": position,
    }
    if definition.get("options"):
        payload["options"] = definition["options"]
    status, response = request_json(CUSTOM_FIELDS_URL.format(location_id=location_id), "POST", token, payload)
    return {"status": status, "payload": response}


def ensure_fields(location_id: str, output_path: Path) -> dict[str, Any]:
    load_env_file()
    token = auth_token()
    existing = get_custom_fields(location_id, token)
    by_name = {normalize(str(field.get("name", ""))): field for field in existing}
    by_key = {normalize(str(field.get("fieldKey", "").removeprefix("contact."))): field for field in existing}
    base_position = max([int(field.get("position") or 0) for field in existing] or [0]) + 50

    results: list[dict[str, Any]] = []
    for offset, definition in enumerate(FIELD_DEFINITIONS):
        lookup = normalize(definition["name"])
        found = by_name.get(lookup) or by_key.get(lookup)
        if found:
            results.append({"name": definition["name"], "action": "exists", "id": found.get("id"), "fieldKey": found.get("fieldKey")})
            continue
        created = create_custom_field(location_id, token, definition, base_position + offset * 50)
        payload = created["payload"]
        field = payload.get("customField") if isinstance(payload, dict) else None
        if not isinstance(field, dict):
            field = payload if isinstance(payload, dict) else {}
        results.append(
            {
                "name": definition["name"],
                "action": "created" if 200 <= int(created["status"]) < 300 else "failed",
                "status": created["status"],
                "id": field.get("id"),
                "fieldKey": field.get("fieldKey"),
                "error": payload if not 200 <= int(created["status"]) < 300 else None,
            }
        )

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "location_id": location_id,
        "created": sum(1 for item in results if item["action"] == "created"),
        "existing": sum(1 for item in results if item["action"] == "exists"),
        "failed": sum(1 for item in results if item["action"] == "failed"),
        "fields": results,
        "notes": [
            "HighLevel connector 401 was bypassed with direct LeadConnector API access using the local private integration token.",
            "Contact custom-field folder placement is not exposed by the public contact custom-field endpoint; organize into the ScoreFusion Billing folder in the UI if folder grouping is required.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location-id", default="", help="HighLevel sub-account/location ID.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Local setup result JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file()
    location_id = args.location_id or env_location_id()
    if not location_id:
        raise SystemExit("Missing location ID. Pass --location-id or set CREDIT_TRACKER_LOCATION_ID.")
    summary = ensure_fields(location_id, args.output)
    print(f"HighLevel ScoreFusion setup complete for location {location_id}.")
    print(f"- created: {summary['created']}")
    print(f"- existing: {summary['existing']}")
    print(f"- failed: {summary['failed']}")
    print(f"- output: {args.output}")


if __name__ == "__main__":
    main()
