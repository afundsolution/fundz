from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_date_sensitive_billing_review as review


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class FundzDateSensitiveBillingReviewTests(unittest.TestCase):
    def test_builds_payment_and_low_credit_clearance_rows(self) -> None:
        rows = review.build_review_rows(
            [
                {
                    "client_name": "Arthur Pedraza",
                    "decision": "active_date_sensitive_billing_review",
                    "failure_types": "Client Card Failure",
                    "next_charge_date": "2026-05-09",
                    "amount_due": "27.99",
                    "system_next_import": "-15 Days",
                },
                {
                    "client_name": "Felicia Williams",
                    "decision": "active_date_sensitive_billing_review",
                    "failure_types": "Low Credits Failure",
                    "next_charge_date": "2026-05-11",
                    "amount_due": "0.00",
                    "system_next_import": "20 Days",
                },
                {
                    "client_name": "Standard Client",
                    "decision": "active_standard_billing_review",
                    "failure_types": "Client Card Failure",
                },
            ],
            [
                {
                    "client_name": "Arthur Pedraza",
                    "billing_statuses": "Client Card Failure: Failed 5/1 due May 09",
                },
                {
                    "client_name": "Felicia Williams",
                    "billing_statuses": "Low Credits Failure: N/A due N/A",
                },
            ],
            [],
            date(2026, 5, 8),
        )

        self.assertEqual([row["client_name"] for row in rows], ["Arthur Pedraza", "Felicia Williams"])
        self.assertEqual(rows[0]["review_status"], "reviewed_payment_method_hold")
        self.assertEqual(rows[0]["owner_priority"], "P1")
        self.assertEqual(rows[1]["review_status"], "reviewed_scorefusion_credit_hold")
        self.assertIn("Amount due is 0.00", rows[1]["required_action"])
        self.assertEqual(rows[1]["client_contact_allowed_now"], "no")

    def test_writes_clearance_packet_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            csv_path = base / "clearance.csv"
            md_path = base / "clearance.md"
            rows = [
                {
                    "client_name": "Corrissa Weaver",
                    "review_status": "reviewed_payment_method_hold",
                    "clearance_status": "not_cleared_live_payment_proof_required",
                    "failure_type": "Client Card Failure",
                    "next_charge_date": "2026-05-10",
                    "days_until_charge": "2",
                    "amount_due": "27.99",
                    "billing_status": "Client Card Failure",
                    "system_status": "In Dispute",
                    "system_stage_in_process": "Round 1 Sent",
                    "system_next_import": "21 Days",
                    "system_next_import_days": "21",
                    "owner_priority": "P1",
                    "client_contact_allowed_now": "no",
                    "live_edit_allowed_now": "no",
                    "required_action": "Check live billing.",
                    "proof_needed_to_clear": "Fresh proof.",
                    "evidence": "local evidence",
                }
            ]

            outputs = review.write_outputs(
                rows,
                date(2026, 5, 8),
                csv_path=csv_path,
                md_path=md_path,
                generated_at="2026-05-08T00:00:00",
            )

            self.assertEqual(outputs["csv"], str(csv_path))
            self.assertTrue(csv_path.exists())
            text = md_path.read_text(encoding="utf-8")
            self.assertIn("Date-sensitive active billing reviews checked: 1", text)
            self.assertIn("Client contact allowed now: 0", text)
            self.assertIn("Corrissa Weaver", text)


if __name__ == "__main__":
    unittest.main()
