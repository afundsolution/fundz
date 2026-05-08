from __future__ import annotations

import os
import unittest
from unittest import mock

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_owner_command as owner_command


class FundzOwnerCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_health_command_is_safe_without_approval(self) -> None:
        decision = owner_command.decide_command("FUNDz health check", sender="+18325551234")

        self.assertEqual(decision.command, "health")
        self.assertFalse(decision.requires_approval)
        self.assertFalse(decision.blocked)

    def test_sender_allowlist_blocks_unknown_sender(self) -> None:
        os.environ["FUNDZ_OWNER_COMMAND_SENDERS"] = "+18325551234"

        decision = owner_command.decide_command("FUNDz health check", sender="+19998887777")

        self.assertTrue(decision.blocked)
        self.assertIn("not owner-allowlisted", decision.reason)

    def test_fix_bridge_requires_approval_phrase(self) -> None:
        decision = owner_command.decide_command("FUNDz fix bridge", sender="+18325551234")

        self.assertEqual(decision.command, "fix_bridge")
        self.assertTrue(decision.requires_approval)
        self.assertTrue(decision.blocked)

    def test_approved_fix_bridge_is_allowed(self) -> None:
        decision = owner_command.decide_command("FUNDz APPROVE fix bridge", sender="+18325551234")

        self.assertEqual(decision.command, "fix_bridge")
        self.assertEqual(decision.action_level, "apply_approved_fix")
        self.assertTrue(decision.approved)
        self.assertFalse(decision.blocked)

    def test_bulk_and_pilot_sends_are_blocked(self) -> None:
        for text in ("FUNDz bulk send updates", "FUNDz send pilot to Erika"):
            with self.subTest(text=text):
                decision = owner_command.decide_command(text, sender="+18325551234")

                self.assertTrue(decision.blocked)
                self.assertIn(decision.command, owner_command.BLOCKED_COMMANDS)

    def test_execute_health_writes_receipt_reply(self) -> None:
        with (
            mock.patch.object(owner_command, "load_env_file"),
            mock.patch.object(owner_command, "read_url", return_value=(True, '{"ok":true}')),
        ):
            receipt = owner_command.execute_owner_command("FUNDz status", sender="+18325551234")

        self.assertIn("reply", receipt)
        self.assertIn("Bridge: OK", receipt["reply"])
        self.assertTrue((ROOT / receipt["receipt_path"]).exists())


if __name__ == "__main__":
    unittest.main()
