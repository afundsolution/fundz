#!/usr/bin/env python3
"""Build ScoreFusion billing dashboard exports from local DisputeFox files."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DISPUTE_FOX_DIR = ROOT / "data" / "dispute-fox"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "local" / "scorefusion-billing-dashboard"

ACTIVE_PATTERNS = (
    "disputefox-active-clients-full-*.csv",
    "*active-clients-full*.csv",
    "disputefox-active-clients-*.csv",
    "*active-clients*.csv",
)
BILLING_PATTERNS = (
    "*scorefusion*billing*failed*payments*.csv",
    "*invoice*due*.csv",
    "*future*billing*.csv",
    "*billing*report*.csv",
    "*billing*.csv",
)

ROSTER_FIELDS = [
    "client_name",
    "email",
    "phone",
    "highlevel_contact_id",
    "disputefox_customer_id",
    "disputefox_customer_url",
    "enrollment_date",
    "next_charge_date",
    "amount_due",
    "billing_status",
    "highlevel_pipeline_stage",
    "last_warning_sent_date",
    "last_charge_date",
    "notes_owner_action",
]

IMPORT_LOG_FIELDS = [
    "export_filename",
    "export_type",
    "import_date",
    "row_count",
    "matched_contacts",
    "unmatched_contacts",
    "total_imported_amount_due",
]

EXCEPTION_FIELDS = ["exception_type", "client_name", "email", "amount_due", "details"]
BILLING_RISK_FIELDS = [
    "risk_level",
    "client_name",
    "email",
    "amount_due",
    "billing_status",
    "pipeline_stage",
    "next_charge_date",
    "recommended_action",
]
BILLING_RISK_REVIEW_FIELDS = [
    "risk_level",
    "review_bucket",
    "rollout_treatment",
    "client_name",
    "email",
    "amount_due",
    "row_count",
    "duplicate_row_count",
    "billing_statuses",
    "failure_types",
    "pipeline_stage",
    "next_charge_date",
    "recommended_action",
]

FAILED_PAYMENT_EXPORT_FIELDS = [
    "client_name",
    "email",
    "disputefox_customer_id",
    "disputefox_customer_url",
    "status",
    "type",
    "payment_status",
    "payment_date",
    "due_on",
    "price",
    "total_paid",
    "commission",
    "amount_due",
    "billing_status",
    "source_failure_bucket",
    "source_page",
]

FAILED_PAYMENT_ROW_RE = re.compile(
    r"(?P<name_email>.*?)(?P<status>Active|Archived|Deleted|Pause|-)(?P<type>Client|Lead)\n"
    r"(?P<payment>(?:Failed|Paid)\s+\d{1,2}/\d{1,2}|N/A)\n"
    r"(?P<due_on>N/A|Today|Yesterday|Tomorrow|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2})\n"
    r"(?P<price>\$[\d,.]+)(?P<total_paid>\$[\d,.]+)(?P<commission>\$[\d,.]+)MessageEmail",
    re.S,
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Live summary must be a JSON object: {path}")
    return data


def latest_matching_file(source_dir: Path, patterns: tuple[str, ...]) -> Path | None:
    for pattern in patterns:
        matches = [path for path in source_dir.glob(pattern) if path.is_file()]
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)
    return None


def normalize_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def normalize_name(name: str) -> str:
    text = re.sub(r"\s*\*\s*new\b", "", (name or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def value(row: dict[str, str], *names: str) -> str:
    lookup = {normalize_header(str(key)): str(val).strip() for key, val in row.items()}
    for name in names:
        raw = lookup.get(normalize_header(name))
        if raw not in (None, ""):
            return raw
    return ""


def parse_money(text: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", text or "")
    if cleaned in ("", "-", ".", "-."):
        return 0.0
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return 0.0


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_date(day: date | None) -> str:
    return day.isoformat() if day else ""


def next_monthly_charge(enrollment_date: date | None, today: date) -> date | None:
    if enrollment_date is None:
        return None
    year = today.year
    month = today.month
    candidate = monthly_charge_for(year, month, enrollment_date.day)
    if candidate < today:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        candidate = monthly_charge_for(year, month, enrollment_date.day)
    return candidate


def monthly_charge_for(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def amount_from_billing_row(row: dict[str, str]) -> float:
    return parse_money(
        value(
            row,
            "amount_due",
            "total_paid",
            "balance_due",
            "invoice_due",
            "invoice_amount",
            "future_billing_amount",
            "amount",
            "balance",
            "total",
            "billing",
        )
    )


def raw_failed_payment_export_name(today: date) -> str:
    return f"disputefox-scorefusion-billing-failed-payments-{today:%Y%m%d}.csv"


def parse_failed_payment_pages(
    raw_dir: Path,
    known_emails: set[str] | None = None,
    known_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    known_emails = {email.lower() for email in (known_emails or set()) if email}
    known_names = known_names or {}
    rows: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.txt")):
        if path.name == "current-page.txt":
            continue
        page_text = path.read_text(encoding="utf-8", errors="replace").replace("\xa0", " ")
        table_text = failed_payment_table_text(page_text)
        bucket = failure_bucket_from_path(path)
        for match in FAILED_PAYMENT_ROW_RE.finditer(table_text):
            name, email = split_name_email(match.group("name_email"), known_emails, known_names)
            payment_status, payment_date = split_payment(match.group("payment"))
            amount_due = parse_money(match.group("price"))
            billing_status = f"{bucket}: {match.group('payment')} due {match.group('due_on')}"
            rows.append(
                {
                    "client_name": name,
                    "email": email.lower(),
                    "disputefox_customer_id": "",
                    "disputefox_customer_url": "",
                    "status": normalize_disputefox_status(match.group("status")),
                    "type": match.group("type"),
                    "payment_status": payment_status,
                    "payment_date": payment_date,
                    "due_on": match.group("due_on"),
                    "price": f"{parse_money(match.group('price')):.2f}",
                    "total_paid": f"{parse_money(match.group('total_paid')):.2f}",
                    "commission": f"{parse_money(match.group('commission')):.2f}",
                    "amount_due": f"{amount_due:.2f}",
                    "billing_status": billing_status,
                    "source_failure_bucket": bucket,
                    "source_page": path.name,
                }
            )
    return rows


def failed_payment_table_text(page_text: str) -> str:
    marker = 'button above\n'
    if marker in page_text:
        return page_text.split(marker, 1)[1]
    return page_text


def failure_bucket_from_path(path: Path) -> str:
    name = path.name.lower()
    if "low-credit" in name or "low_credits" in name or "no-credit" in name:
        return "Low Credits Failure"
    return "Client Card Failure"


def split_payment(payment: str) -> tuple[str, str]:
    parts = payment.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def normalize_disputefox_status(status: str) -> str:
    return "" if status == "-" else status


def split_name_email(name_email: str, known_emails: set[str], known_names: dict[str, str] | None = None) -> tuple[str, str]:
    compact = re.sub(r"\s+", " ", (name_email or "").strip())
    lower = compact.lower()
    for email in sorted(known_emails, key=len, reverse=True):
        if lower.endswith(email):
            return clean_disputefox_name(compact[: -len(email)]), compact[-len(email) :]
    known_split = split_after_known_name(compact, known_names or {})
    if known_split:
        return known_split

    candidates: list[tuple[int, int, str, str]] = []
    at_index = compact.find("@")
    if at_index == -1:
        return clean_disputefox_name(compact), ""

    for start in range(0, at_index + 1):
        candidate = compact[start:]
        if EMAIL_RE.fullmatch(candidate) is None:
            continue
        name = clean_disputefox_name(compact[:start])
        if not name:
            continue
        local = candidate.split("@", 1)[0]
        score = split_candidate_score(name, local)
        candidates.append((score, len(local), name, candidate))

    if not candidates:
        found = EMAIL_RE.search(compact)
        if not found:
            return clean_disputefox_name(compact), ""
        return clean_disputefox_name(compact[: found.start()]), found.group(0)

    _, _, name, email = max(candidates, key=lambda item: (item[0], item[1]))
    return name, email


def split_after_known_name(text: str, known_names: dict[str, str]) -> tuple[str, str] | None:
    for key, display_name in sorted(known_names.items(), key=lambda item: len(item[0]), reverse=True):
        split_index = split_index_after_normalized_prefix(text, key)
        if split_index is None:
            continue
        email = text[split_index:].strip()
        email = re.sub(r"^\*New\*", "", email, flags=re.I)
        if EMAIL_RE.fullmatch(email):
            return display_name, email
    return None


def split_index_after_normalized_prefix(text: str, normalized_prefix: str) -> int | None:
    consumed = 0
    for index, char in enumerate(text):
        if not char.isalnum():
            continue
        if consumed >= len(normalized_prefix):
            return index
        if char.lower() != normalized_prefix[consumed]:
            return None
        consumed += 1
        if consumed == len(normalized_prefix):
            return index + 1
    return len(text) if consumed == len(normalized_prefix) else None


def compact_name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def split_candidate_score(name: str, local_part: str) -> int:
    words = normalize_name(name).split()
    local = (local_part or "").lower()
    score = min(len(words), 3) * 12
    if len(words) >= 2:
        score += 20
    if words:
        compact_words = "".join(words)
        expected_locals = {words[0], words[-1], compact_words}
        if len(words[-1]) > 1:
            expected_locals.add(f"{words[0][:1]}{words[-1]}")
        if local in expected_locals:
            score += 60
    if len(local_part) < 5:
        score -= 25
    if local_part[:1].isdigit():
        score -= 25
    if local_part.isdigit():
        score -= 25
    if re.search(r"[\d_\-.]$", name):
        score -= 35
    if re.search(r"[a-z][A-Z]$", name):
        score -= 10
    if words and len(words[-1]) < 2:
        score -= 20
    if words and len(words[-1]) == 2:
        score -= 40
    if any(char.isdigit() for char in local_part):
        score += 2
    if any(char in local_part for char in "._-+"):
        score += 2
    return score


def clean_disputefox_name(name: str) -> str:
    text = re.sub(r"\*New\*", "", name or "", flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def write_failed_payment_export(path: Path, rows: list[dict[str, Any]]) -> None:
    write_csv(path, rows, FAILED_PAYMENT_EXPORT_FIELDS)


def export_type(path: Path | None) -> str:
    if path is None:
        return "None"
    name = path.name.lower()
    if "invoice" in name and "due" in name:
        return "Invoice Due"
    if "future" in name and "billing" in name:
        return "Future Billing"
    if "billing" in name:
        return "Billing"
    return "Unknown"


@dataclass
class BillingMatch:
    row: dict[str, str]
    key: str
    amount_due: float
    billing_status: str


def build_billing_indexes(rows: list[dict[str, str]]) -> tuple[dict[str, BillingMatch], dict[str, BillingMatch], list[dict[str, Any]]]:
    by_email: dict[str, BillingMatch] = {}
    by_name: dict[str, BillingMatch] = {}
    exceptions: list[dict[str, Any]] = []

    for row in rows:
        name = value(row, "client_name", "customer_name", "name", "full_name")
        email = value(row, "email", "customer_email", "client_email").lower()
        amount_due = amount_from_billing_row(row)
        status = value(row, "billing_status", "payment_status", "invoice_status", "status")
        match = BillingMatch(row=row, key=email or normalize_name(name), amount_due=amount_due, billing_status=status)

        if email:
            if email in by_email:
                exceptions.append(exception("amount_conflict", name, email, amount_due, "Duplicate billing export rows share the same email."))
            by_email[email] = match
        if name:
            normalized = normalize_name(name)
            if normalized in by_name and not email:
                exceptions.append(exception("amount_conflict", name, email, amount_due, "Duplicate billing export rows share the same client name."))
            by_name[normalized] = match
        if not name and not email:
            exceptions.append(exception("missing_email_name_match", "", "", amount_due, "Billing row has no usable name or email."))
    return by_email, by_name, exceptions


def exception(kind: str, name: str, email: str, amount_due: float | str, details: str) -> dict[str, Any]:
    return {
        "exception_type": kind,
        "client_name": name,
        "email": email,
        "amount_due": amount_due,
        "details": details,
    }


def highlevel_stage(status: str, amount_due: float) -> str:
    lower = (status or "").lower()
    if any(term in lower for term in ("cancel", "inactive", "archive")):
        return "Cancelled"
    if amount_due > 0 or any(term in lower for term in ("fail", "dunning", "past due", "overdue")):
        return "At Risk"
    return "Enrolled"


def is_failed_payment_export(rows: list[dict[str, str]]) -> bool:
    return any(value(row, "source_failure_bucket") for row in rows)


def active_lookups(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_email: dict[str, dict[str, str]] = {}
    by_name: dict[str, dict[str, str]] = {}
    for row in rows:
        email = value(row, "email", "customer_email", "client_email").lower()
        name = value(row, "client_name", "customer_name", "name", "full_name")
        if email:
            by_email[email] = row
        normalized = normalize_name(name)
        if normalized:
            by_name[normalized] = row
    return by_email, by_name


def build_failed_payment_roster(
    active_rows: list[dict[str, str]],
    billing_rows: list[dict[str, str]],
    today: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    active_by_email, active_by_name = active_lookups(active_rows)
    roster: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    matched_keys: set[str] = set()

    for index, row in enumerate(billing_rows, start=1):
        name = value(row, "client_name", "customer_name", "name", "full_name")
        email = value(row, "email", "customer_email", "client_email").lower()
        active_row = active_by_email.get(email) if email else None
        if active_row is None:
            active_row = active_by_name.get(normalize_name(name))

        amount_due = amount_from_billing_row(row)
        billing_status = value(row, "billing_status", "payment_status", "invoice_status", "status")
        enrollment_date = parse_date(value(active_row or {}, "started", "enrollment_date", "sf_enrollment_date", "created_at"))
        next_charge_date = next_monthly_charge(enrollment_date, today)
        stage = "At Risk" if value(row, "source_failure_bucket") else highlevel_stage(billing_status, amount_due)

        if active_row:
            matched_keys.add(email or normalize_name(name) or f"row-{index}")
        else:
            exceptions.append(
                exception(
                    "disputefox_client_missing_from_highlevel",
                    name,
                    email,
                    f"{amount_due:.2f}",
                    "DisputeFox failed-payment row did not match the active-client export.",
                )
            )

        roster.append(
            {
                "client_name": name,
                "email": email,
                "phone": value(active_row or {}, "phone", "mobile", "sent_to"),
                "highlevel_contact_id": "",
                "disputefox_customer_id": value(row, "disputefox_customer_id", "customer_id", "client_id", "id"),
                "disputefox_customer_url": value(row, "disputefox_customer_url", "customer_url", "url", "link"),
                "enrollment_date": format_date(enrollment_date),
                "next_charge_date": format_date(next_charge_date),
                "amount_due": f"{amount_due:.2f}",
                "billing_status": billing_status,
                "highlevel_pipeline_stage": stage,
                "last_warning_sent_date": "",
                "last_charge_date": "",
                "notes_owner_action": owner_action(stage, amount_due, billing_status),
            }
        )
    return roster, exceptions, matched_keys


def warning_due_count(active_rows: list[dict[str, str]], today: date) -> int:
    count = 0
    for row in active_rows:
        enrollment_date = parse_date(value(row, "started", "enrollment_date", "sf_enrollment_date", "created_at"))
        next_charge_date = next_monthly_charge(enrollment_date, today)
        if next_charge_date and (next_charge_date - today).days in (3, 4, 5):
            count += 1
    return count


def build_dashboard(
    source_dir: Path = DISPUTE_FOX_DIR,
    today: date | None = None,
    billing_export: Path | None = None,
    live_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    live_summary = live_summary or {}
    active_export = latest_matching_file(source_dir, ACTIVE_PATTERNS)
    active_rows = read_csv(active_export)

    if billing_export is None:
        billing_export = latest_matching_file(source_dir, BILLING_PATTERNS)
        if billing_export and active_export and billing_export.resolve() == active_export.resolve():
            billing_export = None
    billing_rows = read_csv(billing_export)
    failed_payment_export = is_failed_payment_export(billing_rows)
    if failed_payment_export:
        roster, exceptions, matched_keys = build_failed_payment_roster(active_rows, billing_rows, today)
    else:
        by_email, by_name, exceptions = build_billing_indexes(billing_rows)

        matched_keys: set[str] = set()
        roster = []
        for row in active_rows:
            name = value(row, "client_name", "customer_name", "name", "full_name")
            email = value(row, "email", "customer_email", "client_email").lower()
            enrollment_date = parse_date(value(row, "started", "enrollment_date", "sf_enrollment_date", "created_at"))
            next_charge_date = next_monthly_charge(enrollment_date, today)
            billing_match = by_email.get(email) if email else None
            if billing_match is None:
                billing_match = by_name.get(normalize_name(name))
            amount_due = billing_match.amount_due if billing_match else 0.0
            billing_status = billing_match.billing_status if billing_match else value(row, "billing")
            if billing_match:
                matched_keys.add(billing_match.key)

            stage = highlevel_stage(billing_status or value(row, "status"), amount_due)
            roster.append(
                {
                    "client_name": name,
                    "email": email,
                    "phone": value(row, "phone", "mobile", "sent_to"),
                    "highlevel_contact_id": "",
                    "disputefox_customer_id": value(row, "customer_id", "client_id", "id"),
                    "disputefox_customer_url": value(row, "customer_url", "url", "link"),
                    "enrollment_date": format_date(enrollment_date),
                    "next_charge_date": format_date(next_charge_date),
                    "amount_due": f"{amount_due:.2f}" if amount_due else "",
                    "billing_status": billing_status,
                    "highlevel_pipeline_stage": stage,
                    "last_warning_sent_date": "",
                    "last_charge_date": "",
                    "notes_owner_action": owner_action(stage, amount_due, billing_status),
                }
            )

        active_emails = {value(row, "email", "customer_email", "client_email").lower() for row in active_rows}
        active_names = {normalize_name(value(row, "client_name", "customer_name", "name", "full_name")) for row in active_rows}
        for row in billing_rows:
            name = value(row, "client_name", "customer_name", "name", "full_name")
            email = value(row, "email", "customer_email", "client_email").lower()
            amount_due = amount_from_billing_row(row)
            if (email and email not in active_emails) or (not email and normalize_name(name) not in active_names):
                exceptions.append(exception("disputefox_client_missing_from_highlevel", name, email, amount_due, "Billing export row did not match the active-client export."))

    if not billing_rows and not live_summary:
        exceptions.append(exception("missing_billing_export", "", "", "", "No DisputeFox Invoice Due or Future Billing export was found; exact amounts are blank."))
    elif not billing_rows and live_summary:
        exceptions.append(
            exception(
                "client_level_billing_export_needed",
                "",
                "",
                live_summary.get("failed_invoices_total", ""),
                "Exact DisputeFox dashboard totals were captured live, but a row-level Invoice Due or Future Billing export is still needed for per-client amount matching.",
            )
        )

    warning_due = warning_due_count(active_rows, today) if is_failed_payment_export(billing_rows) else sum(1 for item in roster if days_until(item["next_charge_date"], today) in (3, 4, 5))
    owed_payment_count = len(billing_rows) if is_failed_payment_export(billing_rows) else sum(1 for item in roster if parse_money(str(item["amount_due"])) > 0)
    roster_amount_total = round(sum(parse_money(str(item["amount_due"])) for item in roster), 2)
    total_amount_due = roster_amount_total
    failed_at_risk = sum(1 for item in roster if item["highlevel_pipeline_stage"] == "At Risk")
    warning_sent = sum(1 for item in roster if item["highlevel_pipeline_stage"] == "Warning Sent")
    enrolled_count = len(roster)

    if live_summary:
        enrolled_count = int(live_summary.get("active_clients") or enrolled_count)
        owed_payment_count = int(live_summary.get("failed_payment_count") or owed_payment_count)
        total_amount_due = parse_money(str(live_summary.get("failed_invoices_total") or total_amount_due))
        failed_at_risk = owed_payment_count

    missing_disputefox_rows = sum(
        1 for item in exceptions if item.get("exception_type") == "disputefox_client_missing_from_highlevel"
    )
    if failed_payment_export:
        matched_contact_count = max(0, len(billing_rows) - missing_disputefox_rows)
        unmatched_contact_count = missing_disputefox_rows
    else:
        matched_contact_count = len(matched_keys)
        unmatched_contact_count = max(0, len(billing_rows) - len(matched_keys))

    billing_risk_queue = build_billing_risk_queue(roster)
    billing_risk_review_queue = build_billing_risk_review_queue(billing_risk_queue, today=today)
    risk_dedupe = billing_risk_dedupe_summary(billing_risk_queue)
    dashboard_rows = [
        {"metric": "ScoreFusion Enrolled", "value": enrolled_count},
        {"metric": "Warnings Due", "value": warning_due},
        {"metric": "Warning Sent", "value": warning_sent},
        {"metric": "Owed Payments", "value": owed_payment_count},
        {"metric": "Total Amount Due", "value": f"{total_amount_due:.2f}"},
        {"metric": "Roster Current Failed Charges", "value": f"{roster_amount_total:.2f}"},
        {"metric": "Failed / At Risk", "value": failed_at_risk},
        {"metric": "Billing Risk Review Rows", "value": len(billing_risk_review_queue)},
        {"metric": "Billing Risk Unique Keys", "value": risk_dedupe["unique_keys"]},
        {"metric": "Billing Risk Duplicate Keys", "value": risk_dedupe["duplicate_keys"]},
        {"metric": "Billing Risk Rows In Duplicate Keys", "value": risk_dedupe["rows_in_duplicate_keys"]},
        {"metric": "Matched Failed-Payment Rows", "value": matched_contact_count},
        {"metric": "Exceptions Requiring Review", "value": unmatched_contact_count},
        {"metric": "Last DisputeFox Sync", "value": datetime.now().isoformat(timespec="seconds")},
        {"metric": "Billing Export Used", "value": str(billing_export.name if billing_export else "")},
    ]
    if live_summary:
        dashboard_rows.extend(live_dashboard_rows(live_summary))

    import_log_rows = [
        {
            "export_filename": str(billing_export.name if billing_export else live_summary.get("source", "")),
            "export_type": export_type(billing_export) if billing_export else ("Live DisputeFox Dashboard" if live_summary else "None"),
            "import_date": datetime.now().isoformat(timespec="seconds"),
            "row_count": len(billing_rows) or int(live_summary.get("failed_payment_count") or 0),
            "matched_contacts": matched_contact_count,
            "unmatched_contacts": unmatched_contact_count,
            "total_imported_amount_due": f"{roster_amount_total if billing_rows else total_amount_due:.2f}",
        }
    ]

    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "today": today.isoformat(),
            "active_export": str(active_export or ""),
            "billing_export": str(billing_export or ""),
            "live_summary_source": str(live_summary.get("source", "")),
            "policy": "Drive-ready reporting only. HighLevel updates require authorized HighLevel access.",
        },
        "dashboard": dashboard_rows,
        "roster": roster,
        "import_log": import_log_rows,
        "exceptions": exceptions,
        "billing_risk_queue": billing_risk_queue,
        "billing_risk_review_queue": billing_risk_review_queue,
        "billing_risk_summary": billing_risk_summary(billing_risk_queue),
        "billing_review_bucket_summary": billing_review_bucket_summary(billing_risk_review_queue),
    }


def live_dashboard_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    mappings = [
        ("Client Card Failures", "client_card_failures"),
        ("Low Credit Failures", "low_credit_failures"),
        ("Credits Available", "credits_available"),
        ("Total Commission Since Oct 2024", "total_commission"),
        ("May Commission", "may_commission"),
        ("Last Month Commission", "last_month_commission"),
        ("Last Month Failed Invoices", "last_month_failed_invoices"),
        ("May Credits Used", "may_credits_used"),
        ("Last Month Credits Used", "last_month_credits_used"),
        ("Credits Needed Forecast", "credits_needed_forecast"),
        ("New This Month", "new_this_month"),
        ("Last Month New Clients", "last_month_new_clients"),
        ("Paused Clients", "paused_clients"),
        ("Last Month Paused Clients", "last_month_paused_clients"),
    ]
    rows: list[dict[str, Any]] = []
    for label, key in mappings:
        if key in summary and summary[key] not in ("", None):
            value_to_write = summary[key]
            if isinstance(value_to_write, float):
                value_to_write = f"{value_to_write:.2f}"
            rows.append({"metric": label, "value": value_to_write})
    return rows


def days_until(iso_date: str, today: date) -> int | None:
    parsed = parse_date(iso_date)
    if parsed is None:
        return None
    return (parsed - today).days


def owner_action(stage: str, amount_due: float, billing_status: str) -> str:
    lower = (billing_status or "").lower()
    if stage == "Cancelled":
        return "Keep historical dates intact; remove from active monitoring."
    if amount_due > 0:
        return "Review amount due and confirm payment-warning or dunning action."
    if any(term in lower for term in ("fail", "dunning", "past due", "overdue")):
        return "Review failed-payment status before sending campaign follow-up."
    return "Monitor active ScoreFusion billing cycle."


def billing_risk_level(row: dict[str, Any]) -> str:
    amount = parse_money(str(row.get("amount_due") or "0"))
    status = str(row.get("billing_status") or "").lower()
    stage = str(row.get("highlevel_pipeline_stage") or "").lower()
    if amount >= 100 or any(term in status for term in ("failed", "past due", "overdue")):
        return "high"
    if amount > 0 or stage == "at risk":
        return "medium"
    if any(term in status for term in ("paid", "future")):
        return "low"
    return "monitor"


def build_billing_risk_queue(roster: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risk_order = {"high": 0, "medium": 1, "monitor": 2, "low": 3}
    rows = []
    for item in roster:
        level = billing_risk_level(item)
        if level == "low":
            continue
        rows.append(
            {
                "risk_level": level,
                "client_name": item.get("client_name", ""),
                "email": item.get("email", ""),
                "amount_due": item.get("amount_due", ""),
                "billing_status": item.get("billing_status", ""),
                "pipeline_stage": item.get("highlevel_pipeline_stage", ""),
                "next_charge_date": item.get("next_charge_date", ""),
                "recommended_action": item.get("notes_owner_action", ""),
            }
        )
    return sorted(rows, key=lambda row: (risk_order.get(str(row["risk_level"]), 9), -parse_money(str(row["amount_due"])), str(row["client_name"]).lower()))


def billing_risk_dedupe_summary(queue: list[dict[str, Any]]) -> dict[str, int]:
    groups: Counter[str] = Counter()
    for row in queue:
        key = str(row.get("email") or "").strip().lower()
        if not key:
            key = normalize_name(str(row.get("client_name") or ""))
        if key:
            groups[key] += 1
    duplicate_keys = [key for key, count in groups.items() if count > 1]
    return {
        "unique_keys": len(groups),
        "duplicate_keys": len(duplicate_keys),
        "rows_in_duplicate_keys": sum(groups[key] for key in duplicate_keys),
    }


def billing_risk_key(row: dict[str, Any]) -> str:
    key = str(row.get("email") or "").strip().lower()
    return key or normalize_name(str(row.get("client_name") or ""))


def days_until_charge(row: dict[str, Any], today: date) -> int | None:
    charge_date = parse_date(str(row.get("next_charge_date") or ""))
    if charge_date is None:
        return None
    return (charge_date - today).days


def billing_review_bucket(row: dict[str, Any], today: date) -> str:
    failure_types = str(row.get("failure_types") or "")
    days_until_next = days_until_charge(row, today)
    if days_until_next is not None and days_until_next <= 0:
        return "urgent_due_now_or_past_due"
    if "Client Card Failure" in failure_types and "Low Credits Failure" in failure_types:
        return "dual_failure_review"
    if days_until_next is not None and days_until_next <= 7:
        return "date_sensitive_next_7_days"
    if str(row.get("risk_level") or "") == "high":
        return "standard_high_risk_review"
    if not row.get("next_charge_date"):
        return "missing_charge_date_review"
    return "medium_monitor_review"


def billing_rollout_treatment(bucket: str) -> str:
    if bucket == "urgent_due_now_or_past_due":
        return "Owner review first; no automated billing warning until exact approval."
    if bucket == "dual_failure_review":
        return "Review once as a unique client/key; do not double-contact duplicate failure rows."
    if bucket == "date_sensitive_next_7_days":
        return "Prioritize for human decision before the next charge date."
    if bucket == "missing_charge_date_review":
        return "Fix or verify billing data before any billing-warning workflow change."
    if bucket == "standard_high_risk_review":
        return "Keep in high-risk review queue; require approval before outreach."
    return "Monitor after high-risk rows; no rollout action yet."


def build_billing_risk_review_queue(queue: list[dict[str, Any]], today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    risk_order = {"high": 0, "medium": 1, "monitor": 2, "low": 3}
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in queue:
        key = billing_risk_key(row)
        if not key:
            continue
        groups.setdefault(key, []).append(row)

    rows: list[dict[str, Any]] = []
    for group_rows in groups.values():
        best_risk = min((str(row.get("risk_level") or "monitor") for row in group_rows), key=lambda level: risk_order.get(level, 9))
        amounts = [parse_money(str(row.get("amount_due") or "0")) for row in group_rows]
        statuses = list(dict.fromkeys(str(row.get("billing_status") or "").strip() for row in group_rows if row.get("billing_status")))
        failure_types = list(dict.fromkeys(status.split(":", 1)[0] for status in statuses if status))
        dates = sorted(str(row.get("next_charge_date") or "").strip() for row in group_rows if row.get("next_charge_date"))
        first = group_rows[0]
        row_count = len(group_rows)
        review_row = {
            "risk_level": best_risk,
            "client_name": first.get("client_name", ""),
            "email": first.get("email", ""),
            "amount_due": f"{max(amounts or [0.0]):.2f}",
            "row_count": row_count,
            "duplicate_row_count": max(0, row_count - 1),
            "billing_statuses": "; ".join(statuses),
            "failure_types": "; ".join(failure_types),
            "pipeline_stage": first.get("pipeline_stage", ""),
            "next_charge_date": dates[0] if dates else "",
            "recommended_action": "Review this unique billing-risk client once before any billing-warning workflow change.",
        }
        bucket = billing_review_bucket(review_row, today)
        review_row["review_bucket"] = bucket
        review_row["rollout_treatment"] = billing_rollout_treatment(bucket)
        rows.append(review_row)
    bucket_order = {
        "urgent_due_now_or_past_due": 0,
        "dual_failure_review": 1,
        "date_sensitive_next_7_days": 2,
        "standard_high_risk_review": 3,
        "missing_charge_date_review": 4,
        "medium_monitor_review": 5,
    }
    return sorted(
        rows,
        key=lambda row: (
            bucket_order.get(str(row.get("review_bucket") or ""), 9),
            risk_order.get(str(row["risk_level"]), 9),
            -parse_money(str(row["amount_due"])),
            str(row["client_name"]).lower(),
        ),
    )


def billing_risk_summary(queue: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {level: 0 for level in ("high", "medium", "monitor")}
    total = 0.0
    for row in queue:
        level = str(row.get("risk_level") or "monitor")
        counts[level] = counts.get(level, 0) + 1
        total += parse_money(str(row.get("amount_due") or "0"))
    return {"counts": counts, "total_amount_due": f"{total:.2f}", "queue_count": len(queue), **billing_risk_dedupe_summary(queue)}


def billing_review_bucket_summary(review_queue: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("review_bucket") or "unknown") for row in review_queue)
    return dict(sorted(counts.items()))


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def write_billing_risk_review_packet(path: Path, data: dict[str, Any]) -> None:
    review_rows = data.get("billing_risk_review_queue", [])
    summary = data.get("billing_risk_summary", {})
    risk_counts = Counter(str(row.get("risk_level") or "unknown") for row in review_rows)
    duplicate_rows = [row for row in review_rows if int(row.get("duplicate_row_count") or 0) > 0]
    dual_failure_rows = [row for row in review_rows if "Client Card Failure" in str(row.get("failure_types")) and "Low Credits Failure" in str(row.get("failure_types"))]
    dated_rows = [row for row in review_rows if row.get("next_charge_date")]
    lines = [
        "# ScoreFusion Billing Risk Review Packet",
        "",
        f"Generated: {data.get('metadata', {}).get('generated_at', '')}",
        "",
        "Use this before any billing-warning workflow change. It is a review packet only; it does not approve or send messages.",
        "",
        "## Summary",
        f"- Raw risk rows: {summary.get('queue_count', 0)}",
        f"- Unique review rows: {len(review_rows)}",
        f"- High risk: {risk_counts.get('high', 0)}",
        f"- Medium risk: {risk_counts.get('medium', 0)}",
        f"- Duplicate failure keys: {summary.get('duplicate_keys', 0)}",
        f"- Rows with both card and low-credit failures: {len(dual_failure_rows)}",
        f"- Rows with next charge date: {len(dated_rows)}",
        "",
        "## Business Review Buckets",
    ]
    for bucket, count in data.get("billing_review_bucket_summary", {}).items():
        lines.append(f"- {bucket}: {count}")
    lines.extend(
        [
            "",
            "## Controlled Rollout Decision",
            "- Allowed now: review, dedupe, and preview-only rollout packets.",
            "- Blocked now: billing-warning live sends, broad campaign assignment, and duplicate-contact outreach.",
            "- Next approval gate: one named client/key, exact channel, exact message/campaign, and action-time approval.",
            "",
        ]
    )
    lines.extend([
        "## Operating Rule",
        "- Review one unique client/key once before any billing-warning workflow change.",
        "- Treat duplicate failure rows as evidence to review, not as extra people to contact.",
        "- Do not send billing-warning messages from this packet without Brandon's action-time approval.",
        "",
        "## Top Review Rows",
        "| Bucket | Risk | Client | Amount | Rows | Failure types | Next charge | Rollout treatment |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ])
    for row in review_rows[:40]:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "review_bucket",
                    "risk_level",
                    "client_name",
                    "amount_due",
                    "row_count",
                    "failure_types",
                    "next_charge_date",
                    "rollout_treatment",
                )
            )
            + " |"
        )
    if len(review_rows) > 40:
        lines.append(f"- Plus {len(review_rows) - 40} more rows in `billing-risk-review-queue.csv`.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(output_dir: Path, data: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "dashboard": output_dir / "dashboard.csv",
        "roster": output_dir / "client-billing-roster.csv",
        "import_log": output_dir / "disputefox-import-log.csv",
        "exceptions": output_dir / "exceptions.csv",
        "billing_risk_queue": output_dir / "billing-risk-queue.csv",
        "billing_risk_review_queue": output_dir / "billing-risk-review-queue.csv",
        "billing_risk_review_packet": output_dir / "billing-risk-review-packet.md",
        "json": output_dir / "scorefusion-billing-dashboard.json",
    }
    write_csv(files["dashboard"], data["dashboard"], ["metric", "value"])
    write_csv(files["roster"], data["roster"], ROSTER_FIELDS)
    write_csv(files["import_log"], data["import_log"], IMPORT_LOG_FIELDS)
    write_csv(files["exceptions"], data["exceptions"], EXCEPTION_FIELDS)
    write_csv(files["billing_risk_queue"], data.get("billing_risk_queue", []), BILLING_RISK_FIELDS)
    write_csv(files["billing_risk_review_queue"], data.get("billing_risk_review_queue", []), BILLING_RISK_REVIEW_FIELDS)
    write_billing_risk_review_packet(files["billing_risk_review_packet"], data)
    write_json(files["json"], data)
    return {name: str(path) for name, path in files.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ScoreFusion billing dashboard files for Google Drive and HighLevel review.")
    parser.add_argument("--source-dir", type=Path, default=DISPUTE_FOX_DIR, help="Folder containing DisputeFox CSV exports.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder for generated dashboard files.")
    parser.add_argument("--billing-export", type=Path, default=None, help="Explicit Invoice Due or Future Billing CSV export.")
    parser.add_argument("--raw-failed-payments-dir", type=Path, default=None, help="Folder containing copied DisputeFox failed-payment page text files.")
    parser.add_argument("--raw-billing-output", type=Path, default=None, help="CSV path for the parsed failed-payment billing export.")
    parser.add_argument("--live-summary", type=Path, default=None, help="JSON snapshot from the live DisputeFox ScoreFusion dashboard.")
    parser.add_argument("--today", default=date.today().isoformat(), help="Dashboard date in YYYY-MM-DD format.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date()
    billing_export = args.billing_export
    if args.raw_failed_payments_dir:
        active_export = latest_matching_file(args.source_dir, ACTIVE_PATTERNS)
        active_rows = read_csv(active_export)
        known_emails = {value(row, "email", "customer_email", "client_email").lower() for row in active_rows}
        known_names = {
            compact_name_key(value(row, "client_name", "customer_name", "name", "full_name")): value(row, "client_name", "customer_name", "name", "full_name")
            for row in active_rows
            if value(row, "client_name", "customer_name", "name", "full_name")
        }
        failed_payment_rows = parse_failed_payment_pages(args.raw_failed_payments_dir, known_emails=known_emails, known_names=known_names)
        billing_export = args.raw_billing_output or (args.source_dir / raw_failed_payment_export_name(today))
        write_failed_payment_export(billing_export, failed_payment_rows)
        print(f"Parsed DisputeFox failed-payment rows: {len(failed_payment_rows)}")
    data = build_dashboard(args.source_dir, today=today, billing_export=billing_export, live_summary=read_json(args.live_summary))
    files = write_outputs(args.output_dir, data)
    print("ScoreFusion billing dashboard generated.")
    for name, path in files.items():
        print(f"- {name}: {path}")
    print(f"- enrolled: {data['dashboard'][0]['value']}")
    print(f"- total amount due: {data['dashboard'][4]['value']}")
    print(f"- exceptions: {len(data['exceptions'])}")


if __name__ == "__main__":
    main()
