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

import fundz_phone_app_intake as phone_intake


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class FundzPhoneAppIntakeTests(unittest.TestCase):
    def test_classifies_money_and_risk_as_high_priority(self) -> None:
        result = phone_intake.classify_text("Client wants a refund and says the card payment was wrong.", inbound=True)

        self.assertEqual(result["category"], "Risk / Retention")
        self.assertEqual(result["status"], "Needs Brandon")
        self.assertEqual(result["approval_needed"], "yes")
        self.assertEqual(result["revenue_signal"], "risk")
        self.assertGreaterEqual(result["priority"], 90)

    def test_security_text_stays_private(self) -> None:
        result = phone_intake.classify_text("Your verification code is 123456.", inbound=True)

        self.assertEqual(result["category"], "Security / Keep Private")
        self.assertEqual(result["status"], "No Company Action")
        self.assertEqual(result["shared_safe"], "no")

    def test_build_phone_app_intake_from_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            phone_queue = base / "phone.csv"
            governor_candidates = base / "candidates.csv"
            import_dir = base / "imports"
            import_dir.mkdir()
            (import_dir / "call-note.txt").write_text("New lead wants a consultation and asked about cost.", encoding="utf-8")

            write_csv(
                phone_queue,
                ["contact", "phone", "last_message", "date", "direction", "owner"],
                [
                    {
                        "contact": "Ada",
                        "phone": "+1555",
                        "last_message": "Can I pay my invoice today?",
                        "date": "2026-05-06T09:00:00-05:00",
                        "direction": "inbound",
                        "owner": "Brandon",
                    }
                ],
            )
            write_csv(
                governor_candidates,
                ["source", "contact", "phone", "queue_status", "owner", "next_step", "proof_required", "approval_needed", "shared_safe", "reason", "evidence"],
                [
                    {
                        "source": "personal_phone_triage",
                        "contact": "Travis Vance",
                        "phone": "+1504",
                        "queue_status": "Needs Brandon",
                        "owner": "Brandon",
                        "next_step": "Review.",
                        "proof_required": "Approval.",
                        "approval_needed": "yes",
                        "shared_safe": "no",
                        "reason": "Sensitive.",
                        "evidence": "triage.md",
                    }
                ],
            )

            with (
                mock.patch.object(phone_intake, "PERSONAL_PHONE_QUEUE_CSV", phone_queue),
                mock.patch.object(phone_intake, "INTAKE_GOVERNOR_CANDIDATES_CSV", governor_candidates),
                mock.patch.object(phone_intake, "IMPORT_DIR", import_dir),
            ):
                report = phone_intake.build_phone_app_intake()

        self.assertEqual(report["summary"]["rows"], 3)
        self.assertEqual(report["summary"]["source_app"]["Messages"], 1)
        self.assertEqual(report["summary"]["source_app"]["Intake Governor"], 1)
        self.assertEqual(report["summary"]["source_app"]["Manual Phone App Export"], 1)
        self.assertGreaterEqual(report["summary"]["revenue_signal"].get("yes", 0), 2)

    def test_unknown_keyword_only_message_stays_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            phone_queue = Path(tmp) / "phone.csv"
            write_csv(
                phone_queue,
                ["contact", "phone", "last_message", "date", "direction", "owner", "status", "source"],
                [
                    {
                        "contact": "Unknown business keyword match",
                        "phone": "+1555",
                        "last_message": "Can you check my credit report?",
                        "date": "2026-05-06T09:00:00-05:00",
                        "direction": "inbound",
                        "owner": "Brandon",
                        "status": "Review",
                        "source": "Mac Messages chat.db | keyword:credit;keyword:report",
                    }
                ],
            )

            rows = phone_intake.intake_from_personal_phone(phone_queue)

        self.assertEqual(rows[0]["status"], "Review")
        self.assertEqual(rows[0]["approval_needed"], "yes")
        self.assertIn("Verify this is a FUNDz client", rows[0]["next_step"])

    def test_owner_command_message_stays_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            phone_queue = Path(tmp) / "phone.csv"
            write_csv(
                phone_queue,
                ["contact", "phone", "last_message", "date", "direction", "owner", "status", "source"],
                [
                    {
                        "contact": "Brandon Jordan",
                        "phone": "+13466429919",
                        "last_message": "FUNDz status",
                        "date": "2026-05-12T12:00:00-05:00",
                        "direction": "inbound",
                        "owner": "Brandon",
                        "status": "Owner Review",
                        "source": "Mac Messages chat.db | client_phone;owner_command_source",
                    }
                ],
            )

            rows = phone_intake.intake_from_personal_phone(phone_queue)

        self.assertEqual(rows[0]["category"], "Owner Command / Private")
        self.assertEqual(rows[0]["status"], "Owner Review")
        self.assertEqual(rows[0]["shared_safe"], "no")
        self.assertEqual(rows[0]["sanitized_summary"], "Owner-number message kept private.")

    def test_write_outputs(self) -> None:
        report = {
            "generated_at": "2026-05-06T10:00:00-05:00",
            "mission": "Test mission.",
            "summary": {
                "rows": 1,
                "category": {"Money / Billing": 1},
                "source_app": {"Messages": 1},
                "revenue_signal": {"yes": 1},
                "status": {"Needs Brandon": 1},
                "approval_needed": {"yes": 1},
                "shared_safe": {"sanitized_only": 1},
                "top_priority": [
                    {
                        "intake_id": "PHONE-MSG-001",
                        "source_app": "Messages",
                        "category": "Money / Billing",
                        "status": "Needs Brandon",
                        "priority": 90,
                        "contact": "Ada",
                        "handle": "+1555",
                        "next_step": "Review.",
                    }
                ],
            },
            "rows": [
                {
                    "intake_id": "PHONE-MSG-001",
                    "source_app": "Messages",
                    "source_type": "business-filtered",
                    "contact": "Ada",
                    "handle": "+1555",
                    "date": "",
                    "category": "Money / Billing",
                    "revenue_signal": "yes",
                    "priority": 90,
                    "owner": "Brandon",
                    "status": "Needs Brandon",
                    "next_step": "Review.",
                    "proof_required": "Proof.",
                    "approval_needed": "yes",
                    "shared_safe": "sanitized_only",
                    "sanitized_summary": "Can I pay?",
                    "evidence": "phone.csv",
                }
            ],
            "existing_member_redirect": {
                "sop": "assistant/personal-phone-redirect-sop.md",
                "default_copy": phone_intake.EXISTING_MEMBER_REDIRECT_COPY,
                "app_access_help_copy": phone_intake.APP_ACCESS_HELP_COPY,
                "rule": "Existing members who text Brandon's personal line should be redirected to the Credit Tracker app through an approved company channel. Do not auto-reply from the personal line.",
            },
            "registry": phone_intake.APP_REGISTRY,
            "import_folder": "/tmp/imports",
            "rules": ["No whole phone."],
        }

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                mock.patch.object(phone_intake, "PHONE_APP_INTAKE_JSON", base / "intake.json"),
                mock.patch.object(phone_intake, "PHONE_APP_INTAKE_CSV", base / "intake.csv"),
                mock.patch.object(phone_intake, "PHONE_APP_INTAKE_MD", base / "intake.md"),
                mock.patch.object(phone_intake, "PHONE_APP_REGISTRY_MD", base / "registry.md"),
                mock.patch.object(phone_intake, "PHONE_APP_DASHBOARD_HTML", base / "dashboard.html"),
            ):
                paths = phone_intake.write_outputs(report)

            self.assertTrue(paths["json"].exists())
            self.assertTrue(paths["csv"].exists())
            self.assertTrue(paths["markdown"].exists())
            self.assertTrue(paths["registry"].exists())
            self.assertTrue(paths["dashboard"].exists())
            self.assertEqual(json.loads(paths["json"].read_text(encoding="utf-8"))["summary"]["rows"], 1)
            self.assertIn("FUNDz Phone App Intake", paths["dashboard"].read_text(encoding="utf-8"))
            self.assertIn("Existing Member Redirect", paths["markdown"].read_text(encoding="utf-8"))
            self.assertIn("Credit Tracker app", paths["dashboard"].read_text(encoding="utf-8"))

    def test_build_report_includes_existing_member_redirect_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            phone_queue = base / "phone.csv"
            governor_candidates = base / "candidates.csv"
            import_dir = base / "imports"
            import_dir.mkdir()
            write_csv(phone_queue, ["contact", "phone", "last_message", "date", "direction", "owner"], [])
            write_csv(
                governor_candidates,
                ["source", "contact", "phone", "queue_status", "owner", "next_step", "proof_required", "approval_needed", "shared_safe", "reason", "evidence"],
                [],
            )

            with (
                mock.patch.object(phone_intake, "PERSONAL_PHONE_QUEUE_CSV", phone_queue),
                mock.patch.object(phone_intake, "INTAKE_GOVERNOR_CANDIDATES_CSV", governor_candidates),
                mock.patch.object(phone_intake, "IMPORT_DIR", import_dir),
            ):
                report = phone_intake.build_phone_app_intake()

        redirect = report["existing_member_redirect"]
        self.assertIn("Credit Tracker app", redirect["default_copy"])
        self.assertIn("approved company channel", redirect["rule"])


if __name__ == "__main__":
    unittest.main()
