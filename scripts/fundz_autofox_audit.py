#!/usr/bin/env python3
"""Create a local AutoFox outbound audit from exported send/action logs."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (ROOT / "data" / "exports", ROOT / "data" / "dispute-fox")
BRIDGE_LOG = ROOT / "logs" / "credit-tracker-bridge.jsonl"
OUTPUT_DIR = ROOT / "data" / "local" / "autofox-audits"

OUTBOUND_WORDS = (
    "sent",
    "send",
    "delivered",
    "queued",
    "scheduled",
    "failed",
    "undelivered",
    "outbound",
    "sms",
    "email",
    "message",
    "autofox",
    "workflow",
    "campaign",
)

RISKY_PATTERNS = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.I),
    re.compile(r"\bdelete(?:d|s)?\b", re.I),
    re.compile(r"\bremove(?:d|s)?\b", re.I),
    re.compile(r"\bboost\b", re.I),
    re.compile(r"\bapproval\b", re.I),
    re.compile(r"\bscore increase\b", re.I),
    re.compile(r"\bresults? (?:are|is) guaranteed\b", re.I),
    re.compile(r"\bwe (?:will|can) fix\b", re.I),
)

FIELD_ALIASES = {
    "event_id": ("event_id", "id", "message_id", "messageid", "activity_id", "action_id", "uuid"),
    "timestamp": ("timestamp", "created_at", "createdat", "date", "sent_at", "sentat", "time", "created"),
    "status": ("status", "state", "delivery_status", "deliverystatus", "result"),
    "channel": ("channel", "type", "message_type", "messagetype", "medium"),
    "direction": ("direction", "message_direction", "messagedirection"),
    "campaign": ("campaign", "workflow", "workflow_name", "workflowname", "automation", "action", "template"),
    "recipient": ("recipient", "to", "phone", "email", "contact", "contact_id", "contactid", "client", "name"),
    "case_id": ("case_id", "caseid", "client_id", "clientid", "disputefox_id", "contact_id", "contactid"),
    "body": ("message", "body", "text", "content", "sms_body", "email_body", "reply", "draft_reply"),
    "failure": ("failure", "failure_reason", "failurereason", "error", "error_message", "errormessage"),
}

BRIDGE_OUTBOUND_KINDS = {"reply_dry_run", "webhook_replied", "reply_sent", "reply_failed", "send_failed"}
BRIDGE_NON_OUTBOUND_KINDS = {"http", "bridge_started", "bridge_stopped", "health", "webhook_received"}


def newest_candidate_files() -> list[Path]:
    candidates: list[Path] = []
    for source_dir in SOURCE_DIRS:
        candidates.extend(
            path
            for path in source_dir.glob("*")
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in {".csv", ".json", ".jsonl"}
            and not is_generated_reporting_file(path)
        )
    if BRIDGE_LOG.exists():
        candidates.append(BRIDGE_LOG)
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def is_generated_reporting_file(path: Path) -> bool:
    name = path.name.lower()
    generated_names = (
        "fundz-command-center",
        "fundz-contact-ledger",
        "fundz-owner-review",
        "fundz-no-recent-contact",
        "fundz-next-safe-batch",
        "scorefusion-billing-dashboard",
        "billing-risk-queue",
        "client-billing-roster",
        "disputefox-import-log",
        "dashboard.csv",
        "exceptions.csv",
        "highlevel-scorefusion",
    )
    return any(part in name for part in generated_names)


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_jsonish(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
        return records

    data = json.loads(path.read_text(encoding="utf-8"))
    return extract_records(data)


def extract_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    likely_lists = (
        "messages",
        "actions",
        "events",
        "activities",
        "automations",
        "campaigns",
        "workflows",
        "records",
        "data",
        "items",
    )
    for key in likely_lists:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return [data]


def load_records(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix.lower() == ".csv":
            return read_csv(path)
        if path.suffix.lower() in {".json", ".jsonl"}:
            return read_jsonish(path)
    except (OSError, csv.Error, json.JSONDecodeError):
        return []
    return []


def flatten(record: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in record.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(flatten(value, name))
        elif isinstance(value, list):
            flat[name] = json.dumps(value, ensure_ascii=False)
        elif value is not None:
            flat[name] = str(value).strip()
    return flat


def pick(flat: dict[str, str], aliases: tuple[str, ...]) -> str:
    by_last_key = {key.split(".")[-1].lower().replace(" ", "_").replace("-", "_"): value for key, value in flat.items()}
    for alias in aliases:
        value = by_last_key.get(alias.lower().replace(" ", "_").replace("-", "_"))
        if value:
            return value
    for key, value in flat.items():
        normalized = key.lower().replace(" ", "_").replace("-", "_")
        if any(alias.lower().replace(" ", "_").replace("-", "_") in normalized for alias in aliases) and value:
            return value
    return ""


def derive_status(flat: dict[str, str]) -> str:
    kind = pick(flat, ("kind",)).lower()
    if kind == "reply_dry_run":
        return "dry_run"
    if kind in {"reply_failed", "send_failed"}:
        return "failed"
    dry_run = pick(flat, ("dry_run", "send_result.dry_run")).lower()
    sent = pick(flat, ("sent", "send_result.sent")).lower()
    if dry_run == "true":
        return "dry_run"
    if sent == "true":
        return "sent"
    if sent == "false":
        return "not_sent"
    return pick(flat, FIELD_ALIASES["status"]) or "unknown"


def looks_outbound(flat: dict[str, str]) -> bool:
    kind = pick(flat, ("kind",)).lower()
    if kind in BRIDGE_NON_OUTBOUND_KINDS:
        return False
    if kind in BRIDGE_OUTBOUND_KINDS:
        return True

    text = " ".join(f"{key} {value}" for key, value in flat.items()).lower()
    direction = pick(flat, FIELD_ALIASES["direction"]).lower()
    if direction and direction not in {"outbound", "sent", "send"}:
        return False
    return any(word in text for word in OUTBOUND_WORDS)


def normalize(record: dict[str, Any], source: Path, row_number: int) -> dict[str, str] | None:
    if source.name.startswith("disputefox-active-clients"):
        return None

    flat = flatten(record)
    if not looks_outbound(flat):
        return None

    normalized = {
        "source_file": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
        "source_row": str(row_number),
        "event_id": pick(flat, FIELD_ALIASES["event_id"]),
        "timestamp": pick(flat, FIELD_ALIASES["timestamp"]),
        "status": derive_status(flat),
        "channel": pick(flat, FIELD_ALIASES["channel"]) or "unknown",
        "campaign": pick(flat, FIELD_ALIASES["campaign"]) or "unknown",
        "recipient": pick(flat, FIELD_ALIASES["recipient"]) or "unknown",
        "case_id": pick(flat, FIELD_ALIASES["case_id"]) or "unknown",
        "body": pick(flat, FIELD_ALIASES["body"]),
        "failure": pick(flat, FIELD_ALIASES["failure"]),
    }
    return normalized


def risk_hits(body: str) -> list[str]:
    return sorted({pattern.pattern.replace("\\b", "").replace("(?:d|s)?", "") for pattern in RISKY_PATTERNS if pattern.search(body)})


def business_hour_note(timestamp: str) -> str:
    if not timestamp:
        return ""
    text = timestamp.strip()
    match = re.search(r"T?(\d{1,2}):(\d{2})", text)
    if not match:
        return ""
    hour = int(match.group(1))
    if hour < 9 or hour >= 21:
        return "outside 9 AM - 9 PM review window"
    return ""


def audit_records(records: list[dict[str, str]]) -> dict[str, Any]:
    statuses = Counter(row["status"] or "unknown" for row in records)
    channels = Counter(row["channel"] or "unknown" for row in records)
    campaigns = Counter(row["campaign"] or "unknown" for row in records)
    recipients = Counter(row["recipient"] or "unknown" for row in records)

    duplicate_keys: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in records:
        key = "|".join(
            [
                row.get("recipient", ""),
                row.get("body", ""),
                row.get("campaign", ""),
                row.get("timestamp", "")[:10],
            ]
        )
        duplicate_keys[key].append(row)
    duplicates = [group for group in duplicate_keys.values() if len(group) > 1 and group[0].get("body")]

    risky = []
    after_hours = []
    failures = []
    for row in records:
        hits = risk_hits(row.get("body", ""))
        if hits:
            risky.append((row, hits))
        note = business_hour_note(row.get("timestamp", ""))
        if note:
            after_hours.append((row, note))
        if any(word in row.get("status", "").lower() for word in ("fail", "error", "undeliver", "dead")) or row.get("failure"):
            failures.append(row)

    return {
        "statuses": statuses,
        "channels": channels,
        "campaigns": campaigns,
        "recipients": recipients,
        "duplicates": duplicates,
        "risky": risky,
        "after_hours": after_hours,
        "failures": failures,
    }


def write_csv(records: list[dict[str, str]], stamp: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"autofox-normalized-outbound-{stamp}.csv"
    fieldnames = (
        "source_file",
        "source_row",
        "event_id",
        "timestamp",
        "status",
        "channel",
        "campaign",
        "recipient",
        "case_id",
        "body",
        "failure",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    return path


def top_lines(counter: Counter[str], limit: int = 10) -> list[str]:
    if not counter:
        return ["- None found."]
    return [f"- {name}: {count}" for name, count in counter.most_common(limit)]


def write_markdown(records: list[dict[str, str]], source_files: list[Path], stamp: str) -> Path:
    audit = audit_records(records)
    path = OUTPUT_DIR / f"autofox-audit-{stamp}.md"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    bridge_label = str(BRIDGE_LOG.relative_to(ROOT)) if BRIDGE_LOG.is_relative_to(ROOT) else str(BRIDGE_LOG)
    platform_sources = {
        row.get("source_file", "")
        for row in records
        if row.get("source_file") and row.get("source_file") != bridge_label
    }
    scope = (
        "Full/export-based review"
        if platform_sources
        else "Local FUNDz bridge only. This is not a full AutoFox platform audit yet."
    )

    lines = [
        "# AutoFox Outbound Audit",
        "",
        "## Summary",
        f"- Generated locally: {generated}.",
        f"- Scope: {scope}",
        f"- Source files checked: {len(source_files)}.",
        f"- Outbound records found: {len(records)}.",
        f"- Unique recipients found: {len(audit['recipients'])}.",
        f"- Failed/error outbound records: {len(audit['failures'])}.",
        f"- Possible duplicate sends: {sum(len(group) for group in audit['duplicates'])}.",
        f"- Risky-language records needing review: {len(audit['risky'])}.",
        f"- Outside business-hour records needing review: {len(audit['after_hours'])}.",
        "",
        "## Evidence Sources",
    ]
    if source_files:
        lines.extend(f"- {source.relative_to(ROOT) if source.is_relative_to(ROOT) else source}" for source in source_files)
    else:
        lines.append("- No readable local AutoFox/Credit Tracker export was found.")

    if not records:
        lines.extend(
            [
                "",
                "## Missing Evidence",
                "- No full AutoFox outbound export/API dump is available locally yet.",
                "- Local bridge logs only show messages handled by this FUNDz bridge, not everything the AutoFox platform sends.",
                "- To make this report complete, export AutoFox/DisputeFox sent actions, SMS/email messages, campaign activity, and delivery status into `data/exports/`.",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    lines.extend(["", "## Status Breakdown", *top_lines(audit["statuses"])])
    lines.extend(["", "## Channel Breakdown", *top_lines(audit["channels"])])
    lines.extend(["", "## Campaign / Workflow Breakdown", *top_lines(audit["campaigns"])])

    lines.append("")
    lines.append("## Failures")
    if audit["failures"]:
        for row in audit["failures"][:25]:
            lines.append(
                f"- {row['timestamp'] or 'unknown time'} | {row['status']} | {row['channel']} | "
                f"{row['campaign']} | recipient `{row['recipient']}` | {row['failure'] or 'no failure reason provided'}"
            )
    else:
        lines.append("- No failed/error outbound records were detected.")

    lines.append("")
    lines.append("## Possible Duplicates")
    if audit["duplicates"]:
        for group in audit["duplicates"][:20]:
            first = group[0]
            lines.append(
                f"- {len(group)} sends to `{first['recipient']}` from `{first['campaign']}` on {first['timestamp'][:10] or 'unknown date'}."
            )
    else:
        lines.append("- No same-day duplicate message bodies were detected.")

    lines.append("")
    lines.append("## Risky Language")
    if audit["risky"]:
        for row, hits in audit["risky"][:25]:
            preview = row.get("body", "").replace("\n", " ")[:160]
            lines.append(
                f"- {row['timestamp'] or 'unknown time'} | recipient `{row['recipient']}` | terms: {', '.join(hits)} | `{preview}`"
            )
    else:
        lines.append("- No common credit-repair risk phrases were detected.")

    lines.append("")
    lines.append("## After-Hours Review")
    if audit["after_hours"]:
        for row, note in audit["after_hours"][:25]:
            lines.append(f"- {row['timestamp']} | recipient `{row['recipient']}` | {note}.")
    else:
        lines.append("- No outside-window records were detected from timestamps that included an hour.")

    lines.extend(
        [
            "",
            "## Recommended Fixes",
            "- Review every failed/error send and confirm whether AutoFox retried or needs manual follow-up.",
            "- Review possible duplicates before allowing another campaign resend.",
            "- Rewrite any risky-language templates so they do not promise deletions, approvals, score increases, or guaranteed results.",
            "- Keep this report local; do not paste full client PII into Slack or prompts.",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    source_files = newest_candidate_files()
    normalized: list[dict[str, str]] = []

    for source in source_files:
        records = load_records(source)
        for index, record in enumerate(records, start=1):
            row = normalize(record, source, index)
            if row:
                normalized.append(row)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = write_csv(normalized, stamp)
    md_path = write_markdown(normalized, source_files, stamp)

    print(f"AutoFox outbound records found: {len(normalized)}.")
    print(f"Report: {md_path.relative_to(ROOT)}")
    print(f"Normalized CSV: {csv_path.relative_to(ROOT)}")
    if not normalized:
        print("No full AutoFox send export is available yet. Add the AutoFox/DisputeFox outbound export to data/exports/ and run this again.")


if __name__ == "__main__":
    main()
