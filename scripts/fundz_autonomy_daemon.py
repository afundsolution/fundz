#!/usr/bin/env python3
"""Local PR-gated autonomy loop for FUNDz bridge health."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.local"
BRIDGE_LOG = ROOT / "logs" / "credit-tracker-bridge.jsonl"
SEEN_EVENTS = ROOT / "data" / "local" / "credit-tracker-bridge" / "seen-events.txt"
AUTOFOX_AUDITS = ROOT / "data" / "local" / "autofox-audits"
AUTONOMY_DIR = ROOT / "data" / "local" / "autonomy"
QUARANTINE_DIR = AUTONOMY_DIR / "quarantine"
PROPOSAL_DIR = AUTONOMY_DIR / "proposals"
AUTONOMY_LOG = AUTONOMY_DIR / "autonomy-events.jsonl"

RISKY_REPLY_PATTERNS = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.I),
    re.compile(r"\bdelete(?:d|s)?\b", re.I),
    re.compile(r"\bremove(?:d|s)?\b", re.I),
    re.compile(r"\bboost\b", re.I),
    re.compile(r"\bapproval\b", re.I),
    re.compile(r"\bscore increase\b", re.I),
    re.compile(r"\bresults? (?:are|is) guaranteed\b", re.I),
    re.compile(r"\bwe (?:will|can) fix\b", re.I),
)

SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|authorization|password|api[_-]?key|refresh|firebase|credential|cookie)",
    re.I,
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")


@dataclass(frozen=True)
class FailureDiagnosis:
    category: str
    issue: str
    risk: str
    suggested_fix: str
    likely_files: tuple[str, ...]
    test_cases: tuple[str, ...]


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def stable_id(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return "[redacted-phone]"
    return f"[redacted-phone:***{digits[-4:]}]"


def redact_text(value: str) -> str:
    value = EMAIL_RE.sub("[redacted-email]", value)
    return PHONE_RE.sub(lambda match: mask_phone(match.group(0)), value)


def redact_sensitive(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY_RE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key): redact_sensitive(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item, key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def risky_language_hits(text: str) -> list[str]:
    hits = []
    for pattern in RISKY_REPLY_PATTERNS:
        match = pattern.search(text or "")
        if match:
            hits.append(match.group(0).lower())
    return sorted(set(hits))


def log_autonomy_event(kind: str, payload: dict[str, Any]) -> None:
    AUTONOMY_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "kind": kind,
        **redact_sensitive(payload),
    }
    with AUTONOMY_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")


def quarantine_event(reason: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> Path:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "reason": reason,
        "context": redact_sensitive(context or {}),
        "payload": redact_sensitive(payload),
    }
    path = QUARANTINE_DIR / f"quarantine-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{stable_id(entry)}.json"
    path.write_text(json.dumps(entry, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_autonomy_event("quarantined_payload", {"reason": reason, "path": display_path(path)})
    return path


def classify_send_failure(status: int | None = None, error: str = "", body: str = "") -> FailureDiagnosis:
    text = f"{error} {body}".lower()
    if status == 401:
        return FailureDiagnosis(
            "config issue",
            "Outbound API authorization failed.",
            "Live replies may stop until the API token or refresh flow is corrected.",
            "Verify the HighLevel/Credit Tracker token, refresh token, auth scheme, and location-level integration.",
            ("scripts/fundz_credit_tracker_bridge.py", ".env.local"),
            ("401 send failure refreshes once when a refresh token exists.", "401 without refresh token creates a proposal."),
        )
    if status and 400 <= status < 500:
        return FailureDiagnosis(
            "payload mapping issue",
            f"Outbound API rejected the request with HTTP {status}.",
            "FUNDz may be sending a payload shape the provider does not accept.",
            "Compare the provider response to CREDIT_TRACKER_OUTBOUND_TEMPLATE and adjust field names in .env.local.",
            (".env.local", "scripts/fundz_credit_tracker_bridge.py"),
            ("Invalid outbound template failure is quarantined.", "Provider 4xx response produces a proposal."),
        )
    if status and status >= 500:
        return FailureDiagnosis(
            "provider/API issue",
            f"Outbound API returned HTTP {status}.",
            "The provider may be temporarily unavailable; duplicate sends are possible if retries are unmanaged.",
            "Retry with bounded backoff, then quarantine the event if the provider keeps failing.",
            ("scripts/fundz_credit_tracker_bridge.py",),
            ("5xx response retries only up to the configured limit.", "Exhausted retries create a quarantine record."),
        )
    if "timed out" in text or "timeout" in text or "temporarily unavailable" in text:
        return FailureDiagnosis(
            "provider/API issue",
            "Outbound API request timed out or was unavailable.",
            "The client may not receive an update until the provider recovers.",
            "Retry with bounded backoff and leave a redacted quarantine note after repeated failures.",
            ("scripts/fundz_credit_tracker_bridge.py",),
            ("Timeout retries with backoff.", "Exhausted timeout retries produce a proposal."),
        )
    return FailureDiagnosis(
        "code defect",
        "Unexpected bridge error while processing a webhook.",
        "The bridge may skip or fail valid client messages until this is reviewed.",
        "Inspect the redacted error and add a regression test before changing bridge behavior.",
        ("scripts/fundz_credit_tracker_bridge.py",),
        ("Unexpected webhook error produces a redacted proposal.",),
    )


def proposal_path(title: str, evidence: list[dict[str, Any]]) -> Path:
    digest = stable_id({"title": title, "evidence": evidence})
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "proposal"
    return PROPOSAL_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}-{digest}.md"


def write_proposal(
    title: str,
    diagnosis: FailureDiagnosis,
    evidence: list[dict[str, Any]],
    *,
    extra_tests: list[str] | None = None,
) -> Path:
    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    path = proposal_path(title, evidence)
    tests = list(diagnosis.test_cases)
    if extra_tests:
        tests.extend(extra_tests)
    lines = [
        f"# {title}",
        "",
        f"Generated locally: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Issue",
        f"- Category: {diagnosis.category}",
        f"- {diagnosis.issue}",
        "",
        "## Evidence",
    ]
    if evidence:
        for item in evidence[:10]:
            lines.append(f"- `{json.dumps(redact_sensitive(item), ensure_ascii=True, sort_keys=True, default=str)}`")
    else:
        lines.append("- No specific evidence was captured.")
    lines.extend(
        [
            "",
            "## Risk",
            f"- {diagnosis.risk}",
            "",
            "## Suggested Fix",
            f"- {diagnosis.suggested_fix}",
            "- Keep code changes PR-gated. The autonomy daemon must not apply this fix directly.",
            "",
            "## Files Likely Affected",
            *[f"- `{path_name}`" for path_name in diagnosis.likely_files],
            "",
            "## Test Cases",
            *[f"- {test}" for test in tests],
            "",
            "## Approval Gate",
            "- Human review is required before any code or live configuration change.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_autonomy_event("proposed_improvement", {"title": title, "path": display_path(path)})
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def recent_audit_findings() -> list[str]:
    audits = sorted(AUTOFOX_AUDITS.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not audits:
        return []
    lines = audits[0].read_text(encoding="utf-8").splitlines()
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
    return [f"Latest AutoFox audit: {audits[0].relative_to(ROOT)}."] + useful[:6]


def analyze_bridge_logs(records: list[dict[str, Any]], threshold: int) -> list[Path]:
    proposals: list[Path] = []
    failures = [
        record
        for record in records
        if record.get("kind") in {"reply_failed", "send_failed", "webhook_error"}
    ]
    failure_keys = Counter(
        (
            record.get("status"),
            str(record.get("error") or record.get("body") or "")[:80],
            record.get("kind"),
        )
        for record in failures
    )
    for (status, error, kind), count in failure_keys.items():
        if count < threshold:
            continue
        diagnosis = classify_send_failure(
            int(status) if isinstance(status, int) or str(status).isdigit() else None,
            error=str(error),
        )
        evidence = [
            {
                "kind": record.get("kind"),
                "status": record.get("status"),
                "error": record.get("error"),
                "body": record.get("body"),
                "time": record.get("time"),
            }
            for record in failures
            if (record.get("status"), str(record.get("error") or record.get("body") or "")[:80], record.get("kind"))
            == (status, error, kind)
        ]
        proposals.append(write_proposal(f"Repeated {kind} failures need review", diagnosis, evidence))

    risky_blocks = [record for record in records if record.get("kind") == "reply_blocked_risky_language"]
    if len(risky_blocks) >= threshold:
        diagnosis = FailureDiagnosis(
            "reply safety issue",
            "Generated replies included risky credit-repair language.",
            "Unsafe claims could be sent to clients if reply rules are loosened.",
            "Tighten reply-generation rules and keep risky-language blocking enabled.",
            ("scripts/fundz_credit_tracker_replies.py", "assistant/fundz-assistant.md"),
            ("Risky phrases are blocked before send.", "Safe reply wording still sends in dry-run."),
        )
        proposals.append(write_proposal("Risky reply language needs safer rules", diagnosis, risky_blocks[:10]))

    return proposals


def summarize_autonomy(records: list[dict[str, Any]], proposals: list[Path]) -> list[str]:
    counts = Counter(str(record.get("kind", "unknown")) for record in records)
    lines = [
        f"Bridge log events reviewed: {len(records)}.",
        "Recent bridge event types: " + ", ".join(f"{name}: {count}" for name, count in counts.most_common(8)) + ".",
        f"New improvement proposals: {len(proposals)}.",
    ]
    if SEEN_EVENTS.exists():
        seen_count = len([line for line in SEEN_EVENTS.read_text(encoding="utf-8").splitlines() if line.strip()])
        lines.append(f"Seen/deduped bridge keys tracked: {seen_count}.")
    lines.extend(recent_audit_findings())
    return lines


def run_once() -> list[str]:
    load_env_file()
    threshold = env_int("FUNDZ_AUTONOMY_FAILURE_THRESHOLD", 3)
    records = read_jsonl(BRIDGE_LOG)
    proposals = analyze_bridge_logs(records, threshold)
    summary = summarize_autonomy(records, proposals)
    log_autonomy_event("autonomy_review_completed", {"summary": summary, "proposal_count": len(proposals)})
    return summary


def run_watch() -> None:
    load_env_file()
    if not env_bool("FUNDZ_AUTONOMY_ENABLED", False):
        print("FUNDz autonomy is disabled. Set FUNDZ_AUTONOMY_ENABLED=true in .env.local to run --watch.")
        return
    interval = env_int("FUNDZ_AUTONOMY_INTERVAL_SECONDS", 300)
    print(f"FUNDz autonomy daemon watching every {interval} seconds.")
    while True:
        for line in run_once():
            print(f"- {line}")
        time.sleep(max(interval, 30))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local PR-gated FUNDz autonomy loop.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Review current logs once, then exit.")
    mode.add_argument("--watch", action="store_true", help="Run continuously when FUNDZ_AUTONOMY_ENABLED=true.")
    args = parser.parse_args()

    if args.watch:
        run_watch()
        return
    for item in run_once():
        print(f"- {item}")


if __name__ == "__main__":
    main()
