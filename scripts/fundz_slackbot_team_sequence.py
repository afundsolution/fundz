#!/usr/bin/env python3
"""Build the internal Slackbot team sequence for FUNDz/A FUND Solution.

This does not create Slack channels or send Slack messages. It turns the current
FUNDz proof surfaces into a copy-ready operating packet for Slackbot, Slack AI,
LOGIC, Jay, Lucy, and Brandon.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"

WORK_QUEUE_CSV = OUTPUT_DIR / "fundz-work-queue.csv"
DAILY_BOARD_MD = OUTPUT_DIR / "fundz-daily-board.md"
TODAY_BOARD_MD = OUTPUT_DIR / "fundz-today-operating-board.md"
COMMAND_CENTER_MD = OUTPUT_DIR / "fundz-command-center.md"
OWNER_REVIEW_PACKET_MD = OUTPUT_DIR / "fundz-owner-review-packet.md"
GOVERNOR_ALERTS_CSV = OUTPUT_DIR / "fundz-governor-alerts.csv"
SEND_VISIBILITY_MD = OUTPUT_DIR / "fundz-send-visibility-command-center.md"
SEND_GATE_MD = OUTPUT_DIR / "fundz-send-gate-lock.md"
LUCY_BILLING_MD = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-lucy-billing-workqueue.md"
WORKORDER_SOP_MD = ROOT / "assistant" / "jay-lucy-daily-workorder-sop.md"

SLACKBOT_SEQUENCE_MD = OUTPUT_DIR / "fundz-slackbot-team-sequence.md"
SLACKBOT_SEQUENCE_JSON = OUTPUT_DIR / "fundz-slackbot-team-sequence.json"
SLACKBOT_CHANNELS_CSV = OUTPUT_DIR / "fundz-slackbot-team-channels.csv"
SLACKBOT_SOP_MD = ROOT / "assistant" / "fundz-slackbot-team-sequence.md"

CHANNEL_FIELDS = [
    "channel",
    "owner",
    "purpose",
    "recap_setting",
    "slack_ai_use",
    "fundz_logic_boundary",
    "source_files",
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


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def first_nonempty_lines(path: Path, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for line in read_text(path).splitlines():
        clean = line.strip()
        if clean:
            lines.append(clean)
        if len(lines) >= limit:
            break
    return lines


def build_channels() -> list[dict[str, str]]:
    return [
        {
            "channel": "#afs-daily-board",
            "owner": "Brandon",
            "purpose": "One plain-language morning board for what matters now across FUNDz, LOGIC, Lucy, and Jay.",
            "recap_setting": "Daily recap on; mute allowed after recap is configured.",
            "slack_ai_use": "Recap yesterday, summarize today's thread, and turn the board into a short owner brief.",
            "fundz_logic_boundary": "FUNDz/LOGIC decide meaning, proof status, and next action; Slackbot only organizes the board.",
            "source_files": ";".join([relative(DAILY_BOARD_MD), relative(TODAY_BOARD_MD)]),
        },
        {
            "channel": "#fundz-ops",
            "owner": "FUNDz",
            "purpose": "Internal FUNDz operations, safe local autonomy status, customer-service readiness, and blocked work.",
            "recap_setting": "Daily recap on; use summaries for long implementation threads.",
            "slack_ai_use": "Find blockers, summarize proof threads, explain technical status in plain language.",
            "fundz_logic_boundary": "No live bridge, poller, webhook, client reply, campaign, DF/AutoFox edit, or billing edit from Slackbot.",
            "source_files": ";".join([relative(COMMAND_CENTER_MD), relative(SEND_VISIBILITY_MD), relative(SEND_GATE_MD)]),
        },
        {
            "channel": "#logic-disputes",
            "owner": "LOGIC",
            "purpose": "Dispute operations, letter context, bureau response questions, and old-letter lookup requests.",
            "recap_setting": "Daily recap on for leadership; thread summaries for each member issue.",
            "slack_ai_use": "Search Slack for old context and prepare source packets for LOGIC.",
            "fundz_logic_boundary": "LOGIC interprets dispute meaning and review gates; Slackbot does not approve letters or strategy.",
            "source_files": "LOGIC Slackbot tag-team protocol; Slack message/file sources",
        },
        {
            "channel": "#lucy-billing",
            "owner": "Lucy",
            "purpose": "Billing maintenance, payment proof, archive proof, and owner billing decisions.",
            "recap_setting": "Daily recap on; only unresolved proof-backed rows stay active.",
            "slack_ai_use": "Turn billing rows into a checklist and remind Lucy which proof is still missing.",
            "fundz_logic_boundary": "No payment called collected without receipt-level proof; no billing edits from Slackbot.",
            "source_files": relative(LUCY_BILLING_MD),
        },
        {
            "channel": "#jay-workorders",
            "owner": "Jay",
            "purpose": "End-of-day workorder closeout and carried-forward tasks.",
            "recap_setting": "Recap on; huddle notes on if the team meets.",
            "slack_ai_use": "Validate owner, due date, status, evidence, next step, and blocker language before closeout.",
            "fundz_logic_boundary": "A summary is not proof; workorders close only with evidence or explicit blocker outcome.",
            "source_files": relative(WORKORDER_SOP_MD),
        },
        {
            "channel": "#owner-review",
            "owner": "Brandon",
            "purpose": "Only the decisions Brandon must make: approvals, blockers, proof gaps, and send gates.",
            "recap_setting": "Daily recap on; keep noise low.",
            "slack_ai_use": "Summarize open decisions and locate proof links before asking Brandon.",
            "fundz_logic_boundary": "Approved is a gated queue state, not done; no sends or live changes without action-time approval.",
            "source_files": ";".join([relative(OWNER_REVIEW_PACKET_MD), relative(GOVERNOR_ALERTS_CSV)]),
        },
    ]


def build_prompt_templates() -> dict[str, str]:
    return {
        "slackbot_context_packet": (
            "Search Slack for context the operations team can use. Summarize facts only.\n\n"
            "Topic/client:\nDate range:\nChannels or people to check:\nFiles/canvases to include:\n\n"
            "Return:\n1. What you found\n2. Message/file links\n3. What is missing or uncertain\n"
            "4. Exact question for FUNDz or LOGIC\n5. Reminder/follow-up Slackbot should track\n\n"
            "Do not approve sends, change client strategy, edit billing, or treat summaries as proof."
        ),
        "fundz_decision_prompt": (
            "Use this Slackbot context packet and tell us the next FUNDz operations step.\n\n"
            "Client/member:\nContext summary:\nMessage/file links:\nMissing facts:\nQuestion:\n\n"
            "Return:\n1. What this means\n2. Next action\n3. Owner\n4. Proof needed before closeout\n"
            "5. Whether this needs Lucy, Jay, LOGIC, or Brandon approval"
        ),
        "daily_board_prompt": (
            "Summarize today's A FUND Solution board in plain language for the team.\n\n"
            "Use only posted source files or channel messages. Return:\n1. What matters now\n"
            "2. Blocked\n3. Needs Brandon\n4. Safe local work\n5. Proof needed before anything is called done"
        ),
        "workorder_check_prompt": (
            "Check this /workorder before closeout. Flag missing status, owner, due date, next step, evidence, "
            "privacy issues, and any item marked done without proof. Do not rewrite client-facing copy."
        ),
    }


def build_sequence(
    *,
    work_queue_csv: Path = WORK_QUEUE_CSV,
    daily_board_md: Path = DAILY_BOARD_MD,
    today_board_md: Path = TODAY_BOARD_MD,
    send_visibility_md: Path = SEND_VISIBILITY_MD,
) -> dict[str, Any]:
    work_rows = read_csv_rows(work_queue_csv)
    status_counts = Counter(row.get("queue_status", "") for row in work_rows)
    blocking = sum(status_counts.get(status, 0) for status in ("Blocked", "Failed", "Proof Needed", "Needs Brandon", "Hold"))

    channels = build_channels()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "generated_at": generated_at,
        "mission": "Use Slackbot and Slack AI as the internal team memory, recap, search, reminder, and canvas layer.",
        "role_split": {
            "slackbot": "Finds, summarizes, cites, reminds, explains, drafts internal canvases, and prepares context packets.",
            "fundz_logic": "Interprets operational meaning, checks proof, sets next action, preserves approval gates, and closes work only with evidence.",
        },
        "business_plus_fit": [
            "Conversation and thread summaries for daily catch-up.",
            "AI search answers with citations for prior decisions and proof links.",
            "Recaps for muted monitoring channels.",
            "File summaries for PDFs, spreadsheets, SOPs, and reports shared in Slack.",
            "Workflow automation and canvas generation for checklists and handoffs.",
            "Slackbot for limited weekly personal assistant prompts where the workspace plan allows it.",
        ],
        "current_fundz_context": {
            "work_queue_rows": len(work_rows),
            "status_counts": dict(sorted(status_counts.items())),
            "blocking_or_decision_rows": blocking,
            "daily_board_preview": first_nonempty_lines(daily_board_md, 6),
            "today_board_preview": first_nonempty_lines(today_board_md, 6),
            "send_gate_preview": first_nonempty_lines(send_visibility_md, 8),
        },
        "channels": channels,
        "daily_sequence": [
            {
                "time": "Morning",
                "owner": "Brandon or operator on duty",
                "action": "Post or refresh the daily board in #afs-daily-board, then let Slack AI recap it.",
                "output": "What matters now, blockers, Needs Brandon, safe local work, and proof gaps.",
            },
            {
                "time": "Midday",
                "owner": "FUNDz",
                "action": "Use Slackbot search/summaries to locate missing proof and stale decisions.",
                "output": "Short context packets for FUNDz, LOGIC, Lucy, or Jay.",
            },
            {
                "time": "End of day",
                "owner": "Jay/Lucy",
                "action": "Submit /workorder and run the Slackbot workorder check prompt before closeout.",
                "output": "Every item has status, owner, next step, evidence, and blocker language when needed.",
            },
            {
                "time": "Before closeout",
                "owner": "FUNDz/LOGIC",
                "action": "Confirm Slack summaries match proof files before marking anything Done or Sent.",
                "output": "Receipt-backed closeout or clear carry-forward blocker.",
            },
        ],
        "rollout_steps": [
            "Create the six internal channels manually in Slack.",
            "Pin this sequence packet and the relevant source files/canvases in each channel.",
            "Turn on recaps for #afs-daily-board, #fundz-ops, #logic-disputes, #lucy-billing, and #owner-review.",
            "Use the shared Slackbot context-packet prompt for searches and summaries.",
            "Use FUNDz/LOGIC prompts for decisions, proof status, and next actions.",
            "After one week, compare workorder completion, open blockers, and proof gaps before expanding workflows.",
        ],
        "safety_rules": [
            "Slackbot is internal-only for this rollout.",
            "Slackbot can summarize, search, explain, remind, draft internal canvases, and organize proof links.",
            "Slackbot cannot send client messages, approve dispute strategy, edit DF/AutoFox, change billing, wire webhooks, wake live pollers, or mark Approved rows as Done.",
            "Approved means prepared but gated until receipt-backed proof or explicit blocker outcome exists.",
            "Any live client-facing step still needs Brandon's exact action-time approval and the existing FUNDz send gates.",
            "No full SSNs, full DOBs, full account numbers, passwords, secrets, or private personal data should be placed in shared Slack channels.",
        ],
        "prompt_templates": build_prompt_templates(),
        "source_files": [
            relative(DAILY_BOARD_MD),
            relative(TODAY_BOARD_MD),
            relative(COMMAND_CENTER_MD),
            relative(OWNER_REVIEW_PACKET_MD),
            relative(GOVERNOR_ALERTS_CSV),
            relative(SEND_VISIBILITY_MD),
            relative(SEND_GATE_MD),
            relative(WORKORDER_SOP_MD),
            relative(LUCY_BILLING_MD),
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["current_fundz_context"]["status_counts"]
    lines = [
        "# FUNDz Slackbot Team Sequence",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Mission",
        "",
        report["mission"],
        "",
        "Slackbot is the team librarian and coordinator. FUNDz/LOGIC are the operators that decide meaning, proof, next action, and closeout.",
        "",
        "## Current Queue Truth",
        "",
        f"- Work Queue rows: {report['current_fundz_context']['work_queue_rows']}",
        f"- Blocking or decision rows: {report['current_fundz_context']['blocking_or_decision_rows']}",
        f"- Status counts: {', '.join(f'{key}={value}' for key, value in counts.items() if key)}",
        "",
        "## Channels To Create",
        "",
    ]

    for channel in report["channels"]:
        lines.extend(
            [
                f"### {channel['channel']}",
                "",
                f"- Owner: {channel['owner']}",
                f"- Purpose: {channel['purpose']}",
                f"- Slack AI use: {channel['slack_ai_use']}",
                f"- Boundary: {channel['fundz_logic_boundary']}",
                f"- Sources: {channel['source_files']}",
                "",
            ]
        )

    lines.extend(["## Daily Sequence", ""])
    for item in report["daily_sequence"]:
        lines.extend(
            [
                f"### {item['time']}",
                "",
                f"- Owner: {item['owner']}",
                f"- Action: {item['action']}",
                f"- Output: {item['output']}",
                "",
            ]
        )

    lines.extend(["## Rollout Steps", ""])
    lines.extend(f"- {step}" for step in report["rollout_steps"])
    lines.extend(["", "## Copy-Ready Prompts", ""])
    for name, prompt in report["prompt_templates"].items():
        lines.extend([f"### {name.replace('_', ' ').title()}", "", "```text", prompt, "```", ""])

    lines.extend(["## Safety Rules", ""])
    lines.extend(f"- {rule}" for rule in report["safety_rules"])
    lines.extend(["", "## Source Files", ""])
    lines.extend(f"- {source}" for source in report["source_files"])
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    markdown = render_markdown(report)
    SLACKBOT_SEQUENCE_MD.parent.mkdir(parents=True, exist_ok=True)
    SLACKBOT_SEQUENCE_MD.write_text(markdown, encoding="utf-8")
    SLACKBOT_SOP_MD.write_text(markdown, encoding="utf-8")
    write_json(SLACKBOT_SEQUENCE_JSON, report)
    write_csv(SLACKBOT_CHANNELS_CSV, report["channels"], CHANNEL_FIELDS)
    return {
        "markdown": SLACKBOT_SEQUENCE_MD,
        "sop": SLACKBOT_SOP_MD,
        "json": SLACKBOT_SEQUENCE_JSON,
        "channels": SLACKBOT_CHANNELS_CSV,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the internal FUNDz Slackbot team sequence.")
    parser.parse_args()
    report = build_sequence()
    paths = write_outputs(report)
    print(f"Wrote {paths['markdown']}")
    print(f"Wrote {paths['sop']}")
    print(f"Wrote {paths['json']}")
    print(f"Wrote {paths['channels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
