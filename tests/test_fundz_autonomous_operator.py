from __future__ import annotations

import csv
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

import fundz_autonomous_operator as operator


class FundzAutonomousOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.autonomy_dir = self.base / "autonomy"
        self.maintenance_dir = self.base / "maintenance"
        self.command_dir = self.base / "command-center"
        self.status_md = self.autonomy_dir / "status.md"
        self.status_json = self.autonomy_dir / "status.json"
        self.run_log = self.autonomy_dir / "operator.jsonl"
        self.events = self.autonomy_dir / "events.jsonl"
        self.maintenance_json = self.maintenance_dir / "maintenance.json"
        self.maintenance_md = self.maintenance_dir / "maintenance.md"
        self.work_queue = self.command_dir / "work-queue.csv"
        self.daily_board = self.command_dir / "daily-board.md"
        self.intake = self.command_dir / "intake.json"
        self.phone = self.command_dir / "phone.json"

        for path in (self.autonomy_dir, self.maintenance_dir, self.command_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.maintenance_md.write_text("# Maintenance\n", encoding="utf-8")
        self.daily_board.write_text(
            "# FUNDz Daily Board\n\nToday: safe local autonomy.\nNext Action: Review queue.\n",
            encoding="utf-8",
        )
        self.maintenance_json.write_text(
            json.dumps(
                {
                    "ok": True,
                    "rollout_packet": {
                        "approval_required": True,
                        "live_send_allowed": False,
                        "selected": 0,
                    },
                    "maintenance_summary": {"duplicate_review_clients": 2},
                }
            ),
            encoding="utf-8",
        )
        with self.work_queue.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["queue_status", "client_name"])
            writer.writeheader()
            writer.writerow({"queue_status": "Blocked", "client_name": "Client A"})
            writer.writerow({"queue_status": "Needs Brandon", "client_name": "Client B"})
        self.intake.write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-08T08:00:00-0500",
                    "candidates": [{"can_auto_create": False, "approval_needed": True}],
                    "alerts": [{}, {}],
                }
            ),
            encoding="utf-8",
        )
        self.phone.write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-08T08:00:00-0500",
                    "intake_rows": [
                        {"classification": "revenue", "approval_needed": True},
                        {"classification": "risk", "approval_needed": False},
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.events.write_text('{"kind":"autonomy_review_completed","proposal_count":0}\n', encoding="utf-8")

        self.patchers = [
            mock.patch.object(operator, "AUTONOMY_DIR", self.autonomy_dir),
            mock.patch.object(operator, "STATUS_MD", self.status_md),
            mock.patch.object(operator, "STATUS_JSON", self.status_json),
            mock.patch.object(operator, "RUN_LOG", self.run_log),
            mock.patch.object(operator, "AUTONOMY_EVENTS_JSONL", self.events),
            mock.patch.object(operator, "MAINTENANCE_STATUS_JSON", self.maintenance_json),
            mock.patch.object(operator, "MAINTENANCE_STATUS_MD", self.maintenance_md),
            mock.patch.object(operator, "WORK_QUEUE_CSV", self.work_queue),
            mock.patch.object(operator, "DAILY_BOARD_MD", self.daily_board),
            mock.patch.object(operator, "INTAKE_GOVERNOR_JSON", self.intake),
            mock.patch.object(operator, "PHONE_APP_INTAKE_JSON", self.phone),
            mock.patch.object(operator, "log_autonomy_event"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_command_for_step_adds_tests_to_maintenance_only(self) -> None:
        command = operator.command_for_step(
            ("scripts/fundz_maintenance_autopilot.py", "--today", "{today}"),
            "2026-05-08",
            run_tests=True,
        )
        self.assertEqual(command[-1], "--run-tests")

        command = operator.command_for_step(("scripts/fundz_command_center.py",), "2026-05-08", run_tests=True)
        self.assertNotIn("--run-tests", command)

    def test_run_pipeline_writes_safe_status(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str], *, timeout: int = 180) -> dict:
            commands.append(command)
            return {"command": command, "ok": True, "returncode": 0, "stdout": "", "stderr": ""}

        with (
            mock.patch.object(operator, "run_command", side_effect=fake_run),
            mock.patch.object(operator, "runtime_check", return_value={"quiet": True, "active_screens": [], "active_processes": []}),
        ):
            status = operator.run_pipeline("2026-05-08", run_tests=True)

        self.assertTrue(status["ok"])
        self.assertEqual(status["successful_steps"], len(operator.PIPELINE_STEPS))
        self.assertEqual(status["work_queue_counts"], {"Blocked": 1, "Needs Brandon": 1})
        self.assertEqual(status["intake_governor"]["approval_needed"], 1)
        self.assertEqual(status["phone_app_intake"]["intake_rows"], 2)
        self.assertTrue(any("--run-tests" in command for command in commands))
        self.assertTrue(self.status_md.exists())
        self.assertIn("safe local autonomy", self.status_md.read_text(encoding="utf-8"))

    def test_runtime_activity_marks_status_unsafe(self) -> None:
        with (
            mock.patch.object(operator, "run_command", return_value={"ok": True, "returncode": 0}),
            mock.patch.object(
                operator,
                "runtime_check",
                return_value={
                    "quiet": False,
                    "active_screens": ["fundz-bridge"],
                    "active_processes": ["123 scripts/fundz_credit_tracker_bridge.py"],
                },
            ),
        ):
            status = operator.run_pipeline("2026-05-08")

        self.assertFalse(status["ok"])
        self.assertTrue(any(finding.startswith("Unsafe:") for finding in status["safety_findings"]))


if __name__ == "__main__":
    unittest.main()
