from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_slackbot_team_sequence as slackseq


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class FundzSlackbotTeamSequenceTests(unittest.TestCase):
    def test_build_sequence_counts_work_queue_and_keeps_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            work_queue = base / "work.csv"
            daily = base / "daily.md"
            today = base / "today.md"
            send_gate = base / "send.md"
            write_rows(
                work_queue,
                ["queue_status", "client_name"],
                [
                    {"queue_status": "Approved", "client_name": "Ada"},
                    {"queue_status": "Needs Brandon", "client_name": "Ben"},
                    {"queue_status": "Done", "client_name": "Cy"},
                    {"queue_status": "Blocked", "client_name": "Dee"},
                ],
            )
            daily.write_text("# Daily Board\n\n- Next action: review blockers\n", encoding="utf-8")
            today.write_text("# Today\n\n- Safe local work only\n", encoding="utf-8")
            send_gate.write_text("# Send Gate\n\n- live send allowed: false\n", encoding="utf-8")

            report = slackseq.build_sequence(
                work_queue_csv=work_queue,
                daily_board_md=daily,
                today_board_md=today,
                send_visibility_md=send_gate,
            )

        self.assertEqual(report["current_fundz_context"]["work_queue_rows"], 4)
        self.assertEqual(report["current_fundz_context"]["blocking_or_decision_rows"], 2)
        self.assertIn("#afs-daily-board", {row["channel"] for row in report["channels"]})
        self.assertEqual(report["live_slack_setup"]["channel_creation_status"], "created_public_channels_verified")
        self.assertTrue(all(row["slack_channel_id"] for row in report["channels"]))
        self.assertTrue(any("cannot send client messages" in rule for rule in report["safety_rules"]))

    def test_prompt_templates_separate_slackbot_from_fundz_logic(self) -> None:
        prompts = slackseq.build_prompt_templates()

        self.assertIn("Search Slack for context", prompts["slackbot_context_packet"])
        self.assertIn("Do not approve sends", prompts["slackbot_context_packet"])
        self.assertIn("Proof needed before closeout", prompts["fundz_decision_prompt"])

    def test_write_outputs_creates_markdown_json_and_channel_csv(self) -> None:
        report = {
            "generated_at": "2026-05-13T10:00:00-05:00",
            "mission": "Use Slackbot safely.",
            "current_fundz_context": {
                "work_queue_rows": 2,
                "blocking_or_decision_rows": 1,
                "status_counts": {"Approved": 1, "Needs Brandon": 1},
            },
            "channels": [
                {
                    "channel": "#afs-daily-board",
                    "slack_channel_id": "C0B35JETX8F",
                    "slack_url": "https://app.slack.com/client/T0335UDK8AG/C0B35JETX8F",
                    "slack_status": "created_public_not_archived",
                    "member_status": "all_3_workspace_members_added",
                    "owner": "Brandon",
                    "purpose": "Daily board.",
                    "recap_setting": "Daily",
                    "slack_ai_use": "Summarize.",
                    "fundz_logic_boundary": "No sends.",
                    "source_files": "daily.md",
                }
            ],
            "daily_sequence": [
                {
                    "time": "Morning",
                    "owner": "Brandon",
                    "action": "Post board.",
                    "output": "Plain status.",
                }
            ],
            "rollout_steps": ["Use live channels."],
            "live_slack_setup": {
                "canvas_url": "https://afundsolution.slack.com/docs/T0335UDK8AG/F0B3LU8H6TC",
                "kickoff_message_url": "https://afundsolution.slack.com/archives/C0AUEF81TKM/p1778688658173279",
                "kickoff_channel": "#logic-briefing",
                "channel_creation_status": "created_public_channels_verified",
                "channel_count": 1,
                "member_status": "All 3 workspace members were added to each created channel.",
                "verification": "Verified by Slack channel lookup.",
                "connector_limit": "Verified through Slack.",
            },
            "prompt_templates": {"test_prompt": "Do the safe thing."},
            "safety_rules": ["Slackbot cannot send client messages."],
            "source_files": ["daily.md"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                mock.patch.object(slackseq, "SLACKBOT_SEQUENCE_MD", base / "sequence.md"),
                mock.patch.object(slackseq, "SLACKBOT_SOP_MD", base / "sop.md"),
                mock.patch.object(slackseq, "SLACKBOT_SEQUENCE_JSON", base / "sequence.json"),
                mock.patch.object(slackseq, "SLACKBOT_CHANNELS_CSV", base / "channels.csv"),
            ):
                paths = slackseq.write_outputs(report)

            markdown = paths["markdown"].read_text(encoding="utf-8")
            self.assertTrue(paths["json"].exists())
            self.assertTrue(paths["channels"].exists())
            self.assertIn("Slackbot is the team librarian", markdown)
            self.assertIn("created_public_channels_verified", markdown)
            self.assertIn("C0B35JETX8F", markdown)
            self.assertIn("Slackbot cannot send client messages", markdown)


if __name__ == "__main__":
    unittest.main()
