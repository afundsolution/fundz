#!/usr/bin/env python3
"""Build a local archive packet for stale DisputeFox next-import clients."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DISPUTEFOX_DIR = ROOT / "data" / "dispute-fox"
OUTPUT_DIR = ROOT / "data" / "local" / "autofox-rollout"
COMMAND_CENTER_DIR = ROOT / "data" / "local" / "command-center"
RECEIPTS_DIR = ROOT / "data" / "local" / "semi-autonomous" / "receipts"

STALE_IMPORT_ARCHIVE_CSV = OUTPUT_DIR / "df-autofox-stale-import-archive-review.csv"
STALE_IMPORT_ARCHIVE_MD = OUTPUT_DIR / "df-autofox-stale-import-archive-review.md"
STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV = OUTPUT_DIR / "df-autofox-stale-import-archive-exclusions.csv"
QUEUE_SUPPRESSIONS_CSV = COMMAND_CENTER_DIR / "fundz-work-queue-suppressions.csv"

ARCHIVE_FIELDS = [
    "client_name",
    "client_key",
    "status",
    "stage_in_process",
    "next_import",
    "next_import_days",
    "onboarding",
    "archive_decision",
    "reason",
    "next_action",
    "source",
]

EXCEPTION_FIELDS = [
    "client_name",
    "client_key",
    "decision",
    "reason",
    "recorded_at",
]

SUPPRESSION_FIELDS = [
    "client_name",
    "client_key",
    "queue_status",
    "owner",
    "next_step",
    "proof_required",
    "proof",
    "reason",
    "evidence",
    "do_not_send_because",
]

LIVE_ARCHIVE_REASONS = {
    "archive_review_completed_credit_monitoring",
}


def normalize_name(name: str) -> str:
    text = re.sub(r"\s*\*\s*new\b", "", (name or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def client_key_for(name: str) -> str:
    normalized = normalize_name(name)
    return f"name:{normalized.replace(' ', '-')}" if normalized else "unknown"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def exclusion_keys(path: Path = STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV) -> set[str]:
    keys: set[str] = set()
    for row in read_csv_rows(path):
        decision = normalize_name(str(row.get("decision") or ""))
        if decision in {"withdrawn", "archive now", "archived"}:
            continue
        key = suppression_lookup_key(row)
        if key:
            keys.add(key)
    return keys


def excluded_archive_rows(
    active_rows: list[dict[str, str]],
    *,
    threshold_days: int,
    source: Path,
    excluded_keys: set[str],
) -> list[dict[str, Any]]:
    rows = build_archive_rows(active_rows, threshold_days=threshold_days, source=source, excluded_keys=set())
    return [dict(row, archive_decision="owner_excluded_from_archive_for_now") for row in rows if row["client_key"] in excluded_keys]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def latest_active_clients_full() -> Path:
    matches = sorted(DISPUTEFOX_DIR.glob("disputefox-active-clients-full-*.csv"))
    if not matches:
        raise FileNotFoundError("No disputefox-active-clients-full CSV found.")
    return matches[-1]


def parse_next_import_days(value: str) -> int | None:
    text = str(value or "").strip()
    match = re.match(r"^(-?\d+)\s+days?$", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def build_archive_rows(
    active_rows: list[dict[str, str]],
    *,
    threshold_days: int,
    source: Path,
    excluded_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_keys = excluded_keys or set()
    rows: list[dict[str, Any]] = []
    for row in active_rows:
        next_import = str(row.get("next_import") or "").strip()
        next_import_days = parse_next_import_days(next_import)
        if next_import_days is None or next_import_days > threshold_days:
            continue
        client_name = str(row.get("client_name") or "").strip()
        if not client_name:
            continue
        client_key = client_key_for(client_name)
        if client_key in excluded_keys:
            continue
        rows.append(
            {
                "client_name": client_name,
                "client_key": client_key,
                "status": str(row.get("status") or "").strip(),
                "stage_in_process": str(row.get("stage_in_process") or "").strip(),
                "next_import": next_import,
                "next_import_days": next_import_days,
                "onboarding": str(row.get("onboarding") or "").strip(),
                "archive_decision": "archive_requested_stale_next_import_owner_directed",
                "reason": (
                    f"Owner rule: archive active DisputeFox clients whose next import is "
                    f"{threshold_days} days or older. Local export shows {next_import}."
                ),
                "next_action": (
                    "Keep out of normal outreach. Complete live DF archive when logged in, "
                    "then record a live archive receipt."
                ),
                "source": display_path(source),
            }
        )
    return sorted(rows, key=lambda item: (int(item["next_import_days"]), str(item["client_name"]).lower()))


def suppression_lookup_key(row: dict[str, str]) -> str:
    key = str(row.get("client_key") or "").strip()
    if key:
        return key
    return client_key_for(str(row.get("client_name") or ""))


def merge_suppressions(
    existing_rows: list[dict[str, str]],
    archive_rows: list[dict[str, Any]],
    *,
    generated_date: str,
    evidence: Path,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    merged = {suppression_lookup_key(row): dict(row) for row in existing_rows if suppression_lookup_key(row)}
    counts = {"created": 0, "updated": 0, "preserved_live_archived": 0}

    for row in archive_rows:
        key = str(row["client_key"])
        existing = merged.get(key, {})
        reason = str(existing.get("reason") or "")
        do_not_send = str(existing.get("do_not_send_because") or "")
        if reason in LIVE_ARCHIVE_REASONS or "Archived in DF" in do_not_send:
            counts["preserved_live_archived"] += 1
            continue
        suppression = {
            "client_name": str(row["client_name"]),
            "client_key": key,
            "queue_status": "Done",
            "owner": "Brandon",
            "next_step": (
                "Archive directed under stale next-import rule. Keep out of normal outreach; "
                "complete live DF archive when authenticated and record the receipt."
            ),
            "proof_required": (
                "Owner instruction plus local DisputeFox next-import evidence. Live DF archive "
                "receipt required before claiming live archive complete."
            ),
            "proof": (
                f"Owner directed archive on {generated_date}; local DisputeFox export shows "
                f"next import {row['next_import']}."
            ),
            "reason": "archive_directed_stale_next_import_30_days",
            "evidence": display_path(evidence),
            "do_not_send_because": "Owner-directed stale next-import archive; no normal outreach.",
        }
        counts["updated" if key in merged else "created"] += 1
        merged[key] = suppression

    return sorted(merged.values(), key=lambda item: str(item.get("client_name") or "").lower()), counts


def remove_excluded_stale_archive_suppressions(
    existing_rows: list[dict[str, str]],
    excluded_keys: set[str],
) -> tuple[list[dict[str, str]], int]:
    kept: list[dict[str, str]] = []
    removed = 0
    for row in existing_rows:
        key = suppression_lookup_key(row)
        reason = str(row.get("reason") or "")
        if key in excluded_keys and reason == "archive_directed_stale_next_import_30_days":
            removed += 1
            continue
        kept.append(row)
    return kept, removed


def mark_live_archived_rows(rows: list[dict[str, Any]], suppression_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    suppressions = {suppression_lookup_key(row): row for row in suppression_rows if suppression_lookup_key(row)}
    marked: list[dict[str, Any]] = []
    for row in rows:
        result = dict(row)
        suppression = suppressions.get(str(row.get("client_key") or ""))
        reason = str((suppression or {}).get("reason") or "")
        do_not_send = str((suppression or {}).get("do_not_send_because") or "")
        if reason in LIVE_ARCHIVE_REASONS or "Archived in DF" in do_not_send:
            result["archive_decision"] = "already_archived_live_confirmed"
            result["reason"] = "Existing local receipt says this client was already archived in live DisputeFox."
            result["next_action"] = "Keep excluded from normal outreach because DF archive was already confirmed."
        marked.append(result)
    return marked


def write_archive_markdown(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    generated_at: str,
    threshold_days: int,
    exceptions: list[dict[str, Any]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exceptions = exceptions or []
    due_for_next = sum(1 for row in rows if str(row.get("status") or "") == "Due For Next Round")
    in_dispute = sum(1 for row in rows if str(row.get("status") or "") == "In Dispute")
    lines = [
        "# DF AutoFox Stale Import Archive Review",
        "",
        f"Generated: {generated_at}",
        "",
        f"Rule: archive active DisputeFox clients whose next import is {threshold_days} days or older.",
        "",
        "This is a local owner-directed archive packet. It keeps these clients out of normal outreach immediately. Live DisputeFox archive completion still needs an authenticated DF page and a receipt.",
        "",
        "## Summary",
        f"- Archive candidates: {len(rows)}",
        f"- Owner exceptions: {len(exceptions)}",
        f"- Due For Next Round: {due_for_next}",
        f"- In Dispute: {in_dispute}",
        "",
        "## Rows",
        "",
        "| Client | Next import | Status | Stage | Decision |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['client_name']} | {row['next_import']} | {row['status']} | "
            f"{row['stage_in_process']} | {row['archive_decision']} |"
        )
    if exceptions:
        lines.extend(
            [
                "",
                "## Owner Exceptions",
                "",
                "These clients meet the stale-import rule, but Brandon explicitly said not to archive them right now.",
                "",
                "| Client | Next import | Status | Stage | Decision |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in exceptions:
            lines.append(
                f"| {row['client_name']} | {row['next_import']} | {row['status']} | "
                f"{row['stage_in_process']} | {row['archive_decision']} |"
            )
    lines.extend(
        [
            "",
            "## Operating Rule",
            "",
            "Do not reopen these clients for normal outreach. Complete live DF archive only from an authenticated DisputeFox page and record proof before calling the live archive done.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_receipt(summary: dict[str, Any], *, generated_at: str) -> Path:
    stamp = re.sub(r"[^0-9]", "", generated_at)[:14] or time.strftime("%Y%m%d%H%M%S")
    path = RECEIPTS_DIR / f"fundz-df-stale-import-archive-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_packet(
    *,
    active_clients_csv: Path | None = None,
    threshold_days: int = -30,
    exclusions_csv: Path = STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV,
    generated_at: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    source = active_clients_csv or latest_active_clients_full()
    generated_at = generated_at or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    generated_date = generated_at[:10]
    active_rows = read_csv_rows(source)
    excluded_keys = exclusion_keys(exclusions_csv)
    existing_suppressions, removed_excluded_suppressions = remove_excluded_stale_archive_suppressions(
        read_csv_rows(QUEUE_SUPPRESSIONS_CSV),
        excluded_keys,
    )
    exceptions = excluded_archive_rows(
        active_rows,
        threshold_days=threshold_days,
        source=source,
        excluded_keys=excluded_keys,
    )
    rows = mark_live_archived_rows(
        build_archive_rows(active_rows, threshold_days=threshold_days, source=source, excluded_keys=excluded_keys),
        existing_suppressions,
    )
    suppressions, suppression_counts = merge_suppressions(
        existing_suppressions,
        rows,
        generated_date=generated_date,
        evidence=STALE_IMPORT_ARCHIVE_CSV,
    )
    live_archive_confirmed_candidates = sum(
        1 for row in rows if str(row.get("archive_decision") or "") == "already_archived_live_confirmed"
    )
    live_archive_pending_candidates = len(rows) - live_archive_confirmed_candidates
    live_archive_completed = bool(rows) and live_archive_pending_candidates == 0
    summary = {
        "generated_at": generated_at,
        "threshold_days": threshold_days,
        "source": display_path(source),
        "archive_candidates": len(rows),
        "owner_exceptions": len(exceptions),
        "live_archive_confirmed_candidates": live_archive_confirmed_candidates,
        "live_archive_pending_candidates": live_archive_pending_candidates,
        "removed_excluded_archive_suppressions": removed_excluded_suppressions,
        "suppression_counts": suppression_counts,
        "archive_packet_csv": display_path(STALE_IMPORT_ARCHIVE_CSV),
        "archive_packet_md": display_path(STALE_IMPORT_ARCHIVE_MD),
        "archive_exclusions_csv": display_path(exclusions_csv),
        "queue_suppressions": display_path(QUEUE_SUPPRESSIONS_CSV),
        "live_archive_completed": live_archive_completed,
        "live_archive_note": (
            "All archive candidates have live DisputeFox archive confirmation in local suppressions."
            if live_archive_completed
            else "Live DisputeFox archive requires authenticated browser proof per client."
        ),
    }
    if write:
        write_csv(STALE_IMPORT_ARCHIVE_CSV, rows, ARCHIVE_FIELDS)
        write_archive_markdown(
            STALE_IMPORT_ARCHIVE_MD,
            rows,
            generated_at=generated_at,
            threshold_days=threshold_days,
            exceptions=exceptions,
        )
        write_csv(QUEUE_SUPPRESSIONS_CSV, suppressions, SUPPRESSION_FIELDS)
        receipt = write_receipt(summary, generated_at=generated_at)
        summary["receipt"] = display_path(receipt)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-clients-csv", type=Path, default=None)
    parser.add_argument("--exclusions-csv", type=Path, default=STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV)
    parser.add_argument("--threshold-days", type=int, default=-30)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = build_packet(
        active_clients_csv=args.active_clients_csv,
        threshold_days=args.threshold_days,
        exclusions_csv=args.exclusions_csv,
        generated_at=args.generated_at,
        write=not args.dry_run,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
