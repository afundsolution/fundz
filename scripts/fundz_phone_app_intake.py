#!/usr/bin/env python3
"""Build a money/productivity intake board from approved phone-app sources.

This is the safe bridge for "other apps on my phone." It does not scrape an
entire phone. It consumes approved exports/connectors and turns business/money
signals into decision-ready intake rows.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"
IMPORT_DIR = ROOT / "data" / "local" / "phone-app-imports"

PERSONAL_PHONE_QUEUE_CSV = OUTPUT_DIR / "fundz-personal-phone-message-queue.csv"
PERSONAL_PHONE_TRIAGE_CSV = OUTPUT_DIR / "fundz-personal-phone-needs-reply-triage.csv"
INTAKE_GOVERNOR_CANDIDATES_CSV = OUTPUT_DIR / "fundz-intake-governor-candidates.csv"

PHONE_APP_INTAKE_JSON = OUTPUT_DIR / "fundz-phone-app-intake.json"
PHONE_APP_INTAKE_CSV = OUTPUT_DIR / "fundz-phone-app-intake.csv"
PHONE_APP_INTAKE_MD = OUTPUT_DIR / "fundz-phone-app-intake.md"
PHONE_APP_REGISTRY_MD = OUTPUT_DIR / "fundz-phone-app-intake-registry.md"
PHONE_APP_DASHBOARD_HTML = OUTPUT_DIR / "fundz-phone-app-intake-dashboard.html"

MONEY_KEYWORDS = {
    "payment",
    "paid",
    "pay",
    "invoice",
    "refund",
    "charge",
    "chargeback",
    "card",
    "billing",
    "bill",
    "deposit",
    "zelle",
    "cash app",
    "cashapp",
    "venmo",
    "stripe",
    "square",
    "subscription",
    "past due",
    "declined",
}

REVENUE_KEYWORDS = {
    "lead",
    "signup",
    "sign up",
    "consultation",
    "appointment",
    "schedule",
    "new client",
    "interested",
    "apply",
    "application",
    "price",
    "cost",
    "quote",
}

CLIENT_WORK_KEYWORDS = {
    "credit",
    "dispute",
    "report",
    "score",
    "round",
    "delete",
    "collection",
    "tradeline",
    "login",
    "app",
    "portal",
}

RISK_KEYWORDS = {
    "cancel",
    "refund",
    "complaint",
    "angry",
    "scam",
    "lawsuit",
    "attorney",
    "chargeback",
    "fraud",
    "stop",
}

PROOF_KEYWORDS = {
    "receipt",
    "screenshot",
    "proof",
    "sent",
    "done",
    "completed",
    "attached",
    "confirmation",
}

SECURITY_KEYWORDS = {
    "verification code",
    "security code",
    "one-time code",
    "requests this code",
    "use code",
    "2fa",
    "password",
    "passcode",
}

APP_REGISTRY = [
    {
        "app": "Messages",
        "status": "active",
        "source": "Mac Messages business-only import",
        "action": "Run make personal-phone-queue, then make phone-app-intake.",
        "money_use": "Catches client texts, missed replies, payment/refund/cancel mentions, and app/login issues.",
        "safety": "Business keyword/client matches only; no full personal archive sharing.",
    },
    {
        "app": "Phone / Voicemail / Call Recordings",
        "status": "manual export",
        "source": "Export recordings/transcripts into data/local/phone-app-imports/",
        "action": "Drop transcript TXT/CSV/JSON files into the import folder.",
        "money_use": "Turns promises, follow-ups, billing issues, and sales calls into queue rows.",
        "safety": "No call audio is processed unless a recording/transcript is exported intentionally.",
    },
    {
        "app": "Notes",
        "status": "manual export",
        "source": "Export Call Recordings notes or meeting notes into the import folder.",
        "action": "Export only business notes/transcripts.",
        "money_use": "Captures commitments, client next steps, proof notes, and sales context.",
        "safety": "Do not export personal notes.",
    },
    {
        "app": "Photos / Screenshots",
        "status": "manual export",
        "source": "Save business screenshots/receipts into data/local/phone-app-imports/",
        "action": "Use file names that include client/date/context.",
        "money_use": "Creates proof-needed/proof-attached tasks for receipts, app screens, and payment screenshots.",
        "safety": "Only business screenshots should be copied in.",
    },
    {
        "app": "Gmail / Mail",
        "status": "connector/export ready",
        "source": "Gmail connector or exported CSV/MBOX/TXT into the import folder.",
        "action": "Filter by business labels, client names, or money keywords before import.",
        "money_use": "Finds leads, payment issues, client replies, disputes, and overdue follow-ups.",
        "safety": "Do not ingest personal mailbox wholesale.",
    },
    {
        "app": "Calendar",
        "status": "connector/export ready",
        "source": "Google Calendar connector or exported calendar notes.",
        "action": "Review upcoming sales/client/follow-up events.",
        "money_use": "Prevents missed consults, client calls, and owner follow-ups.",
        "safety": "Use business calendars or business-filtered events only.",
    },
    {
        "app": "Slack",
        "status": "connector ready",
        "source": "Slack connector",
        "action": "Summarize company channels into intake decisions.",
        "money_use": "Finds team blockers, client issues, and owner decisions.",
        "safety": "Use company channels, not private/personal DMs unless approved.",
    },
    {
        "app": "Cash App / Venmo / Zelle / Bank / Stripe / Square",
        "status": "approval required",
        "source": "Business transaction exports only",
        "action": "Export business transactions/receipts, not personal banking history.",
        "money_use": "Flags paid, failed, refund, chargeback, and reconciliation work.",
        "safety": "Never ingest full personal financial history or credentials.",
    },
]

INTAKE_FIELDS = [
    "intake_id",
    "source_app",
    "source_type",
    "contact",
    "handle",
    "date",
    "category",
    "revenue_signal",
    "priority",
    "owner",
    "status",
    "next_step",
    "proof_required",
    "approval_needed",
    "shared_safe",
    "sanitized_summary",
    "evidence",
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def match_keywords(text: str, keywords: Iterable[str]) -> set[str]:
    lower = text.lower()
    matches = set()
    for keyword in keywords:
        if re.search(r"\b" + re.escape(keyword.lower()) + r"\b", lower):
            matches.add(keyword)
    return matches


def sanitize_summary(text: str, max_chars: int = 140) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    for pattern in [
        r"\b\d{4,8}\b",
        r"\b(?:\d[ -]*?){13,16}\b",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ]:
        cleaned = re.sub(pattern, "[redacted]", cleaned)
    if len(cleaned) > max_chars:
        return cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def classify_text(text: str, inbound: bool = False) -> dict[str, Any]:
    money = match_keywords(text, MONEY_KEYWORDS)
    revenue = match_keywords(text, REVENUE_KEYWORDS)
    client_work = match_keywords(text, CLIENT_WORK_KEYWORDS)
    risk = match_keywords(text, RISK_KEYWORDS)
    proof = match_keywords(text, PROOF_KEYWORDS)
    security = match_keywords(text, SECURITY_KEYWORDS)

    if security:
        category = "Security / Keep Private"
        status = "No Company Action"
        next_step = "Do not share. Keep out of company queue unless Brandon explicitly approves a security review."
        approval_needed = "yes"
        shared_safe = "no"
        priority = 10
    elif risk:
        category = "Risk / Retention"
        status = "Needs Brandon"
        next_step = "Review for refund/cancel/complaint risk and decide the approved response channel."
        approval_needed = "yes"
        shared_safe = "sanitized_only"
        priority = 95
    elif money:
        category = "Money / Billing"
        status = "Needs Brandon" if inbound else "Review"
        next_step = "Review payment/billing context and attach proof before any client-facing action."
        approval_needed = "yes"
        shared_safe = "sanitized_only"
        priority = 90 if inbound else 70
    elif revenue:
        category = "Lead / Revenue"
        status = "Needs Reply" if inbound else "Review"
        next_step = "Confirm lead/follow-up status and move into the approved sales/client workflow if business-related."
        approval_needed = "review"
        shared_safe = "sanitized_only"
        priority = 85 if inbound else 65
    elif client_work:
        category = "Client Work"
        status = "Needs Reply" if inbound else "Review"
        next_step = "Verify client context in DF/HighLevel and create/update Work Queue row if needed."
        approval_needed = "review"
        shared_safe = "sanitized_only"
        priority = 80 if inbound else 55
    elif proof:
        category = "Proof / Receipt"
        status = "Proof Needed"
        next_step = "Attach the proof to the relevant Work Queue item or mark as no-company-action."
        approval_needed = "review"
        shared_safe = "sanitized_only"
        priority = 75
    else:
        category = "Review"
        status = "Review"
        next_step = "Review only if tied to a client, revenue, payment, proof, or owner decision."
        approval_needed = "review"
        shared_safe = "sanitized_only"
        priority = 40

    revenue_signal = "risk" if risk else "yes" if (money or revenue) else "no"
    return {
        "category": category,
        "status": status,
        "next_step": next_step,
        "proof_required": "Evidence, owner decision, and approved channel before Done.",
        "approval_needed": approval_needed,
        "shared_safe": shared_safe,
        "priority": priority,
        "revenue_signal": revenue_signal,
        "matches": sorted(money | revenue | client_work | risk | proof | security),
    }


def intake_from_personal_phone(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or PERSONAL_PHONE_QUEUE_CSV
    rows = []
    for index, row in enumerate(read_csv_rows(path), start=1):
        inbound = row.get("direction") == "inbound"
        text = row.get("last_message", "")
        classification = classify_text(text, inbound=inbound)
        unknown_keyword_only = (
            inbound
            and row.get("contact") == "Unknown business keyword match"
            and "client_" not in row.get("source", "")
        )
        if unknown_keyword_only and classification["status"] == "Needs Reply":
            classification = {
                **classification,
                "status": "Review",
                "next_step": "Verify this is a FUNDz client or business lead before any reply; keep shared outputs sanitized.",
                "approval_needed": "yes",
                "shared_safe": "sanitized_only",
                "priority": min(int(classification.get("priority", 40)), 60),
            }
        rows.append(
            {
                "intake_id": f"PHONE-MSG-{index:03d}",
                "source_app": "Messages",
                "source_type": "business-filtered Mac Messages",
                "contact": row.get("contact", ""),
                "handle": row.get("phone", ""),
                "date": row.get("date", ""),
                "category": classification["category"],
                "revenue_signal": classification["revenue_signal"],
                "priority": classification["priority"],
                "owner": row.get("owner") or ("Brandon" if inbound else "FUNDz"),
                "status": classification["status"],
                "next_step": classification["next_step"],
                "proof_required": classification["proof_required"],
                "approval_needed": classification["approval_needed"],
                "shared_safe": classification["shared_safe"],
                "sanitized_summary": sanitize_summary(text),
                "evidence": evidence_path(path),
            }
        )
    return rows


def intake_from_governor_candidates(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or INTAKE_GOVERNOR_CANDIDATES_CSV
    rows = []
    for index, row in enumerate(read_csv_rows(path), start=1):
        rows.append(
            {
                "intake_id": f"GOV-CANDIDATE-{index:03d}",
                "source_app": "Intake Governor",
                "source_type": row.get("source", ""),
                "contact": row.get("contact", ""),
                "handle": row.get("phone", ""),
                "date": "",
                "category": "Owner Decision",
                "revenue_signal": "review",
                "priority": 88,
                "owner": row.get("owner", "Brandon"),
                "status": row.get("queue_status", "Needs Brandon"),
                "next_step": row.get("next_step", ""),
                "proof_required": row.get("proof_required", ""),
                "approval_needed": row.get("approval_needed", "yes"),
                "shared_safe": row.get("shared_safe", "no"),
                "sanitized_summary": row.get("reason", ""),
                "evidence": row.get("evidence", ""),
            }
        )
    return rows


def read_textish_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except UnicodeDecodeError:
        return ""


def evidence_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def intake_from_import_folder(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or IMPORT_DIR
    path.mkdir(parents=True, exist_ok=True)
    rows = []
    supported = {".txt", ".md", ".csv", ".json"}
    files = [item for item in sorted(path.glob("**/*")) if item.is_file() and item.suffix.lower() in supported]
    for index, item in enumerate(files, start=1):
        text = read_textish_file(item)
        classification = classify_text(text, inbound=True)
        rows.append(
            {
                "intake_id": f"APP-IMPORT-{index:03d}",
                "source_app": "Manual Phone App Export",
                "source_type": item.suffix.lower().lstrip("."),
                "contact": "",
                "handle": "",
                "date": "",
                "category": classification["category"],
                "revenue_signal": classification["revenue_signal"],
                "priority": classification["priority"],
                "owner": "Brandon" if classification["approval_needed"] == "yes" else "FUNDz",
                "status": classification["status"],
                "next_step": classification["next_step"],
                "proof_required": classification["proof_required"],
                "approval_needed": classification["approval_needed"],
                "shared_safe": classification["shared_safe"],
                "sanitized_summary": sanitize_summary(text or item.name),
                "evidence": evidence_path(item),
            }
        )
    return rows


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (-int(row.get("priority") or 0), str(row.get("date") or ""), row.get("intake_id", "")))


def build_registry_lines() -> list[str]:
    lines = [
        "# FUNDz Phone App Intake Registry",
        "",
        "This registry is the approved path for turning phone-app signals into company work without ingesting the whole phone.",
        "",
        "| App | Status | Source | Money use | Safety rail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in APP_REGISTRY:
        lines.append(
            f"| {item['app']} | {item['status']} | {item['source']} | {item['money_use']} | {item['safety']} |"
        )
    lines.extend(
        [
            "",
            "Rule: no personal, financial, security-code, medical, or family content should be imported unless Brandon explicitly approves a narrow business use.",
            "Rule: app data becomes company work only after it has owner, status, next step, proof requirement, and evidence.",
        ]
    )
    return lines


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "category": dict(Counter(row.get("category", "") for row in rows)),
        "source_app": dict(Counter(row.get("source_app", "") for row in rows)),
        "revenue_signal": dict(Counter(row.get("revenue_signal", "") for row in rows)),
        "status": dict(Counter(row.get("status", "") for row in rows)),
        "approval_needed": dict(Counter(row.get("approval_needed", "") for row in rows)),
        "shared_safe": dict(Counter(row.get("shared_safe", "") for row in rows)),
        "top_priority": rows[:10],
    }


def build_phone_app_intake() -> dict[str, Any]:
    rows = []
    rows.extend(intake_from_personal_phone())
    rows.extend(intake_from_governor_candidates())
    rows.extend(intake_from_import_folder())
    rows = sort_rows(rows)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mission": "Turn approved phone-app signals into money/productivity intake without exposing personal content.",
        "summary": summarize(rows),
        "rows": rows,
        "registry": APP_REGISTRY,
        "import_folder": str(IMPORT_DIR),
        "rules": [
            "Do not ingest the whole phone.",
            "Approved apps only.",
            "No credentials, security codes, personal banking history, family, medical, or private content.",
            "Personal-phone content stays sanitized unless Brandon explicitly approves sharing.",
            "Revenue, payment, refund, cancel, lead, and client follow-up signals get priority.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# FUNDz Phone App Intake",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## What This Does",
        "",
        report["mission"],
        "",
        "## Current Read",
        "",
        f"- Intake rows: {summary['rows']}",
        f"- Revenue/money/risk signals: {summary['revenue_signal']}",
        f"- Approval needed: {summary['approval_needed']}",
        f"- Status counts: {summary['status']}",
        "",
        "## Top Priority Rows",
        "",
    ]
    for row in summary["top_priority"]:
        lines.append(
            f"- {row['intake_id']} | {row['source_app']} | {row['category']} | {row['status']} | "
            f"priority {row['priority']} | {row['contact'] or row['handle']} | {row['next_step']}"
        )
    if not summary["top_priority"]:
        lines.append("- No intake rows yet.")
    lines.extend(["", "## Approved App Registry", ""])
    lines.extend(build_registry_lines()[4:])
    lines.append("")
    return "\n".join(lines)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_dashboard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rows = report["rows"][:30]
    cards = [
        ("Rows", summary["rows"]),
        ("Needs Approval", summary["approval_needed"].get("yes", 0)),
        ("Revenue Signals", summary["revenue_signal"].get("yes", 0)),
        ("Risk Signals", summary["revenue_signal"].get("risk", 0)),
        ("Shared Safe", summary["shared_safe"].get("sanitized_only", 0)),
    ]
    card_html = "".join(f"<div class='metric'><span>{esc(label)}</span><strong>{esc(value)}</strong></div>" for label, value in cards)
    row_html = ""
    for row in rows:
        row_html += (
            "<tr>"
            f"<td>{esc(row['priority'])}</td>"
            f"<td>{esc(row['source_app'])}</td>"
            f"<td>{esc(row['category'])}</td>"
            f"<td>{esc(row['status'])}</td>"
            f"<td>{esc(row['contact'] or row['handle'])}</td>"
            f"<td>{esc(row['sanitized_summary'])}</td>"
            f"<td>{esc(row['next_step'])}</td>"
            "</tr>"
        )
    registry_html = "".join(
        f"<tr><td>{esc(item['app'])}</td><td>{esc(item['status'])}</td><td>{esc(item['money_use'])}</td><td>{esc(item['safety'])}</td></tr>"
        for item in APP_REGISTRY
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FUNDz Phone App Intake</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f8fafc; color:#101828; }}
    header {{ background:#fff; border-bottom:1px solid #d0d5dd; padding:18px 24px; }}
    main {{ width:min(1280px,100%); margin:0 auto; padding:18px 20px 28px; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:16px; letter-spacing:0; }}
    p {{ color:#667085; margin:6px 0 0; }}
    .metrics {{ display:grid; grid-template-columns:repeat(5,minmax(130px,1fr)); gap:10px; margin-bottom:16px; }}
    .metric {{ background:#fff; border:1px solid #d0d5dd; border-radius:8px; padding:12px; min-height:82px; }}
    .metric span {{ color:#667085; display:block; font-size:12px; margin-bottom:8px; }}
    .metric strong {{ font-size:28px; line-height:1; }}
    section {{ background:#fff; border:1px solid #d0d5dd; border-radius:8px; padding:16px; margin-bottom:16px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; font-size:13px; }}
    th,td {{ border-bottom:1px solid #d0d5dd; padding:9px 8px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }}
    th {{ background:#f9fafb; font-size:12px; color:#344054; }}
    .flow {{ display:grid; grid-template-columns:repeat(5,minmax(130px,1fr)); gap:10px; }}
    .node {{ border:1px solid #d0d5dd; border-left:5px solid #175cd3; border-radius:8px; padding:12px; background:#fcfcfd; }}
    .node span {{ display:block; color:#667085; font-size:12px; margin-bottom:6px; }}
    .node strong {{ font-size:18px; }}
    @media (max-width:900px) {{ .metrics,.flow {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>FUNDz Phone App Intake</h1>
    <p>{esc(report['mission'])} Generated {esc(report['generated_at'])}</p>
  </header>
  <main>
    <div class="metrics">{card_html}</div>
    <section>
      <h2>How It Works</h2>
      <div class="flow">
        <div class="node"><span>Approved Apps</span><strong>Messages, Notes, Calls, Mail, Calendar, Receipts</strong></div>
        <div class="node"><span>Filter</span><strong>Business and money signals</strong></div>
        <div class="node"><span>Safety</span><strong>Sanitize private content</strong></div>
        <div class="node"><span>Queue</span><strong>Owner, status, next step</strong></div>
        <div class="node"><span>Money</span><strong>Reply, collect, retain, prove</strong></div>
      </div>
    </section>
    <section>
      <h2>Top Intake Rows</h2>
      <table>
        <thead><tr><th>Priority</th><th>App</th><th>Category</th><th>Status</th><th>Contact</th><th>Summary</th><th>Next Step</th></tr></thead>
        <tbody>{row_html}</tbody>
      </table>
    </section>
    <section>
      <h2>Approved App Registry</h2>
      <table>
        <thead><tr><th>App</th><th>Status</th><th>Money Use</th><th>Safety Rail</th></tr></thead>
        <tbody>{registry_html}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    write_json(PHONE_APP_INTAKE_JSON, report)
    write_csv(PHONE_APP_INTAKE_CSV, report["rows"], INTAKE_FIELDS)
    PHONE_APP_INTAKE_MD.write_text(render_markdown(report), encoding="utf-8")
    PHONE_APP_REGISTRY_MD.write_text("\n".join(build_registry_lines()) + "\n", encoding="utf-8")
    PHONE_APP_DASHBOARD_HTML.write_text(render_dashboard(report), encoding="utf-8")
    return {
        "json": PHONE_APP_INTAKE_JSON,
        "csv": PHONE_APP_INTAKE_CSV,
        "markdown": PHONE_APP_INTAKE_MD,
        "registry": PHONE_APP_REGISTRY_MD,
        "dashboard": PHONE_APP_DASHBOARD_HTML,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the FUNDz phone-app productivity/money intake.")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phone_app_intake()
    paths = write_outputs(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print("FUNDz phone-app intake built:")
    for label, path in paths.items():
        print(f"- {label}: {path}")
    print(f"- rows: {report['summary']['rows']}")
    print(f"- approval needed: {report['summary']['approval_needed'].get('yes', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
