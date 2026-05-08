#!/usr/bin/env python3
"""Build the master FUNDz operational client state from local DisputeFox reports."""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DISPUTE_FOX_DIR = ROOT / "data" / "dispute-fox"
DEFAULT_OUTPUT = ROOT / "data" / "local" / "fundz-client-state.json"
DEFAULT_SUMMARY_CSV = ROOT / "data" / "local" / "fundz-client-state-summary.csv"
DEFAULT_CLIENT_INDEX = ROOT / "data" / "local" / "fundz-client-index.json"

ACTIVE_PATTERNS = (
    "disputefox-active-clients-full-*.csv",
    "*active-clients-full*.csv",
    "disputefox-active-clients-*.csv",
    "*active-clients*.csv",
)
DISPUTE_PATTERNS = (
    "disputefox-dispute-deleted-repaired-report-*.csv",
    "*dispute*deleted*repaired*.csv",
)
EMAIL_PATTERNS = ("disputefox-email-report-*.csv", "*email-report*.csv")
SMS_PATTERNS = ("disputefox-sms-report-*.csv", "*sms-report*.csv")


def read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def latest_matching_file(source_dir: Path, patterns: tuple[str, ...]) -> Path | None:
    for pattern in patterns:
        matches = [path for path in source_dir.glob(pattern) if path.is_file()]
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)
    return None


def relative_label(path: Path | None, root: Path = ROOT) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def value(row: dict[str, str], *names: str) -> str:
    lookup = {str(key).strip().lower().replace(" ", "_"): val for key, val in row.items()}
    for name in names:
        raw = lookup.get(name.strip().lower().replace(" ", "_"))
        if raw not in (None, ""):
            return str(raw).strip()
    return ""


def normalize_name(name: str) -> str:
    text = re.sub(r"\s*\*\s*new\b", "", name.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def make_client_key(name: str, email: str = "") -> str:
    normalized = normalize_name(name)
    if normalized:
        return "name:" + normalized.replace(" ", "-")
    if email:
        return "email:" + email.strip().lower()
    return "unknown"


def parse_int(text: str) -> int:
    match = re.search(r"-?\d+", text or "")
    return int(match.group(0)) if match else 0


def parse_optional_int(text: str) -> int | None:
    match = re.search(r"-?\d+", text or "")
    return int(match.group(0)) if match else None


def parse_percent(text: str) -> int | None:
    match = re.search(r"(\d+)\s*%", text or "")
    return int(match.group(1)) if match else None


def parse_round(stage: str) -> dict[str, Any]:
    round_match = re.search(r"\bround\s+(\d+)\b", stage or "", re.I)
    date_match = re.search(r"\(([^)]+)\)", stage or "")
    return {
        "number": int(round_match.group(1)) if round_match else None,
        "label": f"Round {round_match.group(1)}" if round_match else "",
        "date": date_match.group(1) if date_match else "",
    }


def email_addresses(text: str) -> list[str]:
    return [match.group(0).lower() for match in re.finditer(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text or "", re.I)]


def classify_email_subject(subject: str) -> str:
    lower = (subject or "").lower()
    if "payment failure" in lower or "card fail" in lower:
        return "payment_failure"
    if "score alert" in lower:
        return "credit_score_alert"
    if "round" in lower and ("sent" in lower or "been sent" in lower):
        return "dispute_round_sent"
    if "import" in lower and "due" in lower:
        return "import_due"
    if "signed agreement" in lower or "uploaded doc" in lower or "required documents complete" in lower:
        return "onboarding_document"
    if "account" in lower and "ready" in lower:
        return "portal_account_ready"
    if "mobile app" in lower:
        return "portal_mobile_app"
    if "credit restoration process" in lower:
        return "education"
    return "other"


def empty_client(name: str, email: str = "") -> dict[str, Any]:
    key = make_client_key(name, email)
    return {
        "client_key": key,
        "is_active_client": False,
        "client_name": name,
        "email": email.strip().lower(),
        "status": "unknown",
        "messages": "",
        "billing": "",
        "next_import": "",
        "next_import_days": None,
        "started": "",
        "assigned_to": "",
        "stage_in_process": "",
        "dispute_round": {"number": None, "label": "", "date": ""},
        "onboarding": "",
        "onboarding_percent": None,
        "action": "",
        "dispute_items": {
            "all_items": 0,
            "in_dispute_count": 0,
            "deleted_count": 0,
            "repaired_count": 0,
        },
        "send_history": {
            "email_count": 0,
            "sms_count": 0,
            "latest_email": {},
            "recent_emails": [],
            "recent_sms": [],
            "email_subject_tags": [],
            "recipients": [],
        },
        "operational_flags": [],
        "recommended_next_action": "Review client file.",
        "sources": [],
    }


def add_source(client: dict[str, Any], label: str) -> None:
    if label and label not in client["sources"]:
        client["sources"].append(label)


def get_or_create_client(
    clients: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    email_index: dict[str, str],
    name: str,
    email: str = "",
) -> dict[str, Any]:
    norm_name = normalize_name(name)
    norm_email = email.strip().lower()
    key = name_index.get(norm_name) or email_index.get(norm_email) or make_client_key(name, email)
    if key not in clients:
        clients[key] = empty_client(name.strip(), norm_email)
    client = clients[key]
    if name and not client.get("client_name"):
        client["client_name"] = name.strip()
    if norm_email and not client.get("email"):
        client["email"] = norm_email
    if norm_name:
        name_index[norm_name] = key
    if norm_email:
        email_index[norm_email] = key
    return client


def attach_active_clients(
    rows: list[dict[str, str]],
    source_label: str,
    clients: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    email_index: dict[str, str],
) -> None:
    for row in rows:
        name = value(row, "client_name", "customer_name", "name", "full_name")
        email = value(row, "email")
        if not name and not email:
            continue
        client = get_or_create_client(clients, name_index, email_index, name, email)
        client.update(
            {
                "is_active_client": True,
                "status": value(row, "status") or "unknown",
                "messages": value(row, "messages"),
                "billing": value(row, "billing"),
                "next_import": value(row, "next_import"),
                "next_import_days": parse_optional_int(value(row, "next_import")),
                "started": value(row, "started"),
                "assigned_to": value(row, "assigned_to"),
                "stage_in_process": value(row, "stage_in_process", "stage"),
                "onboarding": value(row, "onboarding"),
                "onboarding_percent": parse_percent(value(row, "onboarding")),
                "action": value(row, "action"),
            }
        )
        client["dispute_round"] = parse_round(client["stage_in_process"])
        add_source(client, source_label)


def attach_dispute_counts(
    rows: list[dict[str, str]],
    source_label: str,
    clients: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    email_index: dict[str, str],
) -> None:
    for row in rows:
        name = value(row, "client_name", "customer_name", "full_name", "name")
        if not name:
            continue
        client = get_or_create_client(clients, name_index, email_index, name, "")
        client["dispute_items"] = {
            "all_items": parse_int(value(row, "all_items")),
            "in_dispute_count": parse_int(value(row, "in_dispute_count")),
            "deleted_count": parse_int(value(row, "deleted_count")),
            "repaired_count": parse_int(value(row, "repaired_count")),
        }
        add_source(client, source_label)


def best_client_for_history(
    clients: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    email_index: dict[str, str],
    name: str,
    recipients: list[str],
) -> dict[str, Any]:
    for recipient in recipients:
        key = email_index.get(recipient.lower())
        if key:
            return clients[key]
    return get_or_create_client(clients, name_index, email_index, name, recipients[0] if recipients else "")


def attach_email_history(
    rows: list[dict[str, str]],
    source_label: str,
    clients: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    email_index: dict[str, str],
    recent_limit: int,
) -> list[tuple[str, int]]:
    duplicate_keys: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    for row in rows:
        name = value(row, "client_name", "customer_name", "name")
        sent_to = value(row, "sent_to", "recipient", "email")
        recipients = email_addresses(sent_to)
        subject = value(row, "subject")
        sent_date = value(row, "sent_date", "date", "timestamp", "time")
        client = best_client_for_history(clients, name_index, email_index, name, recipients)
        history = client["send_history"]
        email = {
            "sent_to": sent_to,
            "email_from": value(row, "email_from", "from"),
            "subject": subject,
            "sent_date": sent_date,
            "tag": classify_email_subject(subject),
        }
        history["email_count"] += 1
        if not history["latest_email"]:
            history["latest_email"] = email
        if len(history["recent_emails"]) < recent_limit:
            history["recent_emails"].append(email)
        for recipient in recipients:
            if recipient not in history["recipients"]:
                history["recipients"].append(recipient)
        tag = email["tag"]
        if tag not in history["email_subject_tags"]:
            history["email_subject_tags"].append(tag)
        duplicate_keys[(client["client_key"], sent_to, subject, sent_date)] += 1
        add_source(client, source_label)
    return [(key[0], count) for key, count in duplicate_keys.items() if count > 1]


def attach_sms_history(
    rows: list[dict[str, str]],
    source_label: str,
    clients: dict[str, dict[str, Any]],
    name_index: dict[str, str],
    email_index: dict[str, str],
    recent_limit: int,
) -> None:
    for row in rows:
        name = value(row, "customer_name", "client_name", "name")
        if not name:
            continue
        client = get_or_create_client(clients, name_index, email_index, name, "")
        history = client["send_history"]
        sms = {
            "sent_to": value(row, "sent_to", "phone", "recipient"),
            "sms_from": value(row, "sms_from", "from"),
        }
        history["sms_count"] += 1
        if len(history["recent_sms"]) < recent_limit:
            history["recent_sms"].append(sms)
        if sms["sent_to"] and sms["sent_to"] not in history["recipients"]:
            history["recipients"].append(sms["sent_to"])
        add_source(client, source_label)


def client_flags(client: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    status = (client.get("status") or "").lower()
    stage = (client.get("stage_in_process") or "").lower()
    history = client.get("send_history", {})

    if "due for next round" in status:
        flags.append("due_for_next_round")
    if "in dispute" in status:
        flags.append("in_dispute")
    if "in dispute" in status and client.get("next_import_days") is None:
        flags.append("missing_next_import")
    if client.get("onboarding_percent") not in (None, 100):
        flags.append("onboarding_incomplete")
    if "customer details" in stage or "agreement signed" in stage:
        flags.append("setup_incomplete")
    if client.get("is_active_client") and history.get("email_count", 0) == 0 and history.get("sms_count", 0) == 0:
        flags.append("no_send_history_linked")
    if not client.get("is_active_client") and (history.get("email_count", 0) or history.get("sms_count", 0)):
        flags.append("history_only_record")
    if "payment_failure" in history.get("email_subject_tags", []):
        flags.append("payment_attention")
    return flags


def recommended_action(client: dict[str, Any]) -> str:
    flags = set(client.get("operational_flags", []))
    next_days = client.get("next_import_days")
    round_label = client.get("dispute_round", {}).get("label")
    if "due_for_next_round" in flags:
        return "Review next-round readiness and prepare the next dispute round."
    if "setup_incomplete" in flags or "onboarding_incomplete" in flags:
        return "Finish onboarding requirements before automated follow-up."
    if "payment_attention" in flags:
        return "Review billing/payment status before sending more campaign messages."
    if "in_dispute" in flags and isinstance(next_days, int):
        return f"Monitor {round_label or 'active dispute round'}; next import is in {next_days} day(s)."
    if "in_dispute" in flags:
        return f"Monitor {round_label or 'active dispute round'} and confirm next import date."
    if "history_only_record" in flags:
        return "Stored communication history exists, but the active-client export does not include current status."
    return "Review client file and keep synced with DisputeFox."


def finalize_clients(clients: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    final = []
    for client in clients.values():
        client["operational_flags"] = client_flags(client)
        client["recommended_next_action"] = recommended_action(client)
        final.append(client)
    return sorted(final, key=lambda item: (item.get("client_name") or "").lower())


def build_queues(clients: list[dict[str, Any]]) -> dict[str, list[str]]:
    queues = {
        "due_for_next_round": [],
        "in_dispute": [],
        "missing_next_import": [],
        "onboarding_incomplete": [],
        "payment_attention": [],
        "no_send_history_linked": [],
    }
    for client in clients:
        name = client.get("client_name") or client.get("client_key")
        flags = set(client.get("operational_flags", []))
        for queue_name in queues:
            if queue_name in flags:
                queues[queue_name].append(name)
    return queues


def build_summary(clients: list[dict[str, Any]], duplicate_email_sends: list[tuple[str, int]]) -> dict[str, Any]:
    statuses = Counter(client.get("status") or "unknown" for client in clients)
    flags = Counter(flag for client in clients for flag in client.get("operational_flags", []))
    email_count = sum(client.get("send_history", {}).get("email_count", 0) for client in clients)
    sms_count = sum(client.get("send_history", {}).get("sms_count", 0) for client in clients)
    return {
        "clients": len(clients),
        "active_clients": sum(1 for client in clients if client.get("is_active_client")),
        "statuses": dict(statuses.most_common()),
        "flags": dict(flags.most_common()),
        "due_for_next_round": flags.get("due_for_next_round", 0),
        "in_dispute": flags.get("in_dispute", 0),
        "missing_next_import": flags.get("missing_next_import", 0),
        "email_sends_linked": email_count,
        "sms_sends_linked": sms_count,
        "possible_duplicate_email_sends": len(duplicate_email_sends),
    }


def build_operational_state(source_dir: Path = DISPUTE_FOX_DIR, recent_limit: int = 10) -> dict[str, Any]:
    source_dir = Path(source_dir)
    files = {
        "active_clients": latest_matching_file(source_dir, ACTIVE_PATTERNS),
        "dispute_deleted_repaired": latest_matching_file(source_dir, DISPUTE_PATTERNS),
        "email_report": latest_matching_file(source_dir, EMAIL_PATTERNS),
        "sms_report": latest_matching_file(source_dir, SMS_PATTERNS),
    }

    clients: dict[str, dict[str, Any]] = {}
    name_index: dict[str, str] = {}
    email_index: dict[str, str] = {}

    attach_active_clients(read_csv(files["active_clients"]), relative_label(files["active_clients"]), clients, name_index, email_index)
    attach_dispute_counts(read_csv(files["dispute_deleted_repaired"]), relative_label(files["dispute_deleted_repaired"]), clients, name_index, email_index)
    duplicate_email_sends = attach_email_history(
        read_csv(files["email_report"]),
        relative_label(files["email_report"]),
        clients,
        name_index,
        email_index,
        recent_limit,
    )
    attach_sms_history(read_csv(files["sms_report"]), relative_label(files["sms_report"]), clients, name_index, email_index, recent_limit)

    final_clients = finalize_clients(clients)
    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_dir": relative_label(source_dir),
            "source_files": {name: relative_label(path) for name, path in files.items() if path},
            "recent_history_limit_per_client": recent_limit,
            "policy": "Local operational state only. No replies are sent and no production code is modified.",
        },
        "summary": build_summary(final_clients, duplicate_email_sends),
        "queues": build_queues(final_clients),
        "clients": final_clients,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_summary_csv(path: Path, clients: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "client_key",
        "is_active_client",
        "client_name",
        "email",
        "status",
        "next_import",
        "next_import_days",
        "started",
        "assigned_to",
        "stage_in_process",
        "dispute_round",
        "onboarding_percent",
        "all_items",
        "in_dispute_count",
        "deleted_count",
        "repaired_count",
        "email_count",
        "sms_count",
        "latest_email_subject",
        "latest_email_sent_date",
        "flags",
        "recommended_next_action",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for client in clients:
            dispute_items = client.get("dispute_items", {})
            history = client.get("send_history", {})
            latest_email = history.get("latest_email") or {}
            writer.writerow(
                {
                    "client_key": client.get("client_key", ""),
                    "is_active_client": "true" if client.get("is_active_client") else "false",
                    "client_name": client.get("client_name", ""),
                    "email": client.get("email", ""),
                    "status": client.get("status", ""),
                    "next_import": client.get("next_import", ""),
                    "next_import_days": client.get("next_import_days"),
                    "started": client.get("started", ""),
                    "assigned_to": client.get("assigned_to", ""),
                    "stage_in_process": client.get("stage_in_process", ""),
                    "dispute_round": client.get("dispute_round", {}).get("label", ""),
                    "onboarding_percent": client.get("onboarding_percent"),
                    "all_items": dispute_items.get("all_items", 0),
                    "in_dispute_count": dispute_items.get("in_dispute_count", 0),
                    "deleted_count": dispute_items.get("deleted_count", 0),
                    "repaired_count": dispute_items.get("repaired_count", 0),
                    "email_count": history.get("email_count", 0),
                    "sms_count": history.get("sms_count", 0),
                    "latest_email_subject": latest_email.get("subject", ""),
                    "latest_email_sent_date": latest_email.get("sent_date", ""),
                    "flags": ";".join(client.get("operational_flags", [])),
                    "recommended_next_action": client.get("recommended_next_action", ""),
                }
            )


def client_index_entry(client: dict[str, Any]) -> dict[str, Any]:
    history = client.get("send_history", {})
    dispute_items = client.get("dispute_items", {})
    name = str(client.get("client_name") or client.get("client_key") or "")
    return {
        "client_key": client.get("client_key"),
        "client_name": name,
        "normalized_name": normalize_name(name),
        "email": client.get("email", ""),
        "is_active_client": bool(client.get("is_active_client")),
        "status": client.get("status", ""),
        "stage_in_process": client.get("stage_in_process", ""),
        "next_import": client.get("next_import", ""),
        "assigned_to": client.get("assigned_to", ""),
        "onboarding": client.get("onboarding", ""),
        "all_items": dispute_items.get("all_items", 0),
        "in_dispute_count": dispute_items.get("in_dispute_count", 0),
        "deleted_count": dispute_items.get("deleted_count", 0),
        "repaired_count": dispute_items.get("repaired_count", 0),
        "email_count": history.get("email_count", 0),
        "sms_count": history.get("sms_count", 0),
        "flags": client.get("operational_flags", []),
        "recommended_next_action": client.get("recommended_next_action", ""),
        "sources": client.get("sources", []),
    }


def build_client_index(state: dict[str, Any]) -> dict[str, Any]:
    clients = state.get("clients", [])
    entries = [client_index_entry(client) for client in clients]
    by_normalized_name: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        normalized = entry.get("normalized_name")
        key = entry.get("client_key")
        if normalized and key:
            by_normalized_name[str(normalized)].append(str(key))
    return {
        "generated_at": state.get("metadata", {}).get("generated_at"),
        "source_files": state.get("metadata", {}).get("source_files", {}),
        "summary": state.get("summary", {}),
        "lookup_policy": (
            "Use this index before saying a client record is unavailable. "
            "Rows with is_active_client=false may still have useful email/SMS history."
        ),
        "by_normalized_name": dict(by_normalized_name),
        "clients": entries,
    }


def write_client_index(path: Path, state: dict[str, Any]) -> None:
    write_json(path, build_client_index(state))


def find_client_matches(state: dict[str, Any], query: str) -> list[dict[str, Any]]:
    normalized_query = normalize_name(query)
    if not normalized_query:
        return []

    clients = state.get("clients", [])
    exact_matches = [
        client
        for client in clients
        if normalize_name(str(client.get("client_name") or "")) == normalized_query
        or str(client.get("client_key") or "").removeprefix("name:").replace("-", " ") == normalized_query
    ]
    if exact_matches:
        return exact_matches

    query_tokens = set(normalized_query.split())
    partial_matches = []
    for client in clients:
        name = normalize_name(str(client.get("client_name") or ""))
        email = str(client.get("email") or "").lower()
        haystack_tokens = set(name.split())
        if query_tokens.issubset(haystack_tokens) or normalized_query in email:
            partial_matches.append(client)
    return partial_matches


def find_index_matches(index: dict[str, Any], query: str, cutoff: float = 0.86) -> list[dict[str, Any]]:
    normalized_query = normalize_name(query)
    if not normalized_query:
        return []

    clients = [client for client in index.get("clients", []) if isinstance(client, dict)]
    exact_matches = [client for client in clients if client.get("normalized_name") == normalized_query]
    if exact_matches:
        return exact_matches

    query_tokens = set(normalized_query.split())
    partial_matches = []
    for client in clients:
        normalized = str(client.get("normalized_name") or "")
        email = str(client.get("email") or "").lower()
        if query_tokens.issubset(set(normalized.split())) or normalized_query in email:
            partial_matches.append(client)
    if partial_matches:
        return partial_matches

    normalized_names = [str(client.get("normalized_name") or "") for client in clients if client.get("normalized_name")]
    close_names = difflib.get_close_matches(normalized_query, normalized_names, n=5, cutoff=cutoff)
    close_set = set(close_names)
    return [client for client in clients if client.get("normalized_name") in close_set]


def index_entry_to_client(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_key": entry.get("client_key"),
        "client_name": entry.get("client_name"),
        "email": entry.get("email", ""),
        "is_active_client": bool(entry.get("is_active_client")),
        "status": entry.get("status", ""),
        "stage_in_process": entry.get("stage_in_process", ""),
        "next_import": entry.get("next_import", ""),
        "assigned_to": entry.get("assigned_to", ""),
        "onboarding": entry.get("onboarding", ""),
        "dispute_items": {
            "all_items": entry.get("all_items", 0),
            "in_dispute_count": entry.get("in_dispute_count", 0),
            "deleted_count": entry.get("deleted_count", 0),
            "repaired_count": entry.get("repaired_count", 0),
        },
        "send_history": {
            "email_count": entry.get("email_count", 0),
            "sms_count": entry.get("sms_count", 0),
            "latest_email": {},
            "recent_emails": [],
            "recent_sms": [{}] if entry.get("sms_count", 0) else [],
            "email_subject_tags": [],
            "recipients": [],
        },
        "operational_flags": entry.get("flags", []),
        "recommended_next_action": entry.get("recommended_next_action", "Review client file."),
        "sources": entry.get("sources", []),
    }


def format_client_update(client: dict[str, Any]) -> str:
    history = client.get("send_history", {})
    dispute_items = client.get("dispute_items", {})
    latest_email = history.get("latest_email") or {}
    recent_sms = history.get("recent_sms") or []
    flags = client.get("operational_flags", [])

    lines = [f"Latest FUNDz update for {client.get('client_name') or 'this client'}:", ""]
    lines.extend(
        [
            f"- Status: {client.get('status') or 'unknown'}.",
            f"- Stage: {client.get('stage_in_process') or 'not shown in the latest export'}.",
            f"- Next import: {client.get('next_import') or 'not shown in the latest export'}.",
            f"- Assigned to: {client.get('assigned_to') or 'not shown in the latest export'}.",
            f"- Onboarding: {client.get('onboarding') or 'not shown in the latest export'}.",
            (
                "- Dispute items: "
                f"{dispute_items.get('all_items', 0)} total, "
                f"{dispute_items.get('in_dispute_count', 0)} in dispute, "
                f"{dispute_items.get('deleted_count', 0)} deleted, "
                f"{dispute_items.get('repaired_count', 0)} repaired."
            ),
            f"- Send history linked: {history.get('email_count', 0)} email(s), {history.get('sms_count', 0)} SMS.",
        ]
    )
    if latest_email:
        lines.append(
            f"- Latest email: {latest_email.get('subject') or 'no subject'} ({latest_email.get('sent_date') or 'date unknown'})."
        )
    elif recent_sms:
        lines.append("- Latest linked activity: SMS history is present, but the export does not include SMS message text.")

    lines.extend(["", "Needs attention:"])
    if flags:
        for flag in flags:
            lines.append(f"- {flag.replace('_', ' ')}.")
    else:
        lines.append("- No operational flags are showing in the latest local export.")

    lines.extend(["", "Next move:", f"- {client.get('recommended_next_action') or 'Review client file.'}"])

    sources = client.get("sources", [])
    if sources:
        lines.extend(["", "Sources:"])
        for source in sources:
            lines.append(f"- {source}")
    return "\n".join(lines)


def print_summary(state: dict[str, Any], output: Path, summary_csv: Path, client_index: Path) -> None:
    summary = state.get("summary", {})
    source_files = state.get("metadata", {}).get("source_files", {})
    print("Built the master FUNDz operational state.")
    print(f"- Client profiles: {summary.get('clients', 0)}")
    print(f"- Active clients: {summary.get('active_clients', 0)}")
    print(f"- Due for next round: {summary.get('due_for_next_round', 0)}")
    print(f"- In dispute: {summary.get('in_dispute', 0)}")
    print(f"- Missing next import: {summary.get('missing_next_import', 0)}")
    print(f"- Email sends linked: {summary.get('email_sends_linked', 0)}")
    print(f"- SMS sends linked: {summary.get('sms_sends_linked', 0)}")
    print(f"- JSON brain: {relative_label(output)}")
    print(f"- Summary CSV: {relative_label(summary_csv)}")
    print(f"- Client index: {relative_label(client_index)}")
    if source_files:
        print("- Sources: " + ", ".join(source_files.values()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DISPUTE_FOX_DIR, help="Folder containing DisputeFox CSV reports.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path for the master JSON state.")
    parser.add_argument("--summary-csv", type=Path, default=DEFAULT_SUMMARY_CSV, help="Path for the flat summary CSV.")
    parser.add_argument("--client-index", type=Path, default=DEFAULT_CLIENT_INDEX, help="Path for the client lookup index.")
    parser.add_argument("--recent-limit", type=int, default=10, help="Recent email/SMS rows to retain per client.")
    parser.add_argument("--client", default="", help="Print a focused update for one client name or email.")
    parser.add_argument("--quiet", action="store_true", help="Write files without printing the summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = build_operational_state(args.source_dir, recent_limit=max(args.recent_limit, 0))
    write_json(args.output, state)
    write_summary_csv(args.summary_csv, state["clients"])
    write_client_index(args.client_index, state)
    if args.client:
        matches = find_client_matches(state, args.client)
        if not matches:
            raise SystemExit(f"No matching client found for {args.client!r} in the latest local DisputeFox state.")
        if len(matches) > 1:
            print(f"Multiple clients matched {args.client!r}:")
            for client in matches:
                print(f"- {client.get('client_name')} | {client.get('status')} | {client.get('email')}")
            return
        print(format_client_update(matches[0]))
        return
    if not args.quiet:
        print_summary(state, args.output, args.summary_csv, args.client_index)


if __name__ == "__main__":
    main()
