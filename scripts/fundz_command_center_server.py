#!/usr/bin/env python3
"""Serve the A FUND Solution Command Center as a protected local web dashboard."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import secrets
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"
DOMAIN_CONFIG = OUTPUT_DIR / "fundz-command-center-domain.json"
COMMAND_CENTER_MD = OUTPUT_DIR / "fundz-command-center.md"
TODAY_OPERATING_BOARD_MD = OUTPUT_DIR / "fundz-today-operating-board.md"
DAILY_BOARD_MD = OUTPUT_DIR / "fundz-daily-board.md"
SEND_VISIBILITY_MD = OUTPUT_DIR / "fundz-send-visibility-command-center.md"
KILL_SWITCH_MD = OUTPUT_DIR / "fundz-send-kill-switch.md"
SEND_GATE_LOCK_MD = OUTPUT_DIR / "fundz-send-gate-lock.md"
BILLING_MAINTENANCE_FOCUS_MD = OUTPUT_DIR / "fundz-billing-maintenance-focus.md"
BILLING_MAINTENANCE_FOCUS_CSV = OUTPUT_DIR / "fundz-billing-maintenance-focus.csv"
ARCHIVE_RECEIPT_TRAIL_MD = OUTPUT_DIR / "fundz-archive-receipt-trail.md"
NEXT_SEND_QUEUE_CSV = OUTPUT_DIR / "fundz-next-send-queue.csv"
WORK_QUEUE_CSV = OUTPUT_DIR / "fundz-work-queue.csv"
COMMAND_CENTER_JSON = OUTPUT_DIR / "fundz-command-center.json"

SAFE_FILES = {
    "command-center": COMMAND_CENTER_MD,
    "today-board": TODAY_OPERATING_BOARD_MD,
    "daily-board": DAILY_BOARD_MD,
    "send-visibility": SEND_VISIBILITY_MD,
    "send-gate-lock": SEND_GATE_LOCK_MD,
    "billing-maintenance": BILLING_MAINTENANCE_FOCUS_MD,
    "billing-maintenance-csv": BILLING_MAINTENANCE_FOCUS_CSV,
    "archive-receipts": ARCHIVE_RECEIPT_TRAIL_MD,
    "kill-switch": KILL_SWITCH_MD,
    "next-send-queue": NEXT_SEND_QUEUE_CSV,
    "work-queue": WORK_QUEUE_CSV,
    "json": COMMAND_CENTER_JSON,
}

PAGE_NAV = (
    {
        "slug": "command-center",
        "title": "Full Report",
        "kicker": "Big Picture",
        "description": "Everything the local A FUND Solution Command Center knows right now.",
        "tone": "info",
    },
    {
        "slug": "today-board",
        "title": "Today Board",
        "kicker": "Focus",
        "description": "The current operating lane and owner-safe next step.",
        "tone": "good",
    },
    {
        "slug": "daily-board",
        "title": "Daily Board",
        "kicker": "Five Lines",
        "description": "The short readable board for today's work.",
        "tone": "good",
    },
    {
        "slug": "send-visibility",
        "title": "Send Visibility",
        "kicker": "Receipts",
        "description": "Sent, attempted, and queued message visibility.",
        "tone": "sky",
    },
    {
        "slug": "send-gate-lock",
        "title": "Send Gate Lock",
        "kicker": "Safety",
        "description": "Why the next sends are still approval-gated.",
        "tone": "warn",
    },
    {
        "slug": "billing-maintenance",
        "title": "Billing Maintenance",
        "kicker": "Cleanup",
        "description": "Urgent, date-sensitive, and duplicate billing review.",
        "tone": "rose",
    },
    {
        "slug": "archive-receipts",
        "title": "Archive Receipts",
        "kicker": "Proof",
        "description": "Archive candidates, exceptions, and proof notes.",
        "tone": "violet",
    },
    {
        "slug": "next-send-queue",
        "title": "Next Send Queue",
        "kicker": "Preview",
        "description": "Queued client messages, shown as review cards.",
        "tone": "sky",
    },
    {
        "slug": "work-queue",
        "title": "Work Queue",
        "kicker": "Rows",
        "description": "Every local work row with the next step up front.",
        "tone": "info",
    },
    {
        "slug": "kill-switch",
        "title": "Kill Switch",
        "kicker": "Control",
        "description": "The local stop control for live sends.",
        "tone": "warn",
    },
    {
        "slug": "json",
        "title": "JSON",
        "kicker": "Machine Data",
        "description": "The full structured report for tools and audits.",
        "tone": "violet",
    },
)
PAGE_META = {item["slug"]: item for item in PAGE_NAV}

CSV_FOCUS_COLUMNS = {
    "next-send-queue": (
        "queue_rank",
        "client_or_lead",
        "channel",
        "subject",
        "owner_notice_status",
        "send_allowed_now",
        "blocked_reason",
        "message_body",
    ),
    "work-queue": (
        "queue_status",
        "client_name",
        "lane",
        "owner",
        "due_date",
        "next_step",
        "proof_required",
        "evidence",
    ),
    "billing-maintenance-csv": (
        "client_name",
        "review_status",
        "billing_issue",
        "next_import",
        "amount_due",
        "recommended_next_action",
        "evidence",
    ),
}


def load_env_file(path: Path = ROOT / ".env.local") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_center_hostname() -> str:
    return os.getenv("FUNDZ_COMMAND_CENTER_HOSTNAME", "fundz-command.afundsolution.com").strip()


def command_center_token() -> str:
    configured = os.getenv("FUNDZ_COMMAND_CENTER_TOKEN", "").strip()
    if configured:
        return configured
    config = read_json(DOMAIN_CONFIG)
    token = str(config.get("token") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    config.update(
        {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "hostname": command_center_hostname(),
            "local_url": f"http://127.0.0.1:{command_center_port()}",
            "owner_url": f"https://{command_center_hostname()}/?token={token}",
            "token": token,
        }
    )
    write_json(DOMAIN_CONFIG, config)
    return token


def command_center_port() -> int:
    try:
        return int(os.getenv("FUNDZ_COMMAND_CENTER_PORT", "8797"))
    except ValueError:
        return 8797


def refresh_command_center() -> tuple[bool, str]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fundz_command_center.py"), "--limit", "10"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    return False, (completed.stderr or completed.stdout).strip()


def read_text(path: Path, limit: int = 120_000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:limit]


def compact_markdown(path: Path) -> str:
    text = read_text(path)
    if not text:
        return "Not generated yet."
    return text


def auth_link(slug: str, token: str) -> str:
    return f"/files/{quote(slug)}?token={quote(token)}"


def display_text(value: Any, fallback: str = "Not set") -> str:
    text = str(value or "").replace("_", " ").strip()
    return text if text else fallback


def status_key(value: Any) -> str:
    text = str(value or "").lower()
    if any(word in text for word in ("blocked", "required", "gated", "hold", "no")):
        return "warn"
    if any(word in text for word in ("ready", "pass", "ok", "done")):
        return "good"
    return "info"


def auth_view_link(slug: str, token: str) -> str:
    return f"/view/{quote(slug)}?token={quote(token)}"


def page_meta(slug: str) -> dict[str, str]:
    meta = PAGE_META.get(slug)
    if meta:
        return meta
    return {
        "slug": slug,
        "title": friendly_label(slug),
        "kicker": "Local File",
        "description": "A local Command Center output rendered for review.",
        "tone": "info",
    }


def friendly_label(value: Any) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    if not text:
        return "Not Set"
    special = {"id", "sms", "df", "csv", "json", "url", "api"}
    words = [word.upper() if word.lower() in special else word.capitalize() for word in text.split()]
    return " ".join(words)


def inline_html(text: str) -> str:
    parts = str(text).split("`")
    rendered = []
    for index, part in enumerate(parts):
        escaped = html.escape(part)
        rendered.append(f"<code>{escaped}</code>" if index % 2 else escaped)
    return "".join(rendered)


def markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_markdown_table_separator(line: str) -> bool:
    cells = markdown_table_row(line)
    return bool(cells) and all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header_html = "".join(f"<th>{inline_html(header)}</th>" for header in headers)
    row_html = []
    for row in rows:
        padded = row + [""] * max(0, len(headers) - len(row))
        cells = "".join(f"<td>{inline_html(cell)}</td>" for cell in padded[: len(headers)])
        row_html.append(f"<tr>{cells}</tr>")
    return (
        "<div class='table-wrap'>"
        "<table class='data-table'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table>"
        "</div>"
    )


def render_markdown_document(text: str) -> str:
    if not text.strip():
        return "<p class='empty'>This local output has not been generated yet.</p>"
    lines = text.splitlines()
    rendered: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            rendered.append(f"<p>{inline_html(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            rendered.append("</ul>")
            in_list = False

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and is_markdown_table_separator(lines[i + 1]):
            flush_paragraph()
            close_list()
            headers = markdown_table_row(stripped)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(markdown_table_row(lines[i]))
                i += 1
            rendered.append(render_markdown_table(headers, rows))
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            close_list()
            level = min(len(stripped) - len(stripped.lstrip("#")), 3)
            title = stripped[level:].strip()
            rendered.append(f"<h{level}>{inline_html(title)}</h{level}>")
            i += 1
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            if not in_list:
                rendered.append("<ul class='friendly-list'>")
                in_list = True
            rendered.append(f"<li>{inline_html(stripped[2:].strip())}</li>")
            i += 1
            continue
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    return "".join(rendered)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = read_text(path, limit=1_000_000)
    if not text.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    rows = [{str(key): str(value or "") for key, value in row.items() if key is not None} for row in reader]
    return headers, rows


def count_values(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = display_text(row.get(key), "Blank")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:6])


def render_stat_cards(cards: list[tuple[str, Any, str]]) -> str:
    if not cards:
        return ""
    return "<div class='stat-grid'>" + "".join(render_metric(label, value, note) for label, value, note in cards) + "</div>"


def render_csv_document(slug: str, path: Path) -> tuple[str, str]:
    headers, rows = read_csv_rows(path)
    if not headers:
        return "<p class='empty'>This CSV is empty or has not been generated yet.</p>", ""
    focus = [column for column in CSV_FOCUS_COLUMNS.get(slug, headers[:8]) if column in headers]
    if not focus:
        focus = headers[:8]
    visible_rows = rows[:80]
    status_column = next((column for column in ("queue_status", "status", "send_allowed_now", "review_status") if column in headers), "")
    cards = [
        ("Rows", len(rows), f"showing {len(visible_rows)}"),
        ("Columns", len(headers), "focused view"),
        ("File", path.name, "raw file still available"),
    ]
    if status_column:
        top_counts = count_values(rows, status_column)
        cards.extend((friendly_label(label), count, friendly_label(status_column)) for label, count in top_counts.items())
    header_html = "".join(f"<th>{html.escape(friendly_label(column))}</th>" for column in focus)
    row_html = []
    for row in visible_rows:
        cells = "".join(f"<td>{inline_html(row.get(column, ''))}</td>" for column in focus)
        row_html.append(f"<tr>{cells}</tr>")
    table = (
        "<div class='table-wrap'>"
        "<table class='data-table roomy'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table>"
        "</div>"
    )
    if len(rows) > len(visible_rows):
        table += f"<p class='empty'>Showing the first {len(visible_rows)} rows. Use the raw file link for the full CSV.</p>"
    return table, render_stat_cards(cards)


def render_json_document(path: Path) -> tuple[str, str]:
    data = read_json(path)
    if not data:
        return "<p class='empty'>This JSON report is empty or has not been generated yet.</p>", ""
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    send_queue = data.get("next_send_queue") if isinstance(data.get("next_send_queue"), list) else []
    work_queue = data.get("work_queue") if isinstance(data.get("work_queue"), list) else []
    cards = [
        ("Generated", display_text(data.get("generated_at"), "Not generated"), "report timestamp"),
        ("Active Clients", summary.get("active_clients", 0), "from summary"),
        ("Next Messages", len(send_queue), "preview rows"),
        ("Work Queue", len(work_queue), "local rows"),
        ("Top Keys", len(data.keys()), "machine sections"),
    ]
    pretty = html.escape(json.dumps(data, indent=2, sort_keys=True))
    body = (
        "<section class='friendly-section'>"
        "<h2>Machine Data, Human Wrapped</h2>"
        "<p>This is the same structured Command Center report, wrapped so it is easy to inspect without losing the raw data.</p>"
        "<details open><summary>View formatted JSON</summary>"
        f"<pre class='json-block'>{pretty}</pre>"
        "</details>"
        "</section>"
    )
    return body, render_stat_cards(cards)


def render_file_body(slug: str, path: Path) -> tuple[str, str]:
    if path.suffix == ".csv":
        return render_csv_document(slug, path)
    if path.suffix == ".json":
        return render_json_document(path)
    text = compact_markdown(path)
    cards = [
        ("File", path.name, "local output"),
        ("Lines", len(text.splitlines()), "readable view"),
    ]
    generated = next((line.split(":", 1)[1].strip() for line in text.splitlines() if line.lower().startswith("generated:")), "")
    if generated:
        cards.insert(0, ("Generated", generated, "report timestamp"))
    return render_markdown_document(text), render_stat_cards(cards)


def render_metric(label: str, value: Any, note: str = "") -> str:
    return (
        "<div class='metric'>"
        f"<span>{html.escape(label)}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        f"<small>{html.escape(note)}</small>"
        "</div>"
    )


def render_chip(label: str, value: Any, tone: str = "info") -> str:
    return (
        f"<span class='chip {html.escape(tone)}'>"
        f"<b>{html.escape(label)}</b>"
        f"{html.escape(display_text(value))}"
        "</span>"
    )


def render_daily_board(report: dict[str, Any]) -> str:
    rows = report.get("daily_board") if isinstance(report.get("daily_board"), list) else []
    if not rows:
        return "<p class='empty'>No daily board has been generated yet.</p>"
    items = []
    for row in rows[:5]:
        label = display_text(row.get("label"), "Item")
        value = display_text(row.get("value"), "")
        items.append(
            "<li>"
            f"<span>{html.escape(label)}</span>"
            f"<strong>{html.escape(value)}</strong>"
            "</li>"
        )
    return f"<ul class='brief-list'>{''.join(items)}</ul>"


def render_top_actions(report: dict[str, Any]) -> str:
    actions = report.get("top_actions") if isinstance(report.get("top_actions"), list) else []
    if not actions:
        return "<p class='empty'>No local action list is ready yet.</p>"
    rows = []
    for item in actions[:5]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(display_text(item.get('client_name'), 'Client'))}</td>"
            f"<td>{html.escape(display_text(item.get('stage')))}</td>"
            f"<td>{html.escape(display_text(item.get('next_touch_status')))}</td>"
            f"<td>{html.escape(display_text(item.get('recommended_next_action')))}</td>"
            "</tr>"
        )
    return (
        "<table class='data-table'>"
        "<thead><tr><th>Client</th><th>Stage</th><th>Status</th><th>Next Local Action</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def render_send_queue(send_queue: list[dict[str, Any]]) -> str:
    if not send_queue:
        return "<p class='empty'>No next-send rows generated.</p>"
    items = []
    for row in send_queue[:6]:
        allowed = display_text(row.get("send_allowed_now"), "no")
        notice = display_text(row.get("owner_notice_status"), "Owner notice required")
        items.append(
            "<article class='queue-item'>"
            "<div class='queue-head'>"
            f"<span class='rank'>#{html.escape(str(row.get('queue_rank') or ''))}</span>"
            f"<strong>{html.escape(display_text(row.get('client_or_lead'), 'Client or lead'))}</strong>"
            f"<span class='pill {status_key(allowed)}'>Send allowed: {html.escape(allowed)}</span>"
            "</div>"
            "<div class='queue-meta'>"
            f"<span>{html.escape(display_text(row.get('channel')))}</span>"
            f"<span>{html.escape(display_text(row.get('stage')))}</span>"
            f"<span>{html.escape(notice)}</span>"
            "</div>"
            f"<p>{html.escape(display_text(row.get('message_body'), 'No message body in the current preview.'))}</p>"
            f"<small>{html.escape(display_text(row.get('blocked_reason'), 'Approval gates still apply.'))}</small>"
            "</article>"
        )
    return f"<div class='queue-list'>{''.join(items)}</div>"


def render_operating_map(token: str) -> str:
    routes = (
        (
            "Open first",
            "Today Board",
            "The single lane for the current work block.",
            auth_view_link("today-board", token),
        ),
        (
            "Do the work",
            "Work Queue",
            "Rows with owner, next step, due date, proof, and evidence.",
            auth_view_link("work-queue", token),
        ),
        (
            "Billing",
            "Billing Maintenance",
            "Lucy-owned billing decisions supplied by the FUNDz source workflow.",
            auth_view_link("billing-maintenance", token),
        ),
        (
            "Messages",
            "Send Visibility",
            "Receipts and next-send gates. This is visibility, not approval.",
            auth_view_link("send-visibility", token),
        ),
    )
    cards = []
    for kicker, title, body, href in routes:
        cards.append(
            "<a class='map-card' href='{}'>"
            "<span>{}</span>"
            "<strong>{}</strong>"
            "<small>{}</small>"
            "</a>".format(
                href,
                html.escape(kicker),
                html.escape(title),
                html.escape(body),
            )
        )
    return (
        "<div class='map-grid'>"
        "<article class='map-card fixed'>"
        "<span>Hierarchy</span>"
        "<strong>One Command Center</strong>"
        "<small>A FUND Solution is the command center. FUNDz is one source workflow feeding local evidence, billing, archive, and message-readiness outputs.</small>"
        "</article>"
        f"{''.join(cards)}"
        "</div>"
        "<div class='message-key'>"
        "<strong>Message types:</strong> "
        "<span>Work Queue = task rows</span>"
        "<span>Send Visibility = receipts and gates</span>"
        "<span>Next Send Queue = preview only</span>"
        "</div>"
    )


def render_links(token: str, active_slug: str = "") -> str:
    items = []
    for meta in PAGE_NAV:
        slug = meta["slug"]
        active = " active" if slug == active_slug else ""
        items.append(
            f"<a class='nav-card {html.escape(meta['tone'])}{active}' href='{auth_view_link(slug, token)}'>"
            f"<span>{html.escape(meta['kicker'])}</span>"
            f"<strong>{html.escape(meta['title'])}</strong>"
            f"<small>{html.escape(meta['description'])}</small>"
            "</a>"
        )
    return "".join(items)


def common_styles() -> str:
    return """
    :root {
      color-scheme: light;
      --ink:#172026;
      --muted:#5d6d75;
      --line:#d7e2e5;
      --paper:#ffffff;
      --wash:#f6faf8;
      --deep:#102f3b;
      --mint:#dcf7e8;
      --mint-ink:#115e3b;
      --gold:#fff1c8;
      --gold-ink:#735000;
      --sky:#e3f2ff;
      --sky-ink:#075985;
      --rose:#ffe5df;
      --rose-ink:#9b2f23;
      --violet:#efe9ff;
      --violet-ink:#55409a;
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      color:var(--ink);
      background:#f7faf8;
      line-height:1.45;
    }
    a { color:inherit; }
    .site-header {
      padding:26px 28px 22px;
      border-bottom:1px solid var(--line);
      background:linear-gradient(180deg,#ffffff 0,#f8fbfb 100%);
    }
    .hero { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:end; }
    .hero-copy { max-width:820px; }
    h1 { margin:0; font-size:clamp(30px,4vw,54px); line-height:1; letter-spacing:0; }
    h2 { margin:0 0 12px; font-size:22px; line-height:1.15; letter-spacing:0; }
    h3 { margin:20px 0 8px; font-size:18px; }
    p { margin:0 0 12px; }
    .sub { margin:9px 0 0; color:var(--muted); max-width:760px; font-size:16px; }
    .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
    .chip,.pill {
      display:inline-flex;
      align-items:center;
      gap:6px;
      border-radius:999px;
      padding:7px 10px;
      font-size:13px;
      border:1px solid var(--line);
      white-space:normal;
      font-weight:650;
    }
    .chip b { font-weight:800; }
    .good { --accent:#1d7a54; --tint:var(--mint); --tone-ink:var(--mint-ink); }
    .warn { --accent:#b98200; --tint:var(--gold); --tone-ink:var(--gold-ink); }
    .info { --accent:#2b6f89; --tint:#e6f7fa; --tone-ink:#17566a; }
    .sky { --accent:#1976a3; --tint:var(--sky); --tone-ink:var(--sky-ink); }
    .rose { --accent:#c64a37; --tint:var(--rose); --tone-ink:var(--rose-ink); }
    .violet { --accent:#7862c8; --tint:var(--violet); --tone-ink:var(--violet-ink); }
    .chip.good,.pill.good { background:var(--mint); color:var(--mint-ink); border-color:#b9e7cd; }
    .chip.warn,.pill.warn { background:var(--gold); color:var(--gold-ink); border-color:#ebd38d; }
    .chip.info,.pill.info { background:var(--sky); color:var(--sky-ink); border-color:#bfdef4; }
    .chip.sky,.pill.sky { background:var(--sky); color:var(--sky-ink); border-color:#bfdef4; }
    .chip.rose,.pill.rose { background:var(--rose); color:var(--rose-ink); border-color:#eec5bd; }
    .chip.violet,.pill.violet { background:var(--violet); color:var(--violet-ink); border-color:#d7ccff; }
    .nav-grid {
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
      gap:10px;
      margin-top:18px;
    }
    .nav-card {
      min-height:112px;
      display:grid;
      align-content:start;
      gap:6px;
      padding:13px;
      border:1px solid color-mix(in srgb,var(--accent),#fff 55%);
      border-left:7px solid var(--accent);
      border-radius:8px;
      background:var(--paper);
      color:var(--ink);
      text-decoration:none;
      box-shadow:0 1px 0 rgba(16,47,59,.05);
    }
    .nav-card:hover,.nav-card.active {
      background:var(--tint);
      transform:translateY(-1px);
      box-shadow:0 8px 18px rgba(16,47,59,.09);
    }
    .nav-card span {
      color:var(--tone-ink);
      font-size:11px;
      font-weight:850;
      letter-spacing:.04em;
      text-transform:uppercase;
    }
    .nav-card strong { font-size:17px; line-height:1.1; }
    .nav-card small { color:var(--muted); font-size:13px; line-height:1.3; }
    .compact-header .nav-grid { grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); }
    .compact-header .nav-card { min-height:76px; padding:10px 11px; }
    .compact-header .nav-card small { display:none; }
    main { max-width:1280px; padding:22px 28px 42px; }
    .top-actions { display:flex; flex-wrap:wrap; gap:9px; justify-content:flex-end; }
    .home-pill,.raw-link {
      min-height:38px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:8px 12px;
      border:1px solid var(--line);
      border-radius:999px;
      background:#fff;
      color:#164d68;
      text-decoration:none;
      font-weight:750;
      font-size:14px;
    }
    .metrics,.stat-grid {
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(165px,1fr));
      gap:12px;
      margin:18px 0;
    }
    .metric {
      border:1px solid var(--line);
      border-radius:8px;
      background:var(--paper);
      padding:14px;
      min-height:98px;
      border-top:5px solid #dbe7e9;
    }
    .metric span { display:block; color:var(--muted); font-size:13px; font-weight:700; }
    .metric strong { display:block; margin-top:8px; font-size:24px; line-height:1.05; overflow-wrap:anywhere; }
    .metric small { display:block; margin-top:7px; color:var(--muted); overflow-wrap:anywhere; }
    .grid { display:grid; grid-template-columns:1.05fr .95fr; gap:16px; align-items:start; }
    section,.friendly-section,.document {
      border:1px solid var(--line);
      background:var(--paper);
      border-radius:8px;
      padding:16px;
    }
    .document { border-top:7px solid var(--accent,#2b6f89); }
    .document h1 { margin:0 0 14px; font-size:30px; line-height:1.08; }
    .document h2 { margin-top:22px; padding-top:14px; border-top:1px solid var(--line); }
    .document h3 { color:var(--deep); }
    .document p,.document li { max-width:1050px; font-size:15px; }
    .friendly-list { display:grid; gap:8px; padding-left:22px; }
    .friendly-list li::marker { color:var(--accent,#2b6f89); }
    .brief-list { list-style:none; padding:0; margin:0; display:grid; gap:10px; }
    .brief-list li { display:grid; gap:4px; padding-bottom:10px; border-bottom:1px solid var(--line); }
    .brief-list li:last-child { border-bottom:0; padding-bottom:0; }
    .brief-list span,.queue-meta,.queue-item small,.empty { color:var(--muted); font-size:13px; }
    .brief-list strong { font-size:15px; line-height:1.4; }
    .queue-list { display:grid; gap:10px; }
    .queue-item { border:1px solid var(--line); border-radius:8px; padding:12px; background:var(--wash); }
    .queue-head { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
    .queue-head strong { font-size:15px; }
    .rank { font-weight:800; color:var(--sky-ink); }
    .queue-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
    .queue-meta span { background:#fff; border:1px solid var(--line); border-radius:999px; padding:5px 8px; }
    .queue-item p { margin:10px 0 8px; overflow-wrap:anywhere; }
    .map-grid {
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
      gap:10px;
    }
    .map-card {
      display:grid;
      gap:6px;
      min-height:122px;
      padding:14px;
      border:1px solid var(--line);
      border-radius:8px;
      background:#fff;
      text-decoration:none;
      border-top:5px solid #2b6f89;
    }
    .map-card.fixed { border-top-color:#1d7a54; }
    .map-card span {
      color:var(--muted);
      font-size:12px;
      font-weight:850;
      text-transform:uppercase;
      letter-spacing:.04em;
    }
    .map-card strong { font-size:17px; line-height:1.15; }
    .map-card small { color:var(--muted); line-height:1.35; }
    .message-key {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:12px;
      color:var(--muted);
    }
    .message-key span {
      border:1px solid var(--line);
      border-radius:999px;
      background:#f8fbfb;
      padding:6px 9px;
      font-size:13px;
    }
    .table-wrap { width:100%; overflow:auto; border:1px solid var(--line); border-radius:8px; background:#fff; }
    .data-table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
    .data-table.roomy { min-width:920px; }
    th,td { border-bottom:1px solid var(--line); text-align:left; padding:10px 9px; vertical-align:top; overflow-wrap:anywhere; }
    th { color:var(--muted); font-weight:800; background:#f8fbfb; position:sticky; top:0; }
    tr:nth-child(even) td { background:#fbfdfd; }
    details { border:1px solid var(--line); border-radius:8px; background:#fff; overflow:hidden; }
    summary { cursor:pointer; padding:12px 14px; font-weight:800; background:var(--wash); }
    .json-block {
      margin:0;
      max-height:72vh;
      overflow:auto;
      padding:14px;
      background:#101820;
      color:#e9f6f2;
      font-size:12px;
      line-height:1.45;
    }
    .utility-row { display:flex; flex-wrap:wrap; gap:10px; margin:12px 0 0; color:var(--muted); }
    code { background:#eef5f6; border:1px solid var(--line); border-radius:5px; padding:1px 4px; }
    @media (max-width:980px) { .grid,.hero { grid-template-columns:1fr; } .top-actions { justify-content:flex-start; } }
    @media (max-width:640px) {
      .site-header,main { padding-left:16px; padding-right:16px; }
      .nav-grid { grid-template-columns:1fr; }
      .compact-header .nav-grid { grid-template-columns:1fr 1fr; }
      .compact-header .nav-card { min-height:62px; }
      .compact-header .nav-card strong { font-size:15px; }
      .metric strong { font-size:21px; }
      .data-table { table-layout:auto; }
    }
  """


def render_page_shell(title: str, intro: str, body: str, token: str, active_slug: str, stats_html: str = "") -> str:
    meta = page_meta(active_slug)
    raw = auth_link(active_slug, token)
    nav = render_links(token, active_slug)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A FUND Solution Command Center - {html.escape(title)}</title>
  <style>{common_styles()}</style>
</head>
<body>
  <header class="site-header compact-header">
    <div class="hero">
      <div class="hero-copy">
        <p class="pill {html.escape(meta['tone'])}">{html.escape(meta['kicker'])}</p>
        <h1>{html.escape(title)}</h1>
        <p class="sub">{html.escape(intro)}</p>
      </div>
      <div class="top-actions">
        <a class="home-pill" href="/?token={quote(token)}">Dashboard Home</a>
        <a class="raw-link" href="{raw}">Open Raw File</a>
      </div>
    </div>
    <nav class="nav-grid" aria-label="A FUND Solution Command Center pages">{nav}</nav>
  </header>
  <main>
    {stats_html}
    <article class="document {html.escape(meta['tone'])}">
      {body}
    </article>
    <p class="utility-row">Safe-mode note: these pages make local reports easier to read. They do not approve, edit, or send client-facing work.</p>
  </main>
</body>
</html>
"""


def render_file_page(slug: str, token: str) -> str:
    target = SAFE_FILES[slug]
    meta = page_meta(slug)
    body, stats = render_file_body(slug, target)
    return render_page_shell(meta["title"], meta["description"], body, token, slug, stats)


def render_home(token: str) -> str:
    report = read_json(COMMAND_CENTER_JSON)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    send_queue = report.get("next_send_queue") if isinstance(report.get("next_send_queue"), list) else []
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    safety_gate = report.get("safety_gate") if isinstance(report.get("safety_gate"), dict) else {}
    maintenance = report.get("maintenance_cleanup_summary") if isinstance(report.get("maintenance_cleanup_summary"), dict) else {}
    billing_decisions = maintenance.get("billing_decisions") if isinstance(maintenance.get("billing_decisions"), dict) else {}
    archive_trail = report.get("archive_receipt_trail") if isinstance(report.get("archive_receipt_trail"), dict) else {}
    queue_status = {}
    for row in report.get("work_queue", []) if isinstance(report.get("work_queue"), list) else []:
        status = str(row.get("queue_status") or "Unknown")
        queue_status[status] = queue_status.get(status, 0) + 1
    allowed_now = sum(1 for row in send_queue if str(row.get("send_allowed_now") or "").lower() == "yes")
    needs_attention = queue_status.get("Needs Brandon", 0) + queue_status.get("Hold", 0) + queue_status.get("Proof Needed", 0)
    cards = [
        ("Safety Gate", display_text(safety_gate.get("state"), "Local reporting only"), display_text(safety_gate.get("note"), "client sends remain off")),
        ("Live Sends", "Off", "client-facing work is inactive"),
        ("Active Clients", summary.get("active_clients", 0), "tracked locally"),
        ("Needs Attention", needs_attention, "hold, proof, or Brandon"),
        ("Next Messages", len(send_queue), f"{allowed_now} allowed now"),
        ("Billing Maintenance", f"{billing_decisions.get('active_urgent_billing_review', 0)} urgent", f"{billing_decisions.get('active_date_sensitive_billing_review', 0)} date-sensitive, {maintenance.get('duplicate_review_clients', 0)} duplicate"),
        ("Archive Receipts", archive_trail.get("live_confirmed", 0), f"{archive_trail.get('exceptions', 0)} exceptions"),
        ("Work Queue", sum(queue_status.values()), "local rows"),
        ("Kill Switch", display_text(kill_switch.get("status"), "gated"), "local control"),
    ]
    card_html = "".join(render_metric(*card) for card in cards)
    chips = "".join(
        (
            render_chip("Mode", "Inactive", "good"),
            render_chip("Dashboard", "Awake", "info"),
            render_chip("Approval", "Required", "warn"),
            render_chip("Client Sends", "Off", "warn"),
        )
    )
    links = render_links(token)
    daily = render_daily_board(report)
    top_actions = render_top_actions(report)
    queue = render_send_queue(send_queue)
    operating_map = render_operating_map(token)
    generated = html.escape(str(report.get("generated_at") or "not generated"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A FUND Solution Command Center</title>
  <style>{common_styles()}</style>
</head>
<body>
  <header class="site-header">
    <div class="hero">
      <div class="hero-copy">
        <h1>A FUND Solution Command Center</h1>
        <p class="sub">Friendly safe-mode view. The FUNDz workspace is awake as one source for local reporting, but inactive for client-facing sends, live replies, DF/AutoFox edits, and webhook wiring.</p>
        <div class="chips">{chips}</div>
      </div>
    </div>
    <nav class="nav-grid" aria-label="A FUND Solution Command Center pages">{links}</nav>
  </header>
  <main>
    <div class="metrics">{card_html}</div>
    <section style="margin-bottom:16px">
      <h2>One Command Center</h2>
      {operating_map}
    </section>
    <div class="grid">
      <section>
        <h2>Now</h2>
        {daily}
      </section>
      <section>
        <h2>Next Queued Messages</h2>
        {queue}
      </section>
    </div>
    <section style="margin-top:16px">
      <h2>Top Local Actions</h2>
      {top_actions}
    </section>
    <p class="sub">Generated: {generated}. This page can refresh boards and show queues; it does not approve or send anything by itself.</p>
  </main>
</body>
</html>
"""


def render_locked_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A FUND Solution Command Center Locked</title>
  <style>
    :root { color-scheme: light; --ink:#172026; --muted:#64737b; --line:#d9e2e5; --mint:#dff7ea; --mint-ink:#115e3b; --gold:#fff0c7; --gold-ink:#7a4f00; --sky:#e3f2ff; --sky-ink:#075985; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; display:grid; place-items:center; padding:22px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:#f7fbfb; }
    main { width:min(720px,100%); border:1px solid var(--line); border-radius:8px; background:#fff; padding:24px; }
    h1 { margin:0; font-size:28px; letter-spacing:0; }
    p { color:var(--muted); line-height:1.5; }
    .chips { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }
    .chip { border-radius:999px; padding:7px 10px; font-size:13px; border:1px solid var(--line); }
    .good { background:var(--mint); color:var(--mint-ink); border-color:#bee8cf; }
    .warn { background:var(--gold); color:var(--gold-ink); border-color:#efd78f; }
    .info { background:var(--sky); color:var(--sky-ink); border-color:#bddff8; }
    code { background:#f5f8f8; border:1px solid var(--line); border-radius:6px; padding:2px 5px; }
  </style>
</head>
<body>
  <main>
    <h1>A FUND Solution Command Center is protected</h1>
    <p>The plain domain is the locked front door. Use the saved owner link on this Mac to open the dashboard with the private token already attached.</p>
    <div class="chips">
      <span class="chip good">FUNDz inactive for client sends</span>
      <span class="chip info">Dashboard awake</span>
      <span class="chip warn">Owner token required</span>
    </div>
    <p>Owner link file: <code>data/local/command-center/fundz-command-center-domain.json</code></p>
  </main>
</body>
</html>
"""


class CommandCenterHandler(BaseHTTPRequestHandler):
    server_version = "FUNDzCommandCenter/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler signature.
        return

    def send_body(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def token_from_request(self) -> str:
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        header_token = self.headers.get("X-FUNDZ-Command-Token", "")
        auth = self.headers.get("Authorization", "")
        bearer = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        return query_token or header_token or bearer

    def authorized(self) -> bool:
        expected = getattr(self.server, "fundz_token")  # type: ignore[attr-defined]
        return bool(expected and secrets.compare_digest(self.token_from_request(), expected))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_body(200, json.dumps({"ok": True, "service": "fundz-command-center"}), "application/json; charset=utf-8")
            return
        if not self.authorized():
            self.send_body(403, render_locked_page())
            return
        if parsed.path == "/":
            refresh_command_center()
            self.send_body(200, render_home(getattr(self.server, "fundz_token")))  # type: ignore[attr-defined]
            return
        if parsed.path == "/refresh":
            ok, detail = refresh_command_center()
            self.send_body(200 if ok else 500, json.dumps({"ok": ok, "detail": detail}), "application/json; charset=utf-8")
            return
        if parsed.path.startswith("/view/"):
            slug = parsed.path.removeprefix("/view/").strip("/")
            if slug not in SAFE_FILES:
                self.send_body(404, "Unknown A FUND Solution Command Center page.\n", "text/plain; charset=utf-8")
                return
            self.send_body(200, render_file_page(slug, getattr(self.server, "fundz_token")))  # type: ignore[attr-defined]
            return
        if parsed.path.startswith("/files/"):
            slug = parsed.path.removeprefix("/files/").strip("/")
            target = SAFE_FILES.get(slug)
            if not target:
                self.send_body(404, "Unknown A FUND Solution Command Center file.\n", "text/plain; charset=utf-8")
                return
            content_type = "application/json; charset=utf-8" if target.suffix == ".json" else "text/plain; charset=utf-8"
            self.send_body(200, read_text(target), content_type)
            return
        self.send_body(404, "Not found.\n", "text/plain; charset=utf-8")


def run_server(host: str, port: int) -> None:
    token = command_center_token()
    config = read_json(DOMAIN_CONFIG)
    config.update(
        {
            "hostname": command_center_hostname(),
            "local_url": f"http://{host}:{port}",
            "owner_url": f"https://{command_center_hostname()}/?token={token}",
            "token": token,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    )
    write_json(DOMAIN_CONFIG, config)
    server = ThreadingHTTPServer((host, port), CommandCenterHandler)
    setattr(server, "fundz_token", token)
    print(f"A FUND Solution Command Center listening on http://{host}:{port}")
    print(f"Owner URL: https://{command_center_hostname()}/?token={token}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("FUNDZ_COMMAND_CENTER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=command_center_port())
    return parser.parse_args()


def main() -> int:
    load_env_file()
    args = parse_args()
    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
