from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_runtime_wake_checklist as wake


class FundzRuntimeWakeChecklistTests(unittest.TestCase):
    def test_build_checklist_is_ready_when_only_reporting_screen_is_awake(self) -> None:
        with (
            mock.patch.object(wake, "active_screen_names", return_value=["fundz-command-center"]),
            mock.patch.object(wake, "active_live_processes", return_value=[]),
            mock.patch.object(wake, "kill_switch_status", return_value={"enabled": True, "status": "on_blocks_live_replies", "path": "kill.json", "exists": True, "reason": ""}),
            mock.patch.object(wake, "current_gate_state", return_value={
                "credit_tracker_dry_run": True,
                "highlevel_poller_live": False,
                "highlevel_controlled_reply_approved": False,
                "webhook_controlled_reply_approved": False,
                "allow_after_hours_sends": False,
            }),
            mock.patch.object(wake, "file_status", return_value={"path": "proof.jsonl", "exists": False, "bytes": 0, "modified_at": ""}),
        ):
            checklist = wake.build_checklist()

        self.assertEqual(checklist["status"], "READY_FOR_APPROVED_WAKE_PROOF_REPORTING_AWAKE")
        self.assertTrue(checklist["no_wake_performed"])
        self.assertFalse(checklist["send_performed"])
        self.assertEqual(checklist["blockers"], [])
        self.assertIn("make inactive", " ".join(checklist["pre_wake_local_steps"]))

    def test_build_checklist_blocks_when_live_runtime_is_awake(self) -> None:
        with (
            mock.patch.object(wake, "active_screen_names", return_value=["fundz-bridge"]),
            mock.patch.object(wake, "active_live_processes", return_value=["123 python3 scripts/fundz_credit_tracker_bridge.py --port 8787"]),
            mock.patch.object(wake, "kill_switch_status", return_value={"enabled": True, "status": "on_blocks_live_replies", "path": "kill.json", "exists": True, "reason": ""}),
            mock.patch.object(wake, "current_gate_state", return_value={
                "credit_tracker_dry_run": True,
                "highlevel_poller_live": False,
                "highlevel_controlled_reply_approved": False,
                "webhook_controlled_reply_approved": False,
                "allow_after_hours_sends": False,
            }),
            mock.patch.object(wake, "file_status", return_value={"path": "proof.jsonl", "exists": False, "bytes": 0, "modified_at": ""}),
        ):
            checklist = wake.build_checklist()

        self.assertEqual(checklist["status"], "BLOCKED_REVIEW_RUNTIME")
        self.assertGreaterEqual(len(checklist["blockers"]), 2)

    def test_build_checklist_blocks_preapproved_live_flags(self) -> None:
        with (
            mock.patch.object(wake, "active_screen_names", return_value=[]),
            mock.patch.object(wake, "active_live_processes", return_value=[]),
            mock.patch.object(wake, "kill_switch_status", return_value={"enabled": False, "status": "off_approval_gates_still_required", "path": "kill.json", "exists": True, "reason": ""}),
            mock.patch.object(wake, "current_gate_state", return_value={
                "credit_tracker_dry_run": False,
                "highlevel_poller_live": True,
                "highlevel_controlled_reply_approved": True,
                "webhook_controlled_reply_approved": False,
                "allow_after_hours_sends": False,
            }),
            mock.patch.object(wake, "file_status", return_value={"path": "proof.jsonl", "exists": False, "bytes": 0, "modified_at": ""}),
        ):
            checklist = wake.build_checklist()

        self.assertEqual(checklist["status"], "BLOCKED_REVIEW_RUNTIME")
        self.assertTrue(any("CREDIT_TRACKER_DRY_RUN" in item for item in checklist["blockers"]))
        self.assertTrue(any("HIGHLEVEL_POLLER_LIVE" in item for item in checklist["blockers"]))
        self.assertTrue(checklist["warnings"])

    def test_write_outputs_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            checklist = {
                "generated_at": "2026-05-13 12:00:00 CDT",
                "status": "READY_FOR_APPROVED_WAKE_PROOF",
                "runtime": {"active_screens": [], "live_screens": [], "allowed_reporting_screens": [], "live_processes": []},
                "kill_switch": {"status": "on_blocks_live_replies"},
                "env_gates": {
                    "credit_tracker_dry_run": True,
                    "highlevel_poller_live": False,
                    "highlevel_controlled_reply_approved": False,
                    "webhook_controlled_reply_approved": False,
                },
                "proof_files": {"reply_receipts": {"path": "receipt.jsonl", "exists": False, "bytes": 0}},
                "blockers": [],
                "warnings": [],
                "approval_packet_required": ["Named client."],
                "pre_wake_local_steps": ["Run checklist."],
                "wake_proof_steps_after_approval": ["Verify health."],
                "not_authorized_by_this_checklist": ["No send."],
            }
            with (
                mock.patch.object(wake, "CHECKLIST_JSON", base / "checklist.json"),
                mock.patch.object(wake, "CHECKLIST_MD", base / "checklist.md"),
            ):
                wake.write_outputs(checklist)

            self.assertEqual(json.loads((base / "checklist.json").read_text(encoding="utf-8"))["status"], "READY_FOR_APPROVED_WAKE_PROOF")
            text = (base / "checklist.md").read_text(encoding="utf-8")
            self.assertIn("FUNDz Runtime Wake Proof Checklist", text)
            self.assertIn("This checklist does not authorize".lower(), text.lower())


if __name__ == "__main__":
    unittest.main()
