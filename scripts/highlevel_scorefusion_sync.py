#!/usr/bin/env python3
"""Sync ScoreFusion billing roster values into HighLevel contact custom fields."""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

import highlevel_scorefusion_setup as setup


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / "data" / "local" / "scorefusion-billing-dashboard"
DRIVE_DIR = ROOT / "data" / "G Drive" / "scorefusion-billing-dashboard"
ROSTER_BASENAME = "client-billing-roster.csv"
SYNC_RECEIPT_BASENAME = "highlevel-scorefusion-sync.json"
IMPORT_CSV_BASENAME = "highlevel-scorefusion-create-update-import.csv"
DEFAULT_ROSTER = LOCAL_DIR / ROSTER_BASENAME
DEFAULT_OUTPUT = LOCAL_DIR / SYNC_RECEIPT_BASENAME
DEFAULT_IMPORT_CSV = LOCAL_DIR / IMPORT_CSV_BASENAME
CONTACT_URL = "https://services.leadconnectorhq.com/contacts/{contact_id}"
DUPLICATE_SEARCH_URL = "https://services.leadconnectorhq.com/contacts/search/duplicate"

FIELD_TO_ROSTER = {
    "SF_Enrollment_Date": "enrollment_date",
    "SF_Next_Charge_Date": "next_charge_date",
    "SF_Warning_Sent_Date": "last_warning_sent_date",
    "SF_Last_Charge_Date": "last_charge_date",
    "SF_Status": "highlevel_pipeline_stage",
    "SF_Amount_Due": "amount_due",
    "SF_Last_DisputeFox_Sync": "__sync_date",
    "SF_DisputeFox_Billing_Status": "billing_status",
}

STATUS_VALUES = {
    "": "",
    "enrolled": "Active",
    "active": "Active",
    "warning sent": "Warning Sent",
    "at risk": "At Risk",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def default_roster_path(use_drive_paths: bool) -> Path:
    if use_drive_paths:
        return DRIVE_DIR / ROSTER_BASENAME
    if DEFAULT_ROSTER.exists():
        return DEFAULT_ROSTER
    drive_roster = DRIVE_DIR / ROSTER_BASENAME
    return drive_roster if drive_roster.exists() else DEFAULT_ROSTER


def default_output_path(use_drive_paths: bool) -> Path:
    return (DRIVE_DIR if use_drive_paths else LOCAL_DIR) / SYNC_RECEIPT_BASENAME


def default_import_csv_path(use_drive_paths: bool) -> Path:
    return (DRIVE_DIR if use_drive_paths else LOCAL_DIR) / IMPORT_CSV_BASENAME


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


def resolve_contact_id(location_id: str, token: str, row: dict[str, str]) -> tuple[str, dict[str, Any] | None]:
    existing_id = row.get("highlevel_contact_id", "").strip()
    if existing_id:
        return existing_id, {"source": "roster"}
    email = row.get("email", "").strip().lower()
    phone = row.get("phone", "").strip()
    if not email and not phone:
        return "", {"source": "none", "reason": "missing email and phone"}

    status, payload = setup.request_json(build_duplicate_search_url(location_id, email=email, phone=phone), "GET", token)
    if not 200 <= status < 300:
        return "", {"source": "duplicate_search", "status": status, "error": payload}
    contact = extract_contact(payload if isinstance(payload, dict) else {})
    if not contact:
        return "", {"source": "duplicate_search", "status": status, "reason": "not found"}
    contact_id = str(contact.get("id") or contact.get("_id") or contact.get("contactId") or "").strip()
    return contact_id, {"source": "duplicate_search", "status": status}


def field_lookup(location_id: str, token: str) -> dict[str, dict[str, Any]]:
    fields = setup.get_custom_fields(location_id, token)
    by_name: dict[str, dict[str, Any]] = {}
    for field in fields:
        name = str(field.get("name", ""))
        if name in FIELD_TO_ROSTER:
            by_name[name] = field
    return by_name


def normalized_value(field_name: str, row: dict[str, str], sync_date: str) -> str:
    source = FIELD_TO_ROSTER[field_name]
    raw = sync_date if source == "__sync_date" else row.get(source, "")
    value = str(raw or "").strip()
    if field_name == "SF_Status":
        return STATUS_VALUES.get(value.lower(), value)
    if field_name == "SF_Amount_Due" and value:
        try:
            return f"{float(value):.2f}"
        except ValueError:
            return value
    return value


def custom_field_payload(row: dict[str, str], fields: dict[str, dict[str, Any]], sync_date: str) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for field_name in FIELD_TO_ROSTER:
        field = fields.get(field_name, {})
        field_id = str(field.get("id") or "").strip()
        field_key = str(field.get("fieldKey") or "").removeprefix("contact.").strip()
        value = normalized_value(field_name, row, sync_date)
        if not field_id or not field_key:
            continue
        if value == "" and field_name not in {"SF_Amount_Due", "SF_Last_DisputeFox_Sync"}:
            continue
        payload.append({"id": field_id, "key": field_key, "field_value": value})
    return payload


def import_csv_rows(roster_rows: list[dict[str, str]], sync_date: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in roster_rows:
        name_parts = row.get("client_name", "").strip().split()
        output = {
            "First Name": name_parts[0] if name_parts else "",
            "Last Name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
            "Email": row.get("email", "").strip().lower(),
            "Phone": row.get("phone", "").strip(),
        }
        for field_name in FIELD_TO_ROSTER:
            value = normalized_value(field_name, row, sync_date)
            if value or field_name in {"SF_Amount_Due", "SF_Last_DisputeFox_Sync"}:
                output[field_name] = value
            else:
                output[field_name] = ""
        if output["Email"] or output["Phone"]:
            rows.append(output)
    return rows


def write_import_csv(roster_path: Path, output_path: Path, sync_date: str) -> dict[str, Any]:
    rows = import_csv_rows(read_csv(roster_path), sync_date)
    fields = ["First Name", "Last Name", "Email", "Phone", *FIELD_TO_ROSTER.keys()]
    write_csv(output_path, rows, fields)
    return {"path": str(output_path), "rows": len(rows), "fields": fields}


def update_contact(contact_id: str, token: str, custom_fields: list[dict[str, str]]) -> tuple[int, dict[str, Any]]:
    return setup.request_json(CONTACT_URL.format(contact_id=contact_id), "PUT", token, {"customFields": custom_fields})


def sync_roster(
    location_id: str,
    roster_path: Path,
    output_path: Path,
    approved_live_sync: bool,
    limit: int,
    sync_date: str,
) -> dict[str, Any]:
    setup.load_env_file()
    token = setup.auth_token()
    fields = field_lookup(location_id, token)
    missing_fields = [name for name in FIELD_TO_ROSTER if name not in fields]
    if missing_fields:
        raise SystemExit(f"Missing HighLevel ScoreFusion fields: {', '.join(missing_fields)}")

    rows = read_csv(roster_path)
    if limit:
        rows = rows[:limit]

    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        contact_id, resolution = resolve_contact_id(location_id, token, row)
        entry: dict[str, Any] = {
            "row": index,
            "client_name": row.get("client_name", ""),
            "email": row.get("email", ""),
            "contact_id": contact_id,
            "resolution": resolution,
        }
        if not contact_id:
            entry["action"] = "skipped"
            entry["reason"] = "contact_not_resolved"
            results.append(entry)
            continue

        custom_fields = custom_field_payload(row, fields, sync_date)
        entry["field_count"] = len(custom_fields)
        if not approved_live_sync:
            entry["action"] = "dry_run"
            results.append(entry)
            continue

        status, payload = update_contact(contact_id, token, custom_fields)
        entry["status"] = status
        if 200 <= status < 300:
            entry["action"] = "updated"
        else:
            entry["action"] = "failed"
            entry["error"] = payload
        results.append(entry)

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "location_id": location_id,
        "roster": str(roster_path),
        "sync_date": sync_date,
        "approved_live_sync": approved_live_sync,
        "total_rows": len(rows),
        "updated": sum(1 for item in results if item.get("action") == "updated"),
        "dry_run": sum(1 for item in results if item.get("action") == "dry_run"),
        "skipped": sum(1 for item in results if item.get("action") == "skipped"),
        "failed": sum(1 for item in results if item.get("action") == "failed"),
        "results": results,
    }
    write_json(output_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location-id", default="", help="HighLevel sub-account/location ID.")
    parser.add_argument("--roster", type=Path, default=None, help="Client billing roster CSV.")
    parser.add_argument("--output", type=Path, default=None, help="Sync receipt JSON path.")
    parser.add_argument("--approved-live-sync", action="store_true", help="Actually update HighLevel contacts.")
    parser.add_argument("--import-csv", type=Path, default=None, help="Write an import-ready HighLevel CSV instead of calling contact APIs.")
    parser.add_argument("--write-import-csv", action="store_true", help="Write the standard create/update HighLevel import CSV.")
    parser.add_argument("--drive-paths", action="store_true", help="Use the shared Google Drive ScoreFusion dashboard folder for inputs and outputs.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N roster rows.")
    parser.add_argument("--sync-date", default=date.today().isoformat(), help="Value for SF_Last_DisputeFox_Sync.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup.load_env_file()
    location_id = args.location_id or setup.env_location_id()
    if not location_id:
        raise SystemExit("Missing location ID. Pass --location-id or set CREDIT_TRACKER_LOCATION_ID.")
    roster_path = args.roster or default_roster_path(args.drive_paths)
    output_path = args.output or default_output_path(args.drive_paths)
    import_csv_path = args.import_csv or (default_import_csv_path(args.drive_paths) if args.write_import_csv else None)
    if import_csv_path:
        result = write_import_csv(roster_path, import_csv_path, args.sync_date)
        print("HighLevel ScoreFusion import CSV generated.")
        print(f"- rows: {result['rows']}")
        print(f"- output: {result['path']}")
        return
    summary = sync_roster(
        location_id=location_id,
        roster_path=roster_path,
        output_path=output_path,
        approved_live_sync=args.approved_live_sync,
        limit=max(args.limit, 0),
        sync_date=args.sync_date,
    )
    print(f"HighLevel ScoreFusion sync complete for location {location_id}.")
    print(f"- updated: {summary['updated']}")
    print(f"- dry_run: {summary['dry_run']}")
    print(f"- skipped: {summary['skipped']}")
    print(f"- failed: {summary['failed']}")
    print(f"- output: {output_path}")


if __name__ == "__main__":
    main()
