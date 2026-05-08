#!/usr/bin/env python3
"""Serve the FUNDz Command Center as a protected local web dashboard."""

from __future__ import annotations

import argparse
import html
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
DAILY_BOARD_MD = OUTPUT_DIR / "fundz-daily-board.md"
SEND_VISIBILITY_MD = OUTPUT_DIR / "fundz-send-visibility-command-center.md"
KILL_SWITCH_MD = OUTPUT_DIR / "fundz-send-kill-switch.md"
NEXT_SEND_QUEUE_CSV = OUTPUT_DIR / "fundz-next-send-queue.csv"
WORK_QUEUE_CSV = OUTPUT_DIR / "fundz-work-queue.csv"
COMMAND_CENTER_JSON = OUTPUT_DIR / "fundz-command-center.json"
OWNER_REVIEW_ACTIONS_JSON = OUTPUT_DIR / "fundz-owner-review-dashboard-actions.json"
OWNER_REVIEW_ACTIONS_JSONL = OUTPUT_DIR / "fundz-owner-review-dashboard-actions.jsonl"

OWNER_REVIEW_STATUSES = {"Needs Brandon", "Hold", "Proof Needed"}
OWNER_REVIEW_ACTION_LABELS = {
    "keep_hold": "Keep on hold",
    "needs_proof": "Needs proof",
    "fixed_locally": "Problem fixed locally",
    "needs_brandon": "Needs Brandon decision",
}

SAFE_FILES = {
    "command-center": COMMAND_CENTER_MD,
    "daily-board": DAILY_BOARD_MD,
    "send-visibility": SEND_VISIBILITY_MD,
    "kill-switch": KILL_SWITCH_MD,
    "next-send-queue": NEXT_SEND_QUEUE_CSV,
    "work-queue": WORK_QUEUE_CSV,
    "json": COMMAND_CENTER_JSON,
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


def work_order_id(row: dict[str, Any]) -> str:
    for key in ("work_order_id", "client_key", "client_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "unknown-work-order"


def priority_score(row: dict[str, Any]) -> int:
    try:
        return int(row.get("priority_score") or 0)
    except (TypeError, ValueError):
        return 0


def owner_review_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("work_queue") if isinstance(report.get("work_queue"), list) else []
    review_rows = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("queue_status") or "").strip() in OWNER_REVIEW_STATUSES
    ]
    status_rank = {"Needs Brandon": 0, "Hold": 1, "Proof Needed": 2}
    return sorted(
        review_rows,
        key=lambda row: (
            status_rank.get(str(row.get("queue_status") or ""), 9),
            -priority_score(row),
            str(row.get("client_name") or ""),
        ),
    )


def load_owner_review_actions() -> dict[str, dict[str, Any]]:
    data = read_json(OWNER_REVIEW_ACTIONS_JSON)
    actions = data.get("items") if isinstance(data.get("items"), dict) else {}
    return {str(key): value for key, value in actions.items() if isinstance(value, dict)}


def save_owner_review_action(payload: dict[str, Any]) -> dict[str, Any]:
    report = read_json(COMMAND_CENTER_JSON)
    rows_by_id = {work_order_id(row): row for row in owner_review_rows(report)}
    requested_id = str(payload.get("work_order_id") or "").strip()
    if requested_id not in rows_by_id:
        raise ValueError("This queue item is not in the current Brandon review list.")
    action = str(payload.get("action") or "").strip()
    if action not in OWNER_REVIEW_ACTION_LABELS:
        raise ValueError("Choose a valid local review action.")
    note = str(payload.get("note") or "").strip()[:800]
    row = rows_by_id[requested_id]
    saved = {
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "work_order_id": requested_id,
        "client_name": str(row.get("client_name") or ""),
        "queue_status": str(row.get("queue_status") or ""),
        "action": action,
        "action_label": OWNER_REVIEW_ACTION_LABELS[action],
        "note": note,
        "source": "fundz_command_center_dashboard",
        "local_only": True,
        "no_live_send": True,
        "no_external_edit": True,
    }
    current = read_json(OWNER_REVIEW_ACTIONS_JSON)
    items = current.get("items") if isinstance(current.get("items"), dict) else {}
    items[requested_id] = saved
    write_json(OWNER_REVIEW_ACTIONS_JSON, {"updated_at": saved["saved_at"], "items": items})
    OWNER_REVIEW_ACTIONS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OWNER_REVIEW_ACTIONS_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(saved, sort_keys=True) + "\n")
    return saved


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


def render_metric(label: str, value: Any, note: str = "", *, review_button: bool = False) -> str:
    tag = "a" if review_button else "div"
    attrs = " href='#owner-review-panel' role='button' data-open-owner-review aria-haspopup='dialog'" if review_button else ""
    hint = "<em>Open review panel</em>" if review_button else ""
    return (
        f"<{tag} class='metric{' metric-button' if review_button else ''}'{attrs}>"
        f"<span>{html.escape(label)}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        f"<small>{html.escape(note)}</small>"
        f"{hint}"
        f"</{tag}>"
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


def render_owner_review_panel(rows: list[dict[str, Any]], actions: dict[str, dict[str, Any]]) -> str:
    count = len(rows)
    if rows:
        cards = []
        action_options = "".join(
            f"<option value='{html.escape(value, quote=True)}'>{html.escape(label)}</option>"
            for value, label in OWNER_REVIEW_ACTION_LABELS.items()
        )
        for index, row in enumerate(rows, start=1):
            row_id = work_order_id(row)
            saved = actions.get(row_id, {})
            saved_text = (
                f"Last saved: {display_text(saved.get('action_label'))}"
                if saved
                else "No local decision saved yet."
            )
            cards.append(
                "<article class='review-card'>"
                "<div class='review-head'>"
                f"<span class='rank'>#{index}</span>"
                f"<strong>{html.escape(display_text(row.get('client_name'), 'Client'))}</strong>"
                f"<span class='pill {status_key(row.get('queue_status'))}'>{html.escape(display_text(row.get('queue_status')))}</span>"
                "</div>"
                "<dl class='review-details'>"
                f"<div><dt>Lane</dt><dd>{html.escape(display_text(row.get('lane')))}</dd></div>"
                f"<div><dt>Due</dt><dd>{html.escape(display_text(row.get('due_date')))}</dd></div>"
                f"<div><dt>Why held</dt><dd>{html.escape(display_text(row.get('do_not_send_because'), 'Review required before outreach.'))}</dd></div>"
                f"<div><dt>Next step</dt><dd>{html.escape(display_text(row.get('next_step')))}</dd></div>"
                f"<div><dt>Proof needed</dt><dd>{html.escape(display_text(row.get('proof_required')))}</dd></div>"
                f"<div><dt>Evidence</dt><dd>{html.escape(display_text(row.get('evidence')))}</dd></div>"
                "</dl>"
                "<form class='review-form'>"
                f"<input type='hidden' name='work_order_id' value='{html.escape(row_id, quote=True)}'>"
                "<label>Decision"
                f"<select name='action'>{action_options}</select>"
                "</label>"
                "<label>Note"
                "<textarea name='note' rows='2' placeholder='What did you fix or decide?'></textarea>"
                "</label>"
                "<button type='submit'>Save Local Fix</button>"
                f"<span class='save-state'>{html.escape(saved_text)}</span>"
                "</form>"
                "</article>"
            )
        body = "".join(cards)
    else:
        body = "<p class='empty'>Nothing needs Brandon review right now.</p>"
    return f"""
<section id="owner-review-panel" class="review-panel" aria-label="Needs Brandon review panel">
  <div class="review-dialog" role="dialog" aria-modal="true">
    <div class="dialog-top">
    <div>
      <h2>Needs Brandon Review</h2>
      <p>{count} queue item(s) need Brandon/hold review. These fixes are local notes only; nothing sends and no external system changes.</p>
    </div>
    <a class="dialog-close" href="#">Close</a>
    </div>
    <div class="review-list">{body}</div>
  </div>
</section>
"""


def render_owner_review_script() -> str:
    return """
<script>
(() => {
  const token = new URLSearchParams(window.location.search).get("token") || "";
  for (const form of document.querySelectorAll(".review-form")) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const state = form.querySelector(".save-state");
      const data = new FormData(form);
      const payload = {
        work_order_id: data.get("work_order_id"),
        action: data.get("action"),
        note: data.get("note"),
      };
      if (state) state.textContent = "Saving...";
      try {
        const response = await fetch(`/review-action?token=${encodeURIComponent(token)}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) {
          throw new Error(result.error || "Could not save local review.");
        }
        if (state) state.textContent = `Saved: ${result.action_label}`;
      } catch (error) {
        if (state) state.textContent = error.message || "Could not save local review.";
      }
    });
  }
})();
</script>
"""


def render_links(token: str) -> str:
    return "".join(
        f"<a href='{auth_link(slug, token)}'>{html.escape(label)}</a>"
        for slug, label in (
            ("command-center", "Full Report"),
            ("daily-board", "Daily Board"),
            ("send-visibility", "Send Visibility"),
            ("next-send-queue", "Next Send Queue"),
            ("work-queue", "Work Queue"),
            ("kill-switch", "Kill Switch"),
            ("json", "JSON"),
        )
    )


def render_home(token: str) -> str:
    report = read_json(COMMAND_CENTER_JSON)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    send_queue = report.get("next_send_queue") if isinstance(report.get("next_send_queue"), list) else []
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    review_rows = owner_review_rows(report)
    review_actions = load_owner_review_actions()
    queue_status = {}
    for row in report.get("work_queue", []) if isinstance(report.get("work_queue"), list) else []:
        status = str(row.get("queue_status") or "Unknown")
        queue_status[status] = queue_status.get(status, 0) + 1
    allowed_now = sum(1 for row in send_queue if str(row.get("send_allowed_now") or "").lower() == "yes")
    cards = [
        ("Live Sends", "Off", "client-facing work is inactive", False),
        ("Active Clients", summary.get("active_clients", 0), "tracked locally", False),
        ("Needs Brandon", len(review_rows), "click to review/fix", True),
        ("Next Messages", len(send_queue), f"{allowed_now} allowed now", False),
        ("Work Queue", sum(queue_status.values()), "local rows", False),
        ("Kill Switch", display_text(kill_switch.get("status"), "gated"), "local control", False),
    ]
    card_html = "".join(render_metric(label, value, note, review_button=review_button) for label, value, note, review_button in cards)
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
    owner_review_panel = render_owner_review_panel(review_rows, review_actions)
    owner_review_script = render_owner_review_script()
    generated = html.escape(str(report.get("generated_at") or "not generated"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FUNDz Command Center</title>
  <style>
    :root {{ color-scheme: light; --ink:#172026; --muted:#64737b; --line:#d9e2e5; --paper:#ffffff; --wash:#f5f8f8; --mint:#dff7ea; --mint-ink:#115e3b; --gold:#fff0c7; --gold-ink:#7a4f00; --sky:#e3f2ff; --sky-ink:#075985; --rose:#ffe3dc; --rose-ink:#9f2f1f; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:linear-gradient(180deg,#f7fbfb 0,#fff 320px); }}
    header {{ padding:28px 28px 20px; border-bottom:1px solid var(--line); background:var(--paper); }}
    h1 {{ margin:0; font-size:28px; letter-spacing:0; }}
    h2 {{ font-size:18px; margin:0 0 12px; }}
    p {{ line-height:1.45; }}
    main {{ padding:22px 28px 40px; max-width:1220px; }}
    .hero {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:end; }}
    .sub {{ margin:8px 0 0; color:var(--muted); max-width:760px; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }}
    .chip,.pill {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:7px 10px; font-size:13px; border:1px solid var(--line); white-space:normal; }}
    .chip b {{ font-weight:700; }}
    .good {{ background:var(--mint); color:var(--mint-ink); border-color:#bee8cf; }}
    .warn {{ background:var(--gold); color:var(--gold-ink); border-color:#efd78f; }}
    .info {{ background:var(--sky); color:var(--sky-ink); border-color:#bddff8; }}
    .rose {{ background:var(--rose); color:var(--rose-ink); border-color:#f2c4bb; }}
    .links {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }}
    .links a {{ border:1px solid var(--line); border-radius:6px; padding:8px 10px; color:#0f4f77; text-decoration:none; background:#fff; font-size:14px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(6,minmax(140px,1fr)); gap:12px; margin:18px 0; }}
    .metric {{ border:1px solid var(--line); background:var(--paper); border-radius:8px; padding:14px; min-height:92px; }}
    .metric span {{ display:block; color:var(--muted); font-size:13px; }}
    .metric strong {{ display:block; margin-top:8px; font-size:22px; word-break:break-word; }}
    .metric small {{ display:block; margin-top:6px; color:var(--muted); }}
    .metric em {{ display:block; margin-top:8px; color:var(--sky-ink); font-style:normal; font-weight:700; font-size:13px; }}
    .metric-button {{ cursor:pointer; text-align:left; font:inherit; color:inherit; text-decoration:none; display:block; }}
    .metric-button:hover,.metric-button:focus {{ border-color:#8cc7ee; box-shadow:0 0 0 3px rgba(14,116,144,.12); outline:0; }}
    .grid {{ display:grid; grid-template-columns:1.1fr .9fr; gap:16px; align-items:start; }}
    section {{ border:1px solid var(--line); background:var(--paper); border-radius:8px; padding:16px; }}
    .brief-list {{ list-style:none; padding:0; margin:0; display:grid; gap:10px; }}
    .brief-list li {{ display:grid; gap:4px; padding-bottom:10px; border-bottom:1px solid var(--line); }}
    .brief-list li:last-child {{ border-bottom:0; padding-bottom:0; }}
    .brief-list span,.queue-meta,.queue-item small,.empty {{ color:var(--muted); font-size:13px; }}
    .brief-list strong {{ font-size:15px; line-height:1.4; }}
    .queue-list {{ display:grid; gap:10px; }}
    .queue-item {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:var(--wash); }}
    .queue-head {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
    .queue-head strong {{ font-size:15px; }}
    .rank {{ font-weight:700; color:var(--sky-ink); }}
    .queue-meta {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }}
    .queue-meta span {{ background:#fff; border:1px solid var(--line); border-radius:999px; padding:5px 8px; }}
    .queue-item p {{ margin:10px 0 8px; overflow-wrap:anywhere; }}
    .data-table {{ width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }}
    th,td {{ border-bottom:1px solid var(--line); text-align:left; padding:9px 8px; vertical-align:top; overflow-wrap:anywhere; }}
    th {{ color:var(--muted); font-weight:600; }}
    .review-panel {{ display:none; position:fixed; inset:0; z-index:40; overflow:auto; padding:22px; background:rgba(15,32,39,.42); }}
    .review-panel:target {{ display:block; }}
    .review-dialog {{ width:min(980px,calc(100vw - 28px)); margin:0 auto; border:1px solid var(--line); border-radius:8px; padding:0; color:var(--ink); background:#fff; box-shadow:0 20px 80px rgba(15,32,39,.28); }}
    .dialog-top {{ position:sticky; top:0; background:#fff; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:16px; padding:16px; z-index:1; }}
    .dialog-top h2 {{ margin-bottom:4px; }}
    .dialog-top p {{ margin:0; color:var(--muted); }}
    .dialog-close,.review-form button {{ border:1px solid var(--line); border-radius:6px; background:#fff; color:#0f4f77; padding:8px 10px; font-weight:700; cursor:pointer; }}
    .review-list {{ display:grid; gap:12px; padding:16px; background:var(--wash); }}
    .review-card {{ border:1px solid var(--line); border-radius:8px; background:#fff; padding:14px; }}
    .review-head {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }}
    .review-head strong {{ font-size:16px; }}
    .review-details {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px 14px; margin:0 0 12px; }}
    .review-details div {{ border-bottom:1px solid var(--line); padding-bottom:8px; }}
    .review-details dt {{ color:var(--muted); font-size:12px; font-weight:700; margin-bottom:4px; }}
    .review-details dd {{ margin:0; overflow-wrap:anywhere; line-height:1.35; }}
    .review-form {{ display:grid; grid-template-columns:190px minmax(180px,1fr) auto minmax(150px,auto); gap:10px; align-items:end; }}
    .review-form label {{ display:grid; gap:5px; color:var(--muted); font-size:12px; font-weight:700; }}
    .review-form select,.review-form textarea {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:8px; font:inherit; color:var(--ink); }}
    .review-form textarea {{ resize:vertical; min-height:42px; }}
    .save-state {{ color:var(--muted); font-size:13px; align-self:center; }}
    @media (max-width:980px) {{ .metrics {{ grid-template-columns:repeat(3,1fr); }} .grid,.hero {{ grid-template-columns:1fr; }} .links {{ justify-content:flex-start; }} }}
    @media (max-width:760px) {{ .review-details,.review-form {{ grid-template-columns:1fr; }} .dialog-top {{ display:grid; }} }}
    @media (max-width:640px) {{ main,header {{ padding-left:16px; padding-right:16px; }} .metrics {{ grid-template-columns:1fr 1fr; }} .data-table {{ display:block; overflow-x:auto; }} }}
  </style>
</head>
<body>
  <header>
    <div class="hero">
      <div>
        <h1>FUNDz Command Center</h1>
        <p class="sub">Friendly safe-mode view. FUNDz is awake for local reporting, but inactive for client-facing sends, live replies, DF/AutoFox edits, and webhook wiring.</p>
        <div class="chips">{chips}</div>
      </div>
      <nav class="links">{links}</nav>
    </div>
  </header>
  <main>
    <div class="metrics">{card_html}</div>
    {owner_review_panel}
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
  {owner_review_script}
</body>
</html>
"""


def render_locked_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FUNDz Command Center Locked</title>
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
    <h1>FUNDz Command Center is protected</h1>
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

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        self.send_body(status, json.dumps(payload), "application/json; charset=utf-8")

    def read_request_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 20_000:
            raise ValueError("Invalid request body.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid JSON request body.") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

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
        if parsed.path.startswith("/files/"):
            slug = parsed.path.removeprefix("/files/").strip("/")
            target = SAFE_FILES.get(slug)
            if not target:
                self.send_body(404, "Unknown Command Center file.\n", "text/plain; charset=utf-8")
                return
            content_type = "application/json; charset=utf-8" if target.suffix == ".json" else "text/plain; charset=utf-8"
            self.send_body(200, read_text(target), content_type)
            return
        self.send_body(404, "Not found.\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.authorized():
            self.send_json(403, {"ok": False, "error": "Owner token required."})
            return
        if parsed.path == "/review-action":
            try:
                saved = save_owner_review_action(self.read_request_json())
            except ValueError as error:
                self.send_json(400, {"ok": False, "error": str(error)})
                return
            self.send_json(200, {"ok": True, **saved})
            return
        self.send_json(404, {"ok": False, "error": "Not found."})


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
    print(f"FUNDz Command Center listening on http://{host}:{port}")
    print("Owner URL: stored locally in data/local/command-center/fundz-command-center-domain.json")
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
