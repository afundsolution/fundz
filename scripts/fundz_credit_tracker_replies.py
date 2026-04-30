#!/usr/bin/env python3
"""Draft FUNDz client replies for credit-tracker records from local exports."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (ROOT / "data" / "dispute-fox", ROOT / "data" / "exports")
OUTPUT_DIR = ROOT / "data" / "local" / "credit-tracker-replies"

PENDING_WORDS = ("pending", "queued", "scheduled", "dead", "error", "failed")
TRACKER_WORDS = ("credit tracker", "credit-tracker", "credit_tracker")


def newest_files() -> list[Path]:
    files: list[Path] = []
    for source_dir in SOURCE_DIRS:
        files.extend(
            path
            for path in source_dir.glob("*")
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in {".csv", ".json", ".jsonl"}
        )
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


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
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
    return records


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_records(path: Path) -> list[dict]:
    try:
        if path.suffix.lower() in {".json", ".jsonl"}:
            return read_jsonish(path)
        if path.suffix.lower() == ".csv":
            return read_csv(path)
    except (OSError, json.JSONDecodeError, csv.Error):
        return []
    return []


def value_for(record: dict, names: tuple[str, ...]) -> str:
    lower_map = {str(key).lower().strip(): value for key, value in record.items()}
    for name in names:
        value = lower_map.get(name.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def record_text(record: dict) -> str:
    return " ".join(str(value).lower() for value in record.values() if value not in (None, ""))


def is_credit_tracker_record(record: dict) -> bool:
    text = record_text(record)
    return any(word in text for word in TRACKER_WORDS)


def first_name(record: dict) -> str:
    name = value_for(
        record,
        (
            "first_name",
            "firstname",
            "client_first_name",
            "contact_first_name",
            "name",
            "client",
            "contact",
            "full_name",
        ),
    )
    if not name:
        return "there"
    clean = re.sub(r"\s+", " ", name).strip()
    return clean.split(" ")[0].strip(",") or "there"


def plain_status(record: dict) -> str:
    status = value_for(record, ("status", "state", "stage", "credit_status", "tracker_status"))
    bureau = value_for(record, ("bureau", "credit_bureau"))
    item = value_for(record, ("item", "account", "credit_item", "tradeline", "creditor"))

    pieces: list[str] = []
    if item:
        pieces.append(f"we are tracking {item}")
    else:
        pieces.append("we are tracking your credit file")
    if bureau:
        pieces.append(f"with {bureau}")
    if status:
        pieces.append(f"and the current status is {status}")
    return " ".join(pieces) + "."


def next_step(record: dict) -> str:
    explicit = value_for(record, ("next_step", "next action", "next_action", "follow_up", "followup", "owner_next_step"))
    if explicit:
        return f"Next step: {explicit}."

    status = value_for(record, ("status", "state", "stage", "credit_status", "tracker_status")).lower()
    if any(word in status for word in ("failed", "error", "dead")):
        return "Our team needs to review the tracker item before sending the next update."
    if any(word in status for word in ("queued", "pending", "scheduled")):
        return "The next update is queued for review."
    return "The next step is to keep monitoring the item and update you when the tracker changes."


def review_note(record: dict) -> str:
    status = value_for(record, ("status", "state", "stage", "credit_status", "tracker_status")).lower()
    if any(word in status for word in PENDING_WORDS):
        return "Review before sending: tracker item is not confirmed complete."
    if first_name(record) == "there":
        return "Review before sending: client name was not found."
    return "Ready for owner review."


def draft_reply(record: dict) -> str:
    return (
        f"Hi {first_name(record)}, quick update from FUNDz: "
        f"{plain_status(record)} {next_step(record)} "
        "We will keep tracking this and follow up when there is movement."
    )


def build_drafts(records: list[dict], source: Path) -> list[dict[str, str]]:
    drafts = []
    for index, record in enumerate(records, start=1):
        if not is_credit_tracker_record(record):
            continue
        drafts.append(
            {
                "source_file": str(source.relative_to(ROOT)),
                "source_row": str(index),
                "client": first_name(record),
                "status": value_for(record, ("status", "state", "stage", "credit_status", "tracker_status")) or "unknown",
                "review_note": review_note(record),
                "draft_reply": draft_reply(record),
            }
        )
    return drafts


def write_outputs(drafts: list[dict[str, str]]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = OUTPUT_DIR / f"credit-tracker-replies-{stamp}.csv"
    txt_path = OUTPUT_DIR / f"credit-tracker-replies-{stamp}.txt"

    fieldnames = ("source_file", "source_row", "client", "status", "review_note", "draft_reply")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(drafts)

    lines = ["FUNDz credit tracker reply drafts", ""]
    for draft in drafts:
        lines.extend(
            [
                f"Source: {draft['source_file']} row {draft['source_row']}",
                f"Client: {draft['client']}",
                f"Status: {draft['status']}",
                f"Note: {draft['review_note']}",
                f"Reply: {draft['draft_reply']}",
                "",
            ]
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path


def main() -> None:
    all_drafts: list[dict[str, str]] = []
    for source in newest_files():
        records = load_records(source)
        all_drafts.extend(build_drafts(records, source))

    if not all_drafts:
        print("No credit-tracker client records were found in local Dispute Fox/export files yet.")
        print("Add the latest export to data/dispute-fox/ or data/exports/, then run this again.")
        return

    csv_path, txt_path = write_outputs(all_drafts)
    needs_review = sum(1 for draft in all_drafts if draft["review_note"].startswith("Review before sending"))
    print(f"Drafted {len(all_drafts)} credit-tracker client replie(s).")
    print(f"Needs owner review before sending: {needs_review}.")
    print(f"CSV: {csv_path.relative_to(ROOT)}")
    print(f"Text: {txt_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
