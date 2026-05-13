from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_command_center_server as server


class FundzCommandCenterServerTests(unittest.TestCase):
    def test_token_is_created_in_local_domain_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "domain.json"
            with (
                mock.patch.object(server, "DOMAIN_CONFIG", config),
                mock.patch.dict(server.os.environ, {}, clear=True),
            ):
                token = server.command_center_token()

            saved = json.loads(config.read_text(encoding="utf-8"))

        self.assertGreater(len(token), 20)
        self.assertEqual(saved["token"], token)
        self.assertIn("fundz-command.afundsolution.com", saved["owner_url"])

    def test_render_home_requires_no_secret_in_markup_except_token_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            command_json = base / "command.json"
            daily = base / "daily.md"
            command_json.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-08T00:00:00-0500",
                        "summary": {"active_clients": 2},
                        "safety_gate": {"state": "Review local runtime", "note": "client sends remain off"},
                        "send_kill_switch": {"status": "ready_but_gated"},
                        "maintenance_cleanup_summary": {
                            "billing_decisions": {"active_urgent_billing_review": 1, "active_date_sensitive_billing_review": 13},
                            "duplicate_review_clients": 57,
                        },
                        "archive_receipt_trail": {"live_confirmed": 29, "exceptions": 7},
                        "next_send_queue": [
                            {
                                "queue_rank": 1,
                                "client_or_lead": "Ada Lovelace",
                                "channel": "Email",
                                "owner_notice_status": "required_2_min_before_live_send",
                                "send_allowed_now": "no",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            daily.write_text("Today's Objective: Test the board.\n", encoding="utf-8")
            with (
                mock.patch.object(server, "COMMAND_CENTER_JSON", command_json),
                mock.patch.object(server, "DAILY_BOARD_MD", daily),
            ):
                html = server.render_home("owner-token")

        self.assertIn("A FUND Solution Command Center", html)
        self.assertIn("Safety Gate", html)
        self.assertIn("One Command Center", html)
        self.assertIn("FUNDz is one source workflow", html)
        self.assertIn("Work Queue = task rows", html)
        self.assertIn("Next Send Queue = preview only", html)
        self.assertIn("Today Board", html)
        self.assertIn("Billing Maintenance", html)
        self.assertIn("Archive Receipts", html)
        self.assertIn("Send Gate Lock", html)
        self.assertIn("Ada Lovelace", html)
        self.assertIn("required 2 min before live send", html)
        self.assertIn("/view/work-queue?token=owner-token", html)
        self.assertIn("token=owner-token", html)
        self.assertIn("inactive for client-facing sends", html)

    def test_render_file_page_wraps_csv_as_friendly_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            work_queue = base / "work-queue.csv"
            work_queue.write_text(
                "queue_status,client_name,lane,owner,due_date,next_step,proof_required,evidence\n"
                "Needs Brandon,Ada Lovelace,onboarding,FUNDz,2026-05-08,Review proof,Receipt,local-proof.md\n",
                encoding="utf-8",
            )
            with mock.patch.dict(server.SAFE_FILES, {"work-queue": work_queue}):
                html = server.render_file_page("work-queue", "owner-token")

        self.assertIn("Work Queue", html)
        self.assertIn("Ada Lovelace", html)
        self.assertIn("Needs Brandon", html)
        self.assertIn("<table", html)
        self.assertIn("Dashboard Home", html)
        self.assertIn("/files/work-queue?token=owner-token", html)
        self.assertIn("Safe-mode note", html)

    def test_render_file_page_wraps_markdown_as_readable_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            daily = base / "daily.md"
            daily.write_text(
                "# A FUND Solution Daily Board\n\nGenerated: now\n\n- Next Action: Keep local reporting readable.\n",
                encoding="utf-8",
            )
            with mock.patch.dict(server.SAFE_FILES, {"daily-board": daily}):
                html = server.render_file_page("daily-board", "owner-token")

        self.assertIn("Daily Board", html)
        self.assertIn("<h1>A FUND Solution Daily Board</h1>", html)
        self.assertIn("Keep local reporting readable", html)
        self.assertIn("Open Raw File", html)

    def test_locked_page_is_friendly_without_secret(self) -> None:
        html = server.render_locked_page()

        self.assertIn("protected", html)
        self.assertIn("Owner token required", html)
        self.assertNotIn("?token=", html)


if __name__ == "__main__":
    unittest.main()
