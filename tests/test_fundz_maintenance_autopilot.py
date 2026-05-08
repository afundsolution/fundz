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

import fundz_maintenance_autopilot as autopilot


class FundzMaintenanceAutopilotTests(unittest.TestCase):
    def test_safety_findings_blocks_live_send_allowed(self) -> None:
        findings = autopilot.safety_findings(
            {"live_send_allowed": True, "approval_required": True, "selected": 0},
            {"billing_unique_clients": 1},
        )

        self.assertTrue(any(finding.startswith("Unsafe:") for finding in findings))

    def test_safety_findings_warns_on_selected_candidate_without_approving_send(self) -> None:
        findings = autopilot.safety_findings(
            {"live_send_allowed": False, "approval_required": True, "selected": 1},
            {"billing_unique_clients": 1},
        )

        self.assertIn("Review only", findings[0])

    def test_run_pipeline_writes_status_when_steps_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            status_md = base / "status.md"
            status_json = base / "status.json"
            autopilot_log = base / "autopilot.jsonl"
            maintenance_summary = base / "summary.json"
            rollout_packet = base / "packet.json"
            daily_board = base / "daily.md"
            maintenance_summary.write_text(
                json.dumps(
                    {
                        "billing_source_rows": 2,
                        "billing_unique_clients": 1,
                        "archived_excluded_clients": 1,
                        "bounced_contact_routes": 0,
                        "duplicate_review_clients": 1,
                        "board": "board.md",
                        "duplicate_csv": "duplicates.csv",
                    }
                ),
                encoding="utf-8",
            )
            rollout_packet.write_text(
                json.dumps(
                    {
                        "selected": 0,
                        "held_before_packet": 2,
                        "approval_required": True,
                        "live_send_allowed": False,
                    }
                ),
                encoding="utf-8",
            )
            daily_board.write_text("# Daily\nNext Action: Clean records.\n", encoding="utf-8")

            def fake_run(command: list[str], *, cwd: Path = autopilot.ROOT) -> dict:
                return {
                    "command": command,
                    "returncode": 0,
                    "duration_seconds": 0.01,
                    "stdout": "",
                    "stderr": "",
                    "ok": True,
                }

            with (
                mock.patch.object(autopilot, "STATUS_MD", status_md),
                mock.patch.object(autopilot, "STATUS_JSON", status_json),
                mock.patch.object(autopilot, "AUTOPILOT_LOG", autopilot_log),
                mock.patch.object(autopilot, "MAINTENANCE_SUMMARY_JSON", maintenance_summary),
                mock.patch.object(autopilot, "ROLLOUT_PACKET_JSON", rollout_packet),
                mock.patch.object(autopilot, "DAILY_BOARD_MD", daily_board),
                mock.patch.object(autopilot, "run_command", side_effect=fake_run),
                mock.patch.object(autopilot, "log_autonomy_event"),
            ):
                status = autopilot.run_pipeline("2026-05-08", run_tests=True)

            self.assertTrue(status["ok"])
            self.assertTrue(status_md.exists())
            self.assertIn("Maintenance Autopilot Status", status_md.read_text(encoding="utf-8"))
            self.assertEqual(status["successful_steps"], len(autopilot.PIPELINE_STEPS) + 1)


if __name__ == "__main__":
    unittest.main()
