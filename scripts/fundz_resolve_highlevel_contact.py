#!/usr/bin/env python3
"""Resolve a HighLevel contact ID from a verified email or phone."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fundz_autonomy_daemon import redact_sensitive
from fundz_credit_tracker_bridge import DEFAULT_USER_AGENT, load_env_file, outbound_headers


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "semi-autonomous"
RESOLVED_CONTACTS = OUTPUT_DIR / "resolved-highlevel-contacts.jsonl"
DUPLICATE_SEARCH_URL = "https://services.leadconnectorhq.com/contacts/search/duplicate"


def env_location_id() -> str:
    for name in (
        "CREDIT_TRACKER_LOCATION_ID",
        "HIGHLEVEL_LOCATION_ID",
        "GHL_LOCATION_ID",
        "LEADCONNECTOR_LOCATION_ID",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def curl_config_lines(headers: dict[str, str]) -> str:
    lines = ["location", "silent", "show-error"]
    for key, value in headers.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'header = "{key}: {escaped}"')
    return "\n".join(lines) + "\n"


def request_get(url: str, headers: dict[str, str], timeout: float = 20.0) -> tuple[int, str]:
    transport = os.getenv("CREDIT_TRACKER_HTTP_TRANSPORT", "auto").strip().lower() or "auto"
    if transport == "curl":
        return request_get_curl(url, headers, timeout)
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        if transport == "auto" and error.code == 403 and "cloudflare" in body.lower():
            return request_get_curl(url, headers, timeout)
        return error.code, body


def request_get_curl(url: str, headers: dict[str, str], timeout: float = 20.0) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
        config_file.write(curl_config_lines(headers))
        config_path = Path(config_file.name)
    try:
        completed = subprocess.run(
            [
                "curl",
                "--config",
                str(config_path),
                "--request",
                "GET",
                "--url",
                url,
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

    if completed.returncode != 0:
        raise urllib.error.URLError(completed.stderr.strip() or f"curl exited with {completed.returncode}")

    body, _, status_text = completed.stdout.rpartition("\n")
    try:
        return int(status_text.strip()), body
    except ValueError as error:
        raise urllib.error.URLError("curl did not return an HTTP status") from error


def build_duplicate_search_url(location_id: str, email: str = "", phone: str = "") -> str:
    params = {"locationId": location_id}
    if email:
        params["email"] = email
    if phone:
        params["number"] = phone
    return DUPLICATE_SEARCH_URL + "?" + urllib.parse.urlencode(params)


def extract_contact(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("contact", "data", "duplicateContact"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    contacts = payload.get("contacts")
    if isinstance(contacts, list) and contacts and isinstance(contacts[0], dict):
        return contacts[0]
    if isinstance(payload.get("id"), str):
        return payload
    return None


def resolve_contact(email: str = "", phone: str = "", location_id: str = "") -> dict[str, Any]:
    load_env_file()
    location_id = location_id or env_location_id()
    if not location_id:
        raise SystemExit("Missing CREDIT_TRACKER_LOCATION_ID. Add the HighLevel sub-account/location ID to .env.local.")
    if not email and not phone:
        raise SystemExit("Provide --email or --phone to resolve a HighLevel contact.")

    headers = outbound_headers()
    headers.setdefault("Accept", "application/json")
    headers.setdefault("User-Agent", os.getenv("CREDIT_TRACKER_USER_AGENT", DEFAULT_USER_AGENT))
    url = build_duplicate_search_url(location_id, email=email, phone=phone)
    status, body = request_get(url, headers)
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"raw": body}

    if not 200 <= status < 300:
        return {"ok": False, "status": status, "error": payload, "contact": None}

    contact = extract_contact(payload if isinstance(payload, dict) else {})
    return {"ok": bool(contact), "status": status, "error": None, "contact": contact, "raw": payload}


def contact_summary(contact: dict[str, Any] | None) -> dict[str, Any]:
    if not contact:
        return {}
    return {
        "id": contact.get("id") or contact.get("_id") or contact.get("contactId"),
        "name": contact.get("name") or " ".join(
            item for item in [str(contact.get("firstName", "")).strip(), str(contact.get("lastName", "")).strip()] if item
        ),
        "email_present": bool(contact.get("email")),
        "phone_present": bool(contact.get("phone")),
    }


def save_resolution(result: dict[str, Any], email: str = "", phone: str = "") -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "lookup": {"email": email, "phone": phone},
        "result": result,
    }
    with RESOLVED_CONTACTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_sensitive(entry), sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="", help="Known contact email to look up.")
    parser.add_argument("--phone", default="", help="Known contact phone to look up.")
    parser.add_argument("--location-id", default="", help="HighLevel location/sub-account ID. Defaults to env.")
    parser.add_argument("--save", action="store_true", help="Save a redacted lookup event locally.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = resolve_contact(email=args.email, phone=args.phone, location_id=args.location_id)
    if args.save:
        save_resolution(result, email=args.email, phone=args.phone)
    output = {
        "ok": result.get("ok", False),
        "status": result.get("status"),
        "contact": contact_summary(result.get("contact")),
        "error": result.get("error"),
    }
    print(json.dumps(redact_sensitive(output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
