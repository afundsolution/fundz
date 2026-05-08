from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_intake_governor_visual as visual


class FundzIntakeGovernorVisualTests(unittest.TestCase):
    def sample_report(self) -> dict:
        return {
            "generated_at": "2026-05-06T10:00:00-05:00",
            "bot": {"mission": "Convert hidden intake into decision-ready queue candidates."},
            "summary": {
                "work_queue_rows": 10,
                "blocking_work_queue_rows": 7,
                "phone_triage_rows": 4,
                "phone_candidates": 1,
                "safe_to_auto_create": 0,
                "needs_brandon_approval": 1,
                "alerts": 3,
            },
            "status_counts": {"Blocked": 7, "Needs Brandon": 1, "Done": 2},
            "communication_board": {
                "rows": 10,
                "mobile_app_sms_allowed": {"yes": 1, "no": 9},
            },
            "candidates": [
                {
                    "intake_id": "PPM-1",
                    "contact": "Travis Vance",
                    "queue_status": "Needs Brandon",
                    "owner": "Brandon",
                    "approval_needed": "yes",
                    "shared_safe": "no",
                    "next_step": "Review.",
                }
            ],
            "alerts": [
                {
                    "severity": "decision",
                    "source": "personal_phone_triage",
                    "contact": "Travis Vance",
                    "owner": "Brandon",
                    "reason": "Approval needed.",
                    "next_step": "Approve or reject.",
                }
            ],
            "rules": ["No sends.", "No shared personal message bodies."],
        }

    def test_render_dashboard_contains_core_sections(self) -> None:
        rendered = visual.render_dashboard(self.sample_report())

        self.assertIn("FUNDz Intake Governor", rendered)
        self.assertIn("Personal Phone", rendered)
        self.assertIn("Safety Gate", rendered)
        self.assertIn("Travis Vance", rendered)
        self.assertIn("Compressed Alerts", rendered)

    def test_write_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report_path = base / "report.json"
            output_path = base / "dashboard.html"
            report_path.write_text(json.dumps(self.sample_report()), encoding="utf-8")

            written = visual.write_dashboard(report_path, output_path)

            self.assertEqual(written, output_path)
            self.assertTrue(output_path.exists())
            self.assertIn("<!doctype html>", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
