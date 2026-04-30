#!/usr/bin/env python3
"""Generate a plain-English FUNDz update from local project and Dispute Fox files."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISPUTE_FOX_DIR = ROOT / "data" / "dispute-fox"
EXPORT_DIR = ROOT / "data" / "exports"


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
    audits = sorted(ROOT.glob("*Audit*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
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
    return [f"Latest audit: {audit.name}."] + useful[:8]


def main() -> None:
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
