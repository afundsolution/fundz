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

import fundz_intake_governor as intake


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class FundzIntakeGovernorTests(unittest.TestCase):
    def test_personal_phone_candidate_requires_approval(self) -> None:
        triage = [
            {
                "triage_id": "PPM-NEEDS-REPLY-001",
                "contact": "Unknown business keyword match",
                "phone": "+15550001111",
                "classification": "possible non-client/personal false positive",
                "move_to_work_queue": "no",
                "needs_brandon_decision": "no",
                "sanitized_summary": "Vendor notice.",
                "recommended_action": "Ignore.",
            },
            {
                "triage_id": "PPM-NEEDS-REPLY-004",
                "contact": "Travis Vance",
                "phone": "+15042151873",
                "classification": "needs Brandon decision",
                "move_to_work_queue": "hold for approval",
                "needs_brandon_decision": "yes",
                "sanitized_summary": "Known historical client phone match with sensitive-looking content.",
                "recommended_action": "Brandon should decide.",
            },
        ]
        candidates = [
            {
                "work_order_id": "FUNDZ-PERSONAL-PHONE-TRAVIS-VANCE-20260315",
                "queue_status": "Needs Brandon",
                "client_name": "Travis Vance",
                "owner": "Brandon",
                "next_step": "Verify status in DF/HighLevel before any reply.",
                "proof_required": "DF/HighLevel current-status proof or no-action decision.",
                "evidence": "data/local/command-center/fundz-personal-phone-needs-reply-triage.md#PPM-NEEDS-REPLY-004",
                "flags": "personal_phone_intake;sensitive_content",
            }
        ]

        queue_rows, alerts = intake.build_phone_candidates(triage, candidates)

        self.assertEqual(len(queue_rows), 1)
        self.assertEqual(queue_rows[0]["contact"], "Travis Vance")
        self.assertEqual(queue_rows[0]["approval_needed"], "yes")
        self.assertEqual(queue_rows[0]["can_auto_create"], "no")
        self.assertEqual(queue_rows[0]["shared_safe"], "no")
        self.assertEqual(len(alerts), 1)

    def test_build_intake_governor_counts_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            work_queue = base / "work.csv"
            alerts = base / "alerts.csv"
            triage = base / "triage.csv"
            phone_candidates = base / "phone_candidates.csv"
            communication = base / "communication.csv"

            write_rows(
                work_queue,
                ["queue_status", "client_name", "owner", "next_step", "evidence"],
                [
                    {"queue_status": "Blocked", "client_name": "Ada", "owner": "Governor", "next_step": "", "evidence": ""},
                    {"queue_status": "Failed", "client_name": "Ben", "owner": "FUNDz", "next_step": "", "evidence": ""},
                    {"queue_status": "Done", "client_name": "Cy", "owner": "FUNDz", "next_step": "", "evidence": ""},
                ],
            )
            write_rows(
                alerts,
                ["reason", "queue_status", "client_name", "owner", "evidence", "next_step"],
                [{"reason": "Missing proof", "queue_status": "Proof Needed", "client_name": "Ada", "owner": "Governor", "evidence": "proof.csv", "next_step": "Attach proof."}],
            )
            write_rows(
                triage,
                ["triage_id", "contact", "phone", "classification", "move_to_work_queue", "needs_brandon_decision", "sanitized_summary", "recommended_action"],
                [{"triage_id": "PPM-1", "contact": "Ada", "phone": "+1555", "classification": "needs Brandon decision", "move_to_work_queue": "hold for approval", "needs_brandon_decision": "yes", "sanitized_summary": "Sensitive.", "recommended_action": "Review."}],
            )
            write_rows(
                phone_candidates,
                ["client_name", "queue_status", "owner", "next_step", "proof_required", "evidence", "flags"],
                [{"client_name": "Ada", "queue_status": "Needs Brandon", "owner": "Brandon", "next_step": "Review.", "proof_required": "Approval.", "evidence": "PPM-1", "flags": "personal_phone_intake"}],
            )
            write_rows(
                communication,
                ["communication_status", "message_lane", "mobile_app_sms_allowed"],
                [{"communication_status": "Blocked", "message_lane": "Round Updates", "mobile_app_sms_allowed": "no"}],
            )

            report = intake.build_intake_governor(
                work_queue_csv=work_queue,
                governor_alerts_csv=alerts,
                phone_triage_csv=triage,
                phone_candidates_csv=phone_candidates,
                communication_board_csv=communication,
            )

        self.assertEqual(report["summary"]["work_queue_rows"], 3)
        self.assertEqual(report["summary"]["blocking_work_queue_rows"], 2)
        self.assertEqual(report["summary"]["phone_candidates"], 1)
        self.assertEqual(report["summary"]["needs_brandon_approval"], 1)
        self.assertGreaterEqual(report["summary"]["alerts"], 3)
        self.assertEqual(report["communication_board"]["rows"], 1)

    def test_write_outputs(self) -> None:
        report = {
            "generated_at": "2026-05-06T10:00:00-05:00",
            "bot": {"mission": "Test mission."},
            "summary": {
                "work_queue_rows": 1,
                "blocking_work_queue_rows": 1,
                "phone_triage_rows": 1,
                "phone_candidates": 1,
                "safe_to_auto_create": 0,
                "needs_brandon_approval": 1,
                "alerts": 1,
            },
            "candidates": [
                {
                    "intake_id": "PPM-1",
                    "source": "personal_phone_triage",
                    "contact": "Ada",
                    "phone": "+1555",
                    "queue_status": "Needs Brandon",
                    "owner": "Brandon",
                    "classification": "needs Brandon decision",
                    "next_step": "Review.",
                    "proof_required": "Approval.",
                    "approval_needed": "yes",
                    "can_auto_create": "no",
                    "shared_safe": "no",
                    "reason": "Sensitive.",
                    "evidence": "triage.md",
                }
            ],
            "alerts": [
                {
                    "alert_id": "A1",
                    "severity": "decision",
                    "source": "personal_phone_triage",
                    "contact": "Ada",
                    "reason": "Review.",
                    "owner": "Brandon",
                    "next_step": "Approve.",
                    "evidence": "triage.md",
                }
            ],
            "rules": ["No sends."],
        }

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                mock.patch.object(intake, "INTAKE_GOVERNOR_MD", base / "intake.md"),
                mock.patch.object(intake, "INTAKE_GOVERNOR_JSON", base / "intake.json"),
                mock.patch.object(intake, "INTAKE_CANDIDATES_CSV", base / "candidates.csv"),
                mock.patch.object(intake, "INTAKE_ALERTS_CSV", base / "alerts.csv"),
            ):
                paths = intake.write_outputs(report)

            self.assertTrue(paths["markdown"].exists())
            self.assertTrue(paths["json"].exists())
            self.assertTrue(paths["candidates"].exists())
            self.assertTrue(paths["alerts"].exists())
            self.assertIn("Do not move intake", paths["markdown"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
