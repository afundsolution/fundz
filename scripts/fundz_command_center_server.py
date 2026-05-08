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
    queue_status = {}
    for row in report.get("work_queue", []) if isinstance(report.get("work_queue"), list) else []:
        status = str(row.get("queue_status") or "Unknown")
        queue_status[status] = queue_status.get(status, 0) + 1
    allowed_now = sum(1 for row in send_queue if str(row.get("send_allowed_now") or "").lower() == "yes")
    needs_attention = queue_status.get("Needs Brandon", 0) + queue_status.get("Hold", 0) + queue_status.get("Proof Needed", 0)
    cards = [
        ("Live Sends", "Off", "client-facing work is inactive"),
        ("Active Clients", summary.get("active_clients", 0), "tracked locally"),
        ("Needs Attention", needs_attention, "hold, proof, or Brandon"),
        ("Next Messages", len(send_queue), f"{allowed_now} allowed now"),
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
    @media (max-width:980px) {{ .metrics {{ grid-template-columns:repeat(3,1fr); }} .grid,.hero {{ grid-template-columns:1fr; }} .links {{ justify-content:flex-start; }} }}
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
