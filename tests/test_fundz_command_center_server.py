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
                        "send_kill_switch": {"status": "ready_but_gated"},
                        "work_queue": [
                            {
                                "work_order_id": "WO-1",
                                "client_name": "Ada Lovelace",
                                "queue_status": "Hold",
                                "lane": "billing-review",
                                "next_step": "Verify billing.",
                                "proof_required": "Billing proof.",
                                "evidence": "local.csv",
                            }
                        ],
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

        self.assertIn("FUNDz Command Center", html)
        self.assertIn("Ada Lovelace", html)
        self.assertIn("required 2 min before live send", html)
        self.assertIn("token=owner-token", html)
        self.assertIn("inactive for client-facing sends", html)
        self.assertIn("data-open-owner-review", html)
        self.assertIn("Needs Brandon", html)
        self.assertIn("Save Local Fix", html)

    def test_locked_page_is_friendly_without_secret(self) -> None:
        html = server.render_locked_page()

        self.assertIn("protected", html)
        self.assertIn("Owner token required", html)
        self.assertNotIn("?token=", html)

    def test_owner_review_action_is_saved_locally_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            command_json = base / "command.json"
            actions_json = base / "actions.json"
            actions_jsonl = base / "actions.jsonl"
            command_json.write_text(
                json.dumps(
                    {
                        "work_queue": [
                            {
                                "work_order_id": "WO-1",
                                "client_name": "Ada Lovelace",
                                "queue_status": "Hold",
                                "priority_score": 10,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(server, "COMMAND_CENTER_JSON", command_json),
                mock.patch.object(server, "OWNER_REVIEW_ACTIONS_JSON", actions_json),
                mock.patch.object(server, "OWNER_REVIEW_ACTIONS_JSONL", actions_jsonl),
            ):
                saved = server.save_owner_review_action(
                    {"work_order_id": "WO-1", "action": "fixed_locally", "note": "Reviewed billing."}
                )

            stored = json.loads(actions_json.read_text(encoding="utf-8"))
            jsonl_text = actions_jsonl.read_text(encoding="utf-8")

        self.assertTrue(saved["local_only"])
        self.assertTrue(saved["no_live_send"])
        self.assertEqual(saved["action_label"], "Problem fixed locally")
        self.assertEqual(stored["items"]["WO-1"]["note"], "Reviewed billing.")
        self.assertIn('"work_order_id": "WO-1"', jsonl_text)

    def test_owner_review_action_rejects_non_review_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            command_json = Path(temp) / "command.json"
            command_json.write_text(
                json.dumps({"work_queue": [{"work_order_id": "WO-1", "client_name": "Ada", "queue_status": "Done"}]}),
                encoding="utf-8",
            )
            with mock.patch.object(server, "COMMAND_CENTER_JSON", command_json):
                with self.assertRaises(ValueError):
                    server.save_owner_review_action({"work_order_id": "WO-1", "action": "fixed_locally"})


if __name__ == "__main__":
    unittest.main()
