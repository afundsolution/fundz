#!/usr/bin/env python3
"""Build a narrow business-message queue from the local Mac Messages database.

This intentionally does not export a full personal message archive. A row is
eligible only when it matches a known client name, a known client phone number,
or an approved business keyword.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"
DEFAULT_MESSAGES_DB = Path.home() / "Library" / "Messages" / "chat.db"
DEFAULT_OUTPUT = OUTPUT_DIR / "fundz-personal-phone-message-queue.csv"
DEFAULT_SUMMARY = OUTPUT_DIR / "fundz-personal-phone-message-queue-summary.md"

BUSINESS_KEYWORDS = [
    "credit",
    "dispute",
    "report",
    "payment",
    "login",
    "app",
    "score",
    "round",
    "delete",
    "collection",
    "tradeline",
    "invoice",
    "refund",
    "cancel",
]

SECURITY_CODE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bverification code\b",
        r"\bsecurity code\b",
        r"\bone[-\s]?time code\b",
        r"\brequests this code\b",
        r"\buse code\b",
        r"\b2fa\b",
        r"\bpasscode\b",
    )
]
SHORT_CODE_RE = re.compile(r"^\d{3,6}$")

CLIENT_SOURCES = [
    ROOT / "data" / "local" / "command-center" / "fundz-client-communication-control-board.csv",
    ROOT / "data" / "local" / "command-center" / "fundz-work-queue.csv",
    ROOT / "data" / "local" / "command-center" / "fundz-contact-ledger.csv",
    ROOT / "data" / "local" / "command-center" / "fundz-approved-app-email-send-roster-20260505.csv",
    ROOT / "data" / "local" / "command-center" / "fundz-download-mobile-app-sequence-roster-20260505.csv",
    ROOT / "data" / "local" / "fundz-client-state-summary.csv",
    ROOT / "data" / "local" / "fundz-client-index.json",
    ROOT / "data" / "dispute-fox" / "disputefox-sms-report-20260502.csv",
]

QUEUE_FIELDS = [
    "contact",
    "phone",
    "last_message",
    "date",
    "direction",
    "needs_reply",
    "owner",
    "status",
    "next_step",
    "source",
]

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ClientDirectory:
    names: frozenset[str]
    display_names: dict[str, str]
    phones: dict[str, str]


def normalize_name(value: str) -> str:
    cleaned = re.sub(r"\*new\b", "", value or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def display_phone(value: str) -> str:
    digits = normalize_phone(value)
    if len(digits) == 10:
        return f"+1{digits}"
    return value or ""


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return BUSINESS_KEYWORDS
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def add_client(
    names: dict[str, str],
    phones: dict[str, str],
    client_name: str,
    phone: str = "",
) -> None:
    normalized = normalize_name(client_name)
    if normalized and len(normalized.split()) >= 2:
        names.setdefault(normalized, client_name.strip())
    normalized_phone = normalize_phone(phone)
    if normalized_phone and len(normalized_phone) >= 10 and normalized:
        phones.setdefault(normalized_phone[-10:], names.get(normalized, client_name.strip()))


def load_client_directory(paths: Iterable[Path] | None = None) -> ClientDirectory:
    paths = paths or CLIENT_SOURCES
    names: dict[str, str] = {}
    phones: dict[str, str] = {}

    for path in paths:
        if not path.exists():
            continue
        if path.suffix.lower() == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
            rows = loaded.get("clients", loaded) if isinstance(loaded, dict) else loaded
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        add_client(
                            names,
                            phones,
                            str(row.get("client_name") or row.get("name") or row.get("fullName") or ""),
                            str(row.get("phone") or row.get("sent_to") or ""),
                        )
            continue

        for row in read_csv_rows(path):
            client_name = (
                row.get("client_name")
                or row.get("customer_name")
                or row.get("name")
                or row.get("fullName")
                or ""
            )
            phone = row.get("phone") or row.get("sent_to") or row.get("client_phone") or ""
            add_client(names, phones, client_name, phone)

    return ClientDirectory(
        names=frozenset(names),
        display_names=names,
        phones=phones,
    )


def decode_message_text(text: Any, attributed_body: Any = None) -> str:
    if text:
        return str(text).replace("\x00", "").strip()
    if not attributed_body:
        return ""
    if isinstance(attributed_body, memoryview):
        attributed_body = attributed_body.tobytes()
    if isinstance(attributed_body, bytes):
        decoded = attributed_body.decode("utf-8", errors="ignore")
        chunks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s.,!?$@:/#&'\"()+-]{2,}", decoded)
        noise = {"NSString", "NSDictionary", "NSObject", "NSNumber", "NSColor", "NSFont"}
        chunks = [chunk.strip() for chunk in chunks if chunk.strip() not in noise]
        return " ".join(chunks).strip()
    return str(attributed_body).strip()


def apple_message_date(raw: Any) -> tuple[str, float]:
    if raw in (None, ""):
        return "", 0.0
    value = float(raw)
    seconds = value / 1_000_000_000 if value > 10_000_000_000 else value
    dt = APPLE_EPOCH.timestamp() + seconds
    return datetime.fromtimestamp(dt).astimezone().isoformat(timespec="seconds"), dt


def name_matches(text: str, directory: ClientDirectory) -> tuple[str, str] | tuple[None, None]:
    normalized_text = f" {normalize_name(text)} "
    for normalized_name in directory.names:
        if f" {normalized_name} " in normalized_text:
            return directory.display_names.get(normalized_name, normalized_name.title()), f"client_name:{normalized_name}"
    return None, None


def keyword_matches(text: str, keywords: list[str]) -> list[str]:
    lower = text.lower()
    matches = []
    for keyword in keywords:
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
        if re.search(pattern, lower):
            matches.append(keyword.lower())
    return matches


def looks_like_private_security_code(text: str, handle: str, matched_contact: str = "") -> bool:
    if matched_contact:
        return False
    normalized_handle = normalize_phone(handle)
    from_short_code = bool(SHORT_CODE_RE.fullmatch(normalized_handle or handle.strip()))
    if not from_short_code:
        return False
    return any(pattern.search(text or "") for pattern in SECURITY_CODE_PATTERNS)


def message_rows(messages_db: Path, max_messages: int) -> list[sqlite3.Row]:
    query = """
        SELECT
            message.ROWID AS message_id,
            message.date AS message_date,
            message.text AS text,
            message.attributedBody AS attributed_body,
            message.is_from_me AS is_from_me,
            message.service AS service,
            handle.id AS handle_id,
            chat.chat_identifier AS chat_identifier
        FROM message
        LEFT JOIN handle ON message.handle_id = handle.ROWID
        LEFT JOIN chat_message_join ON chat_message_join.message_id = message.ROWID
        LEFT JOIN chat ON chat.ROWID = chat_message_join.chat_id
        ORDER BY message.date DESC
        LIMIT ?
    """
    connection = sqlite3.connect(f"file:{messages_db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute(query, (max_messages,)))
    finally:
        connection.close()


def matched_queue_rows(
    rows: Iterable[sqlite3.Row],
    directory: ClientDirectory,
    keywords: list[str],
) -> list[dict[str, str]]:
    latest_by_contact: dict[str, dict[str, str]] = {}
    latest_ts: dict[str, float] = defaultdict(float)

    for row in rows:
        text = decode_message_text(row["text"], row["attributed_body"])
        if not text:
            continue

        handle = str(row["handle_id"] or row["chat_identifier"] or "")
        normalized_handle_phone = normalize_phone(handle)[-10:]
        matched_contact = ""
        match_reasons: list[str] = []

        if normalized_handle_phone and normalized_handle_phone in directory.phones:
            matched_contact = directory.phones[normalized_handle_phone]
            match_reasons.append("client_phone")

        name_contact, name_reason = name_matches(text, directory)
        if name_contact and name_reason:
            matched_contact = matched_contact or name_contact
            match_reasons.append(name_reason)

        if looks_like_private_security_code(text, handle, matched_contact):
            continue

        keyword_hits = keyword_matches(text, keywords)
        match_reasons.extend(f"keyword:{keyword}" for keyword in keyword_hits)

        if not match_reasons:
            continue

        date_text, timestamp = apple_message_date(row["message_date"])
        contact_key = normalize_name(matched_contact) or normalized_handle_phone or handle.lower()
        if latest_ts[contact_key] and timestamp <= latest_ts[contact_key]:
            continue

        inbound = not bool(row["is_from_me"])
        trusted_contact = bool(matched_contact)
        needs_reply = inbound and trusted_contact
        status = "Needs Reply" if needs_reply else "Review"
        phone = display_phone(handle) if normalized_handle_phone else handle
        contact = matched_contact or "Unknown business keyword match"
        source = "Mac Messages chat.db | " + ";".join(sorted(set(match_reasons)))
        next_step = (
            "Review and reply from the approved business channel; attach proof after response."
            if needs_reply
            else (
                "Verify this is a FUNDz client or business lead before any reply; keep out of shared systems unless approved."
                if inbound
                else "Review for business context; no reply needed unless Governor flags a follow-up gap."
            )
        )

        latest_ts[contact_key] = timestamp
        latest_by_contact[contact_key] = {
            "contact": contact,
            "phone": phone,
            "last_message": re.sub(r"\s+", " ", text).strip(),
            "date": date_text,
            "direction": "inbound" if inbound else "outbound",
            "needs_reply": "yes" if needs_reply else "no",
            "owner": "Brandon" if inbound else "FUNDz",
            "status": status,
            "next_step": next_step,
            "source": source,
        }

    return sorted(latest_by_contact.values(), key=lambda item: item["date"], reverse=True)


def write_dict_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_summary(path: Path, rows: list[dict[str, str]], keywords: list[str], max_messages: int) -> None:
    inbound = sum(1 for row in rows if row.get("direction") == "inbound")
    needs_reply = sum(1 for row in rows if row.get("needs_reply") == "yes")
    lines = [
        "# FUNDz Personal Phone Message Queue Summary",
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Messages scanned: up to {max_messages}",
        f"Queue rows: {len(rows)}",
        f"Inbound rows: {inbound}",
        f"Needs reply: {needs_reply}",
        f"Keywords: {', '.join(keywords)}",
        "",
        "Privacy rule: this export only includes rows matching known FUNDz client names, known client phone numbers, or approved business keywords.",
        "No browser or client-facing action should happen from this file unless a queue row has owner, status, next step, and proof requirement.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_queue(
    messages_db: Path = DEFAULT_MESSAGES_DB,
    output: Path = DEFAULT_OUTPUT,
    summary: Path = DEFAULT_SUMMARY,
    keywords: list[str] | None = None,
    max_messages: int = 50_000,
) -> list[dict[str, str]]:
    keywords = keywords or BUSINESS_KEYWORDS
    directory = load_client_directory()
    rows = message_rows(messages_db.expanduser(), max_messages)
    queue_rows = matched_queue_rows(rows, directory, keywords)
    write_dict_csv(output, queue_rows, QUEUE_FIELDS)
    write_summary(summary, queue_rows, keywords, max_messages)
    return queue_rows


def permission_help(error: Exception) -> str:
    return (
        "macOS blocked access to Messages/iPhone backup data. Grant Full Disk Access to Codex "
        "or the terminal app running this command, then restart Codex and rerun. Path: System "
        "Settings > Privacy & Security > Full Disk Access."
        f"\nOriginal error: {error}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a filtered business-message queue from Mac Messages.")
    parser.add_argument("--messages-db", type=Path, default=DEFAULT_MESSAGES_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--keywords", default=",".join(BUSINESS_KEYWORDS))
    parser.add_argument("--max-messages", type=int, default=50_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rows = build_queue(
            messages_db=args.messages_db,
            output=args.output,
            summary=args.summary,
            keywords=parse_keywords(args.keywords),
            max_messages=args.max_messages,
        )
    except (PermissionError, sqlite3.DatabaseError) as error:
        message = str(error).lower()
        if "authorization denied" in message or "operation not permitted" in message or "not authorized" in message:
            print(permission_help(error), file=sys.stderr)
            return 2
        raise

    print(f"Wrote {len(rows)} business-message queue row(s): {args.output}")
    print(f"Summary: {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
