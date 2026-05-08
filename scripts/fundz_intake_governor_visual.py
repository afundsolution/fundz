#!/usr/bin/env python3
"""Render a local visual dashboard for the FUNDz Intake Governor."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"
DEFAULT_REPORT = OUTPUT_DIR / "fundz-intake-governor.json"
DEFAULT_OUTPUT = OUTPUT_DIR / "fundz-intake-governor-dashboard.html"

STATUS_COLORS = {
    "Blocked": "#b42318",
    "Failed": "#d92d20",
    "Hold": "#6941c6",
    "Needs Brandon": "#b54708",
    "Proof Needed": "#175cd3",
    "Approved": "#067647",
    "Sent": "#0e9384",
    "Done": "#027a48",
}

SEVERITY_COLORS = {
    "high": "#b42318",
    "decision": "#b54708",
    "watch": "#175cd3",
}


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_report(path: Path = DEFAULT_REPORT) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: int, total: int) -> float:
    if total <= 0:
        return 0
    return round((value / total) * 100, 1)


def render_status_bars(status_counts: dict[str, int]) -> str:
    total = sum(int(value) for value in status_counts.values())
    rows = []
    for status, count in sorted(status_counts.items(), key=lambda item: (-int(item[1]), item[0])):
        color = STATUS_COLORS.get(status, "#475467")
        percent = pct(int(count), total)
        rows.append(
            f"""
            <div class="bar-row">
              <div class="bar-label"><span>{esc(status)}</span><strong>{esc(count)}</strong></div>
              <div class="bar-track"><div class="bar-fill" style="width:{percent}%;background:{color}"></div></div>
            </div>
            """
        )
    return "\n".join(rows)


def render_flow(report: dict[str, Any]) -> str:
    phone = report["summary"].get("phone_triage_rows", 0)
    work = report["summary"].get("work_queue_rows", 0)
    alerts = report["summary"].get("alerts", 0)
    candidates = report["summary"].get("phone_candidates", 0)
    approval = report["summary"].get("needs_brandon_approval", 0)
    auto_create = report["summary"].get("safe_to_auto_create", 0)
    return f"""
      <section class="flow-band" aria-label="Intake flow">
        <div class="flow-node"><span>Personal Phone</span><strong>{phone}</strong></div>
        <div class="flow-node"><span>Work Queue</span><strong>{work}</strong></div>
        <div class="flow-node"><span>Governor Alerts</span><strong>{alerts}</strong></div>
        <div class="flow-arrow">to</div>
        <div class="flow-node governor"><span>Intake Governor</span><strong>safe filter</strong></div>
        <div class="flow-arrow">to</div>
        <div class="flow-node gate"><span>Safety Gate</span><strong>{approval} approval</strong></div>
        <div class="flow-node output"><span>Candidates</span><strong>{candidates}</strong></div>
        <div class="flow-node output"><span>Auto-create</span><strong>{auto_create}</strong></div>
      </section>
    """


def render_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return '<p class="empty">No intake candidates.</p>'
    rows = []
    for item in candidates:
        rows.append(
            f"""
            <tr>
              <td>{esc(item.get("intake_id"))}</td>
              <td>{esc(item.get("contact"))}</td>
              <td>{esc(item.get("queue_status"))}</td>
              <td>{esc(item.get("owner"))}</td>
              <td>{esc(item.get("approval_needed"))}</td>
              <td>{esc(item.get("shared_safe"))}</td>
              <td>{esc(item.get("next_step"))}</td>
            </tr>
            """
        )
    return f"""
      <table>
        <thead>
          <tr><th>ID</th><th>Contact</th><th>Status</th><th>Owner</th><th>Approval</th><th>Shared safe</th><th>Next step</th></tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    """


def render_alerts(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return '<p class="empty">No alerts.</p>'
    rows = []
    for item in alerts:
        severity = item.get("severity", "")
        color = SEVERITY_COLORS.get(severity, "#475467")
        rows.append(
            f"""
            <tr>
              <td><span class="severity" style="background:{color}"></span>{esc(severity)}</td>
              <td>{esc(item.get("source"))}</td>
              <td>{esc(item.get("contact"))}</td>
              <td>{esc(item.get("owner"))}</td>
              <td>{esc(item.get("reason"))}</td>
              <td>{esc(item.get("next_step"))}</td>
            </tr>
            """
        )
    return f"""
      <table>
        <thead>
          <tr><th>Severity</th><th>Source</th><th>Contact</th><th>Owner</th><th>Reason</th><th>Next step</th></tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    """


def render_rules(rules: list[str]) -> str:
    return "\n".join(f"<li>{esc(rule)}</li>" for rule in rules)


def render_dashboard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    communication = report.get("communication_board", {})
    status_counts = {str(k): int(v) for k, v in report.get("status_counts", {}).items()}
    generated = esc(report.get("generated_at", ""))
    mission = esc(report.get("bot", {}).get("mission", ""))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FUNDz Intake Governor</title>
  <style>
    :root {{
      --ink: #101828;
      --muted: #667085;
      --line: #d0d5dd;
      --soft: #f2f4f7;
      --paper: #ffffff;
      --accent: #175cd3;
      --ok: #067647;
      --warn: #b54708;
      --danger: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #f8fafc;
      font-size: 14px;
      line-height: 1.45;
    }}
    header {{
      background: var(--paper);
      border-bottom: 1px solid var(--line);
      padding: 18px 24px;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      font-weight: 760;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 16px;
      letter-spacing: 0;
    }}
    p {{ margin: 0; color: var(--muted); }}
    main {{
      width: min(1280px, 100%);
      margin: 0 auto;
      padding: 18px 20px 28px;
    }}
    .subhead {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-top: 6px;
      color: var(--muted);
      flex-wrap: wrap;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}
    .metric {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 86px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .metric strong {{
      display: block;
      font-size: 28px;
      line-height: 1;
      letter-spacing: 0;
    }}
    .metric.danger strong {{ color: var(--danger); }}
    .metric.warn strong {{ color: var(--warn); }}
    .metric.ok strong {{ color: var(--ok); }}
    section {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 16px;
      padding: 16px;
    }}
    .flow-band {{
      display: grid;
      grid-template-columns: repeat(3, minmax(120px, 1fr)) 44px minmax(140px, 1.2fr) 44px repeat(3, minmax(120px, 1fr));
      align-items: stretch;
      gap: 8px;
      overflow-x: auto;
    }}
    .flow-node {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      padding: 11px;
      background: #fcfcfd;
      min-width: 124px;
    }}
    .flow-node span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .flow-node strong {{ font-size: 18px; letter-spacing: 0; }}
    .flow-node.governor {{ border-left-color: var(--ok); }}
    .flow-node.gate {{ border-left-color: var(--warn); }}
    .flow-node.output {{ border-left-color: #475467; }}
    .flow-arrow {{
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      min-width: 36px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: minmax(260px, 0.9fr) minmax(320px, 1.1fr);
      gap: 16px;
      align-items: start;
    }}
    .bar-row {{ margin-bottom: 12px; }}
    .bar-label {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 5px;
      gap: 8px;
    }}
    .bar-label span {{ color: var(--muted); }}
    .bar-track {{
      width: 100%;
      height: 12px;
      background: var(--soft);
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-fill {{ height: 100%; border-radius: 999px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      padding: 9px 8px;
      overflow-wrap: anywhere;
    }}
    th {{
      color: #344054;
      background: #f9fafb;
      font-size: 12px;
      font-weight: 700;
    }}
    .severity {{
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      margin-right: 7px;
    }}
    .rules {{
      columns: 2;
      color: #344054;
      margin: 0;
      padding-left: 18px;
    }}
    .empty {{ color: var(--muted); padding: 4px 0; }}
    .source-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(160px, 1fr));
      gap: 10px;
    }}
    .source-row {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fcfcfd;
    }}
    .source-row span {{ color: var(--muted); display: block; font-size: 12px; }}
    .source-row strong {{ font-size: 18px; }}
    @media (max-width: 980px) {{
      .metrics {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
      .two-col {{ grid-template-columns: 1fr; }}
      .flow-band {{ grid-template-columns: repeat(8, minmax(126px, 1fr)); }}
      .rules {{ columns: 1; }}
      .source-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>FUNDz Intake Governor</h1>
    <div class="subhead">
      <p>{mission}</p>
      <p>Generated {generated}</p>
    </div>
  </header>
  <main>
    <div class="metrics">
      <div class="metric"><span>Work Queue Rows</span><strong>{esc(summary.get("work_queue_rows"))}</strong></div>
      <div class="metric danger"><span>Blocking Rows</span><strong>{esc(summary.get("blocking_work_queue_rows"))}</strong></div>
      <div class="metric warn"><span>Needs Brandon</span><strong>{esc(summary.get("needs_brandon_approval"))}</strong></div>
      <div class="metric"><span>Phone Triage</span><strong>{esc(summary.get("phone_triage_rows"))}</strong></div>
      <div class="metric ok"><span>Auto-create</span><strong>{esc(summary.get("safe_to_auto_create"))}</strong></div>
      <div class="metric"><span>Alerts</span><strong>{esc(summary.get("alerts"))}</strong></div>
    </div>

    {render_flow(report)}

    <div class="two-col">
      <section>
        <h2>Work Queue Status</h2>
        {render_status_bars(status_counts)}
      </section>
      <section>
        <h2>Communication Board</h2>
        <div class="source-grid">
          <div class="source-row"><span>Active Rows</span><strong>{esc(communication.get("rows"))}</strong></div>
          <div class="source-row"><span>Mobile App SMS Allowed</span><strong>{esc(communication.get("mobile_app_sms_allowed", {}).get("yes", 0))}</strong></div>
          <div class="source-row"><span>Mobile App SMS Blocked</span><strong>{esc(communication.get("mobile_app_sms_allowed", {}).get("no", 0))}</strong></div>
        </div>
      </section>
    </div>

    <section>
      <h2>Approval Candidates</h2>
      {render_candidates(report.get("candidates", []))}
    </section>

    <section>
      <h2>Compressed Alerts</h2>
      {render_alerts(report.get("alerts", []))}
    </section>

    <section>
      <h2>Safety Rules</h2>
      <ul class="rules">{render_rules(report.get("rules", []))}</ul>
    </section>
  </main>
</body>
</html>
"""


def write_dashboard(report_path: Path = DEFAULT_REPORT, output_path: Path = DEFAULT_OUTPUT) -> Path:
    report = load_report(report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(report), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a local visual dashboard for the FUNDz Intake Governor.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = write_dashboard(args.report, args.output)
    print(f"FUNDz Intake Governor dashboard: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
