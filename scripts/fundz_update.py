#!/usr/bin/env python3
"""Generate a plain-English FUNDz update from local project and Dispute Fox files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fundz_operational_state import (
    build_client_index,
    build_operational_state,
    find_client_matches,
    find_index_matches,
    format_client_update,
    index_entry_to_client,
    write_client_index,
    write_json,
    write_summary_csv,
)
from fundz_client_billing_lookup import build_lookup as build_billing_lookup, monitoring_reply_text


ROOT = Path(__file__).resolve().parents[1]
DISPUTE_FOX_DIR = ROOT / "data" / "dispute-fox"
EXPORT_DIR = ROOT / "data" / "exports"
AUTONOMY_LOG = ROOT / "data" / "local" / "autonomy" / "autonomy-events.jsonl"
AUTONOMY_PROPOSALS = ROOT / "data" / "local" / "autonomy" / "proposals"
AUTONOMY_QUARANTINE = ROOT / "data" / "local" / "autonomy" / "quarantine"
OPERATIONAL_STATE = ROOT / "data" / "local" / "fundz-client-state.json"
SEMI_AUTONOMOUS_QUEUE = ROOT / "data" / "local" / "semi-autonomous" / "fundz-action-queue.json"
DEFAULT_SUMMARY_CSV = ROOT / "data" / "local" / "fundz-client-state-summary.csv"
DEFAULT_CLIENT_INDEX = ROOT / "data" / "local" / "fundz-client-index.json"


def newest_file(paths: list[Path]) -> Path | None:
    files = [path for path in paths if path.is_file() and not path.name.startswith(".")]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def read_jsonish(path: Path) -> list[dict]:
    records: list[dict] = []
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
    if path.suffix.lower() == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                item = json.loads(line)
                if isinstance(item, dict):
                    records.append(item)
    return records


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_records(path: Path | None) -> list[dict]:
    if path is None:
        return []
    suffix = path.suffix.lower()
    try:
        if suffix in {".json", ".jsonl"}:
            return read_jsonish(path)
        if suffix == ".csv":
            return read_csv(path)
    except (OSError, json.JSONDecodeError, csv.Error):
        return []
    return []


def value_for(record: dict, names: tuple[str, ...]) -> str:
    lower_map = {str(key).lower(): value for key, value in record.items()}
    for name in names:
        value = lower_map.get(name.lower())
        if value not in (None, ""):
            return str(value)
    return "unknown"


def summarize_records(records: list[dict]) -> tuple[list[str], list[str]]:
    if not records:
        return [], ["No readable Dispute Fox records were found yet."]

    statuses = Counter(value_for(row, ("status", "state", "stage")) for row in records)
    campaigns = Counter(value_for(row, ("campaign", "action", "workflow", "name")) for row in records)

    needs_attention = []
    pending_words = ("pending", "queued", "scheduled", "dead", "error", "failed")
    tracker_words = ("credit tracker", "credit-tracker", "credit_tracker")
    for status, count in statuses.items():
        if any(word in status.lower() for word in pending_words):
            needs_attention.append(f"{count} record(s) are marked `{status}`.")

    credit_tracker_count = sum(
        1
        for row in records
        if any(
            word in " ".join(str(value).lower() for value in row.values() if value not in (None, ""))
            for word in tracker_words
        )
    )
    if credit_tracker_count:
        needs_attention.append(
            f"{credit_tracker_count} credit-tracker record(s) were found. Run `scripts/fundz_credit_tracker_replies.py` to draft client replies."
        )

    facts = [
        f"Dispute Fox records available: {len(records)}.",
        "Top statuses: " + ", ".join(f"{status}: {count}" for status, count in statuses.most_common(5)) + ".",
    ]
    if campaigns:
        facts.append(
            "Top campaigns/actions: "
            + ", ".join(f"{name}: {count}" for name, count in campaigns.most_common(5))
            + "."
        )

    return facts, needs_attention


def latest_audit_summary() -> list[str]:
    audits = sorted(
        list(ROOT.glob("*Audit*.md")) + list((ROOT / "data" / "local" / "autofox-audits").glob("*.md")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not audits:
        return []

    audit = audits[0]
    lines = audit.read_text(encoding="utf-8").splitlines()
    useful = []
    capture = False
    for line in lines:
        if line.strip() == "## Summary":
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture and line.strip().startswith("- "):
            useful.append(line.strip()[2:])
    label = audit.name if audit.parent == ROOT else str(audit.relative_to(ROOT))
    return [f"Latest audit: {label}."] + useful[:8]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def latest_autonomy_summary() -> list[str]:
    lines: list[str] = []
    records = read_jsonl(AUTONOMY_LOG)
    proposals = sorted(AUTONOMY_PROPOSALS.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    quarantined = sorted(AUTONOMY_QUARANTINE.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)

    if not records and not proposals and not quarantined:
        return []

    if records:
        latest = records[-1]
        lines.append(
            f"Autonomy loop last ran: {latest.get('time', 'unknown time')} ({latest.get('kind', 'unknown event')})."
        )
    if proposals:
        lines.append(f"Latest autonomy proposal: {proposals[0].relative_to(ROOT)}.")
    if quarantined:
        lines.append(f"Quarantined events needing review: {len(quarantined)}.")
    return lines


def latest_operational_state_summary() -> list[str]:
    if not OPERATIONAL_STATE.exists():
        return []
    try:
        state = json.loads(OPERATIONAL_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
    summary = state.get("summary", {}) if isinstance(state, dict) else {}
    if not isinstance(summary, dict):
        return []

    lines = [
        f"Master client brain: {OPERATIONAL_STATE.relative_to(ROOT)}.",
        f"Client profiles: {summary.get('clients', 0)}; active clients: {summary.get('active_clients', 0)}.",
        (
            f"Operational queues: due next round {summary.get('due_for_next_round', 0)}, "
            f"in dispute {summary.get('in_dispute', 0)}, missing next import {summary.get('missing_next_import', 0)}."
        ),
        (
            f"Send history linked: email {summary.get('email_sends_linked', 0)}, "
            f"SMS {summary.get('sms_sends_linked', 0)}."
        ),
    ]
    generated_at = metadata.get("generated_at")
    if generated_at:
        lines.append(f"Client brain generated: {generated_at}.")
    return lines


def latest_semi_autonomous_summary() -> list[str]:
    if not SEMI_AUTONOMOUS_QUEUE.exists():
        return []
    try:
        queue = json.loads(SEMI_AUTONOMOUS_QUEUE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(queue, dict):
        return []

    summary = queue.get("summary", {})
    if not isinstance(summary, dict):
        return []
    pieces = [f"{name} {count}" for name, count in summary.items()]
    lines = [f"Semi-autonomous queue: {SEMI_AUTONOMOUS_QUEUE.relative_to(ROOT)}."]
    if pieces:
        lines.append("Semi-autonomous actions: " + ", ".join(pieces) + ".")
    generated_at = queue.get("generated_at")
    if generated_at:
        lines.append(f"Semi-autonomous queue generated: {generated_at}.")
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="", help="Return a stored-data update for one client name or email.")
    parser.add_argument(
        "--reply-only",
        action="store_true",
        help="Print a concise ready-to-send owner reply for a named client lookup.",
    )
    return parser.parse_args()


def format_owner_client_reply(client: dict) -> str:
    history = client.get("send_history", {})
    dispute_items = client.get("dispute_items", {})
    flags = set(client.get("operational_flags", []))
    name = client.get("client_name") or "this client"

    if "history_only_record" in flags:
        return (
            f"{name}: stored FUNDz history found, but this client is not in the latest active-client export. "
            f"Current status/stage/assignment are not shown. "
            f"Linked history: {history.get('email_count', 0)} email(s), {history.get('sms_count', 0)} SMS. "
            f"Disputes showing in the export: {dispute_items.get('all_items', 0)} total, "
            f"{dispute_items.get('in_dispute_count', 0)} in dispute, "
            f"{dispute_items.get('deleted_count', 0)} deleted, "
            f"{dispute_items.get('repaired_count', 0)} repaired. "
            "Next move: stored communication history exists, but the active-client export does not include current status."
        )

    parts = [
        f"{name}: status is {client.get('status') or 'unknown'}",
        f"stage is {client.get('stage_in_process') or 'not shown'}",
        f"next import is {client.get('next_import') or 'not shown'}",
        f"assigned to {client.get('assigned_to') or 'not shown'}",
        f"onboarding is {client.get('onboarding') or 'not shown'}",
        (
            f"disputes: {dispute_items.get('all_items', 0)} total, "
            f"{dispute_items.get('in_dispute_count', 0)} in dispute, "
            f"{dispute_items.get('deleted_count', 0)} deleted, "
            f"{dispute_items.get('repaired_count', 0)} repaired"
        ),
        f"linked history: {history.get('email_count', 0)} email(s), {history.get('sms_count', 0)} SMS",
    ]
    next_move = client.get("recommended_next_action") or "Review client file."
    reply = ". ".join(parts) + f". Next move: {next_move}"
    monitoring = (build_billing_lookup(str(name)).get("scorefusion_evidence") or {}).get("df_credit_monitoring") or {}
    if monitoring:
        reply += f" Credit monitoring: {monitoring_reply_text(build_billing_lookup(str(name)))}"
    return reply


def print_client_update(client_query: str, reply_only: bool = False) -> None:
    state = build_operational_state()
    write_json(OPERATIONAL_STATE, state)
    write_summary_csv(DEFAULT_SUMMARY_CSV, state["clients"])
    write_client_index(DEFAULT_CLIENT_INDEX, state)
    index = build_client_index(state)
    index_matches = find_index_matches(index, client_query)
    matches = [index_entry_to_client(match) for match in index_matches] if index_matches else find_client_matches(state, client_query)
    if len(matches) == 1:
        print(format_owner_client_reply(matches[0]) if reply_only else format_client_update(matches[0]))
        return
    if len(matches) > 1:
        print(f"Multiple clients matched {client_query!r}:")
        for client in matches:
            print(f"- {client.get('client_name')} | {client.get('status')} | {client.get('email')}")
        return
    print(f"No matching stored DisputeFox record was found for {client_query!r}.")


def main() -> None:
    args = parse_args()
    if args.client:
        print_client_update(args.client, reply_only=args.reply_only)
        return

    dispute_fox_file = newest_file(list(DISPUTE_FOX_DIR.glob("*")))
    export_file = newest_file(list(EXPORT_DIR.glob("*")))
    source_file = dispute_fox_file or export_file
    records = load_records(source_file)
    facts, needs_attention = summarize_records(records)
    audit = latest_audit_summary()

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("Here is the latest FUNDz update:")
    print()
    print("Done:")
    print("- Hybrid local setup is in place: local data, exports, logs, backups, secrets, and Git-safe files are separated.")
    print("- The assistant knowledge area is ready for Dispute Fox data.")
    if source_file:
        print(f"- Latest data source found: {source_file.relative_to(ROOT)}.")
    else:
        print("- No Dispute Fox/export data file has been added yet.")
    print()
    print("Needs attention:")
    if needs_attention:
        for item in needs_attention:
            print(f"- {item}")
    else:
        print("- No urgent Dispute Fox record issues were detected from readable local data.")
    print()
    print("Pending:")
    for item in facts:
        print(f"- {item}")
    for item in audit:
        print(f"- {item}")
    for item in latest_operational_state_summary():
        print(f"- {item}")
    for item in latest_semi_autonomous_summary():
        print(f"- {item}")
    for item in latest_autonomy_summary():
        print(f"- {item}")
    print()
    print("Next move:")
    if not dispute_fox_file:
        print("- Add the latest Dispute Fox export to data/dispute-fox/ so FUNDz can answer from current Dispute Fox information.")
    else:
        print("- Review the needs-attention items, then connect Dispute Fox directly or keep dropping fresh exports into data/dispute-fox/.")
    print()
    print(f"Generated locally: {generated}")


if __name__ == "__main__":
    main()
