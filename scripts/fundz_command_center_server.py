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


def render_home(token: str) -> str:
    report = read_json(COMMAND_CENTER_JSON)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    send_queue = report.get("next_send_queue") if isinstance(report.get("next_send_queue"), list) else []
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    queue_status = {}
    for row in report.get("work_queue", []) if isinstance(report.get("work_queue"), list) else []:
        status = str(row.get("queue_status") or "Unknown")
        queue_status[status] = queue_status.get(status, 0) + 1
    cards = [
        ("Active Clients", summary.get("active_clients", 0)),
        ("Needs Brandon/Hold", queue_status.get("Needs Brandon", 0) + queue_status.get("Hold", 0)),
        ("Next Sends", len(send_queue)),
        ("Kill Switch", kill_switch.get("status", "unknown")),
    ]
    card_html = "".join(
        f"<div class='metric'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in cards
    )
    queue_rows = ""
    for row in send_queue[:8]:
        queue_rows += (
            "<tr>"
            f"<td>{html.escape(str(row.get('queue_rank') or ''))}</td>"
            f"<td>{html.escape(str(row.get('client_or_lead') or ''))}</td>"
            f"<td>{html.escape(str(row.get('channel') or ''))}</td>"
            f"<td>{html.escape(str(row.get('owner_notice_status') or ''))}</td>"
            f"<td>{html.escape(str(row.get('send_allowed_now') or 'no'))}</td>"
            "</tr>"
        )
    if not queue_rows:
        queue_rows = "<tr><td colspan='5'>No next-send rows generated.</td></tr>"
    links = "".join(
        f"<a href='{auth_link(slug, token)}'>{html.escape(label)}</a>"
        for slug, label in (
            ("command-center", "Command Center"),
            ("daily-board", "Daily Board"),
            ("send-visibility", "Send Visibility"),
            ("next-send-queue", "Next Send Queue"),
            ("work-queue", "Work Queue"),
            ("kill-switch", "Kill Switch"),
            ("json", "JSON"),
        )
    )
    daily = html.escape(compact_markdown(DAILY_BOARD_MD)[:1400])
    generated = html.escape(str(report.get("generated_at") or "not generated"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FUNDz Command Center</title>
  <style>
    :root {{ color-scheme: light; --ink:#172026; --muted:#63717a; --line:#d8e0e5; --panel:#f7f9fa; --ok:#166534; --warn:#92400e; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:#ffffff; }}
    header {{ padding:24px 28px 16px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-size:26px; letter-spacing:0; }}
    .sub {{ margin-top:6px; color:var(--muted); }}
    main {{ padding:22px 28px 36px; max-width:1180px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:12px; margin-bottom:18px; }}
    .metric {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:14px; min-height:72px; }}
    .metric span {{ display:block; color:var(--muted); font-size:13px; }}
    .metric strong {{ display:block; margin-top:8px; font-size:22px; }}
    .links {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 20px; }}
    .links a {{ border:1px solid var(--line); border-radius:6px; padding:8px 10px; color:#0f4f77; text-decoration:none; background:#fff; }}
    section {{ margin-top:20px; }}
    h2 {{ font-size:18px; margin:0 0 10px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ border-bottom:1px solid var(--line); text-align:left; padding:9px 8px; vertical-align:top; }}
    th {{ color:var(--muted); font-weight:600; }}
    pre {{ white-space:pre-wrap; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; overflow:auto; }}
    @media (max-width:760px) {{ main,header {{ padding-left:16px; padding-right:16px; }} .metrics {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>FUNDz Command Center</h1>
    <div class="sub">Protected owner dashboard. Generated: {generated}</div>
  </header>
  <main>
    <div class="metrics">{card_html}</div>
    <nav class="links">{links}</nav>
    <section>
      <h2>Daily Board</h2>
      <pre>{daily}</pre>
    </section>
    <section>
      <h2>Next Send Queue</h2>
      <table>
        <thead><tr><th>#</th><th>Client/Lead</th><th>Channel</th><th>Owner Notice</th><th>Allowed Now</th></tr></thead>
        <tbody>{queue_rows}</tbody>
      </table>
    </section>
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
            self.send_body(403, "FUNDz Command Center requires the owner token.\n", "text/plain; charset=utf-8")
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
