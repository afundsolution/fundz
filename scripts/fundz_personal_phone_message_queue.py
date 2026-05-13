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
import os
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
DEFAULT_TRIAGE = OUTPUT_DIR / "fundz-personal-phone-needs-reply-triage.csv"
DEFAULT_TRIAGE_MD = OUTPUT_DIR / "fundz-personal-phone-needs-reply-triage.md"
DEFAULT_CANDIDATES = OUTPUT_DIR / "fundz-personal-phone-work-queue-candidates.csv"
DEFAULT_NO_COMPANY_ACTION = OUTPUT_DIR / "fundz-personal-phone-no-company-action.csv"

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

TRIAGE_FIELDS = [
    "triage_id",
    "contact",
    "phone",
    "date",
    "classification",
    "reply_needed",
    "move_to_work_queue",
    "needs_brandon_decision",
    "sanitized_summary",
    "recommended_action",
    "source",
]

CANDIDATE_FIELDS = [
    "work_order_id",
    "created_at",
    "actor",
    "system",
    "lane",
    "queue_status",
    "client_key",
    "client_name",
    "owner",
    "due_date",
    "next_step",
    "proof_required",
    "proof",
    "evidence",
    "priority_score",
    "flags",
    "browser_required",
    "do_not_send_because",
    "approval_needed",
]

DEFAULT_OWNER_PHONE_SUFFIXES = {"3466429919"}

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


def owner_phone_suffixes() -> set[str]:
    raw = os.environ.get("FUNDZ_OWNER_COMMAND_SENDERS", "")
    configured = {normalize_phone(item)[-10:] for item in raw.split(",") if normalize_phone(item)}
    return configured or DEFAULT_OWNER_PHONE_SUFFIXES


def is_owner_contact(contact: str, phone: str) -> bool:
    normalized_contact = normalize_name(contact)
    normalized_phone = normalize_phone(phone)[-10:]
    return normalized_contact == "brandon jordan" or normalized_phone in owner_phone_suffixes()


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return BUSINESS_KEYWORDS
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_no_company_action_contacts(path: Path = DEFAULT_NO_COMPANY_ACTION) -> set[str]:
    return {
        normalize_name(row.get("contact", ""))
        for row in read_csv_rows(path)
        if row.get("decision", "").lower() in {"personal", "no_company_action", "ignore"}
    }


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
        owner_contact = inbound and is_owner_contact(matched_contact, handle)
        needs_reply = inbound and trusted_contact and not owner_contact
        status = "Needs Reply" if needs_reply else "Review"
        phone = display_phone(handle) if normalized_handle_phone else handle
        contact = matched_contact or "Unknown business keyword match"
        if owner_contact:
            status = "Owner Review"
            match_reasons.append("owner_command_source")
        source = "Mac Messages chat.db | " + ";".join(sorted(set(match_reasons)))
        next_step = (
            "Review and reply from the approved business channel; attach proof after response."
            if needs_reply
            else (
                "Route as owner-command/private intake; do not place in the client Work Queue unless Brandon asks."
                if owner_contact
                else (
                "Verify this is a FUNDz client or business lead before any reply; keep out of shared systems unless approved."
                if inbound
                else "Review for business context; no reply needed unless Governor flags a follow-up gap."
                )
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


def client_key(contact: str) -> str:
    normalized = normalize_name(contact)
    return f"name:{normalized.replace(' ', '-')}" if normalized else ""


def triage_rows(
    queue_rows: list[dict[str, str]],
    no_company_action_contacts: set[str] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    no_company_action_contacts = no_company_action_contacts or set()
    inbound_rows = [row for row in queue_rows if row.get("direction") == "inbound"]
    for index, row in enumerate(inbound_rows, start=1):
        contact = row.get("contact", "")
        source = row.get("source", "")
        owner_command = "owner_command_source" in source or is_owner_contact(contact, row.get("phone", ""))
        unknown_keyword = contact == "Unknown business keyword match" and "client_" not in source
        needs_reply = row.get("needs_reply") == "yes"
        personal_no_action = normalize_name(contact) in no_company_action_contacts
        sensitive = contact == "Travis Vance"

        if personal_no_action:
            classification = "personal/no-company-action"
            move_to_queue = "no"
            needs_decision = "no"
            summary = "Brandon identified this personal-phone row as personal. Keep it out of A FUND Solution work."
            action = "Move on. Do not verify, reply, or create a Work Queue row from this phone item."
        elif owner_command:
            classification = "owner-command/private intake"
            move_to_queue = "no"
            needs_decision = "no"
            summary = "Owner-number message surfaced in the business filter; keep it in owner-command/private intake, not the client Work Queue."
            action = "Handle through the owner-command path if needed. Do not treat as a client reply."
        elif unknown_keyword:
            classification = "possible non-client/personal false positive"
            move_to_queue = "no"
            needs_decision = "no"
            summary = "Unknown inbound business-keyword match without a known client phone/name. Keep out of shared systems unless Brandon recognizes it as business."
            action = "Do not reply from the company workflow. Ignore or handle personally unless Brandon confirms it is FUNDz work."
        elif needs_reply and sensitive:
            classification = "needs Brandon decision"
            move_to_queue = "hold for approval"
            needs_decision = "yes"
            summary = "Known historical client phone match for Travis Vance, but not an active-client row; message content is short and sensitive-looking, so do not copy it into shared systems."
            action = "Brandon should decide whether to verify Travis status in DF/HighLevel. If business-related, create a Work Queue row without exposing the sensitive text; otherwise mark false positive/no action."
        elif needs_reply:
            classification = "known client needs review"
            move_to_queue = "hold for approval"
            needs_decision = "yes"
            summary = "Known client phone/name match with an inbound business-filtered message. Keep the shared packet sanitized until Brandon approves handling."
            action = "Verify current client status and approved response channel before any reply."
        else:
            classification = "review only"
            move_to_queue = "no"
            needs_decision = "no"
            summary = "Business-filtered inbound row does not require a company reply from this queue."
            action = "No shared Work Queue action unless Brandon identifies a business need."

        rows.append(
            {
                "triage_id": f"PPM-NEEDS-REPLY-{index:03d}",
                "contact": contact,
                "phone": row.get("phone", ""),
                "date": row.get("date", ""),
                "classification": classification,
                "reply_needed": "maybe" if needs_decision == "yes" else "no",
                "move_to_work_queue": move_to_queue,
                "needs_brandon_decision": needs_decision,
                "sanitized_summary": summary,
                "recommended_action": action,
                "source": "data/local/command-center/fundz-personal-phone-message-queue.csv",
            }
        )
    return rows


def candidate_rows_from_triage(rows: list[dict[str, str]], generated_at: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for row in rows:
        if row.get("needs_brandon_decision") != "yes":
            continue
        contact = row.get("contact", "")
        slug = normalize_name(contact).replace(" ", "-") or "unknown"
        sensitive = "sensitive" in row.get("sanitized_summary", "").lower()
        candidates.append(
            {
                "work_order_id": f"FUNDZ-PERSONAL-PHONE-{slug.upper().replace('-', '-')}-{row.get('date', '')[:10].replace('-', '')}",
                "created_at": generated_at,
                "actor": "Governor",
                "system": "FUNDz",
                "lane": "personal-phone-intake",
                "queue_status": "Needs Brandon",
                "client_key": client_key(contact),
                "client_name": contact,
                "owner": "Brandon",
                "due_date": generated_at[:10],
                "next_step": row.get("recommended_action", ""),
                "proof_required": "DF/HighLevel current-status proof or Brandon no-action decision. Do not attach sensitive phone-message content to shared systems.",
                "proof": "",
                "evidence": f"data/local/command-center/fundz-personal-phone-needs-reply-triage.md#{row.get('triage_id', '')}",
                "priority_score": "80",
                "flags": "personal_phone_intake;historical_client_phone"
                + (";sensitive_content;not_active_client" if sensitive else ""),
                "browser_required": "yes",
                "do_not_send_because": "Needs Brandon decision and current client status verification before any reply or shared queue action.",
                "approval_needed": "yes",
            }
        )
    return candidates


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


def write_triage_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    false_positive = sum(1 for row in rows if row.get("move_to_work_queue") == "no" and row.get("classification") != "owner-command/private intake")
    owner_private = sum(1 for row in rows if row.get("classification") == "owner-command/private intake")
    needs_decision = sum(1 for row in rows if row.get("needs_brandon_decision") == "yes")
    lines = [
        "# Personal Phone Needs-Reply Triage",
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "Privacy note: message bodies are intentionally omitted. This packet contains sanitized summaries only.",
        "",
        "## Recommendation",
        "",
        "- Move 0 rows into the shared Work Queue automatically.",
        f"- Treat {false_positive} rows as false-positive/no-company-action unless Brandon recognizes them.",
        f"- Keep {owner_private} owner-number rows in owner-command/private intake instead of the client queue.",
        f"- Hold {needs_decision} row for Brandon decision before any shared Work Queue action.",
        "- Security-code short-code messages are excluded from the personal-phone queue before triage.",
        "",
        "## Rows",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"### {row['triage_id']} - {row['classification']}",
                f"- Contact: {row['contact']}",
                f"- Phone: {row['phone']}",
                f"- Date: {row['date']}",
                f"- Reply needed: {row['reply_needed']}",
                f"- Move to Work Queue: {row['move_to_work_queue']}",
                f"- Needs Brandon decision: {row['needs_brandon_decision']}",
                f"- Sanitized summary: {row['sanitized_summary']}",
                f"- Recommended action: {row['recommended_action']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_queue(
    messages_db: Path = DEFAULT_MESSAGES_DB,
    output: Path = DEFAULT_OUTPUT,
    summary: Path = DEFAULT_SUMMARY,
    triage: Path = DEFAULT_TRIAGE,
    triage_md: Path = DEFAULT_TRIAGE_MD,
    candidates: Path = DEFAULT_CANDIDATES,
    no_company_action: Path = DEFAULT_NO_COMPANY_ACTION,
    keywords: list[str] | None = None,
    max_messages: int = 50_000,
) -> list[dict[str, str]]:
    keywords = keywords or BUSINESS_KEYWORDS
    directory = load_client_directory()
    rows = message_rows(messages_db.expanduser(), max_messages)
    queue_rows = matched_queue_rows(rows, directory, keywords)
    write_dict_csv(output, queue_rows, QUEUE_FIELDS)
    write_summary(summary, queue_rows, keywords, max_messages)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    triage_output_rows = triage_rows(queue_rows, load_no_company_action_contacts(no_company_action))
    write_dict_csv(triage, triage_output_rows, TRIAGE_FIELDS)
    write_triage_markdown(triage_md, triage_output_rows)
    write_dict_csv(candidates, candidate_rows_from_triage(triage_output_rows, generated_at), CANDIDATE_FIELDS)
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
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--triage-md", type=Path, default=DEFAULT_TRIAGE_MD)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--no-company-action", type=Path, default=DEFAULT_NO_COMPANY_ACTION)
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
            triage=args.triage,
            triage_md=args.triage_md,
            candidates=args.candidates,
            no_company_action=args.no_company_action,
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
    print(f"Triage: {args.triage_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
