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

    def test_locked_page_is_friendly_without_secret(self) -> None:
        html = server.render_locked_page()

        self.assertIn("protected", html)
        self.assertIn("Owner token required", html)
        self.assertNotIn("?token=", html)


if __name__ == "__main__":
    unittest.main()
