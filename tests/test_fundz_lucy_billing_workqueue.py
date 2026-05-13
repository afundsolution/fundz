from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_lucy_billing_workqueue as lucy


class FundzLucyBillingWorkQueueTests(unittest.TestCase):
    def test_build_queue_assigns_duplicate_and_standard_items_to_lucy(self) -> None:
        rows = lucy.build_queue(
            [
                {
                    "client_name": "Niala Agudelo",
                    "decision": "duplicate_review_once",
                    "next_charge_date": "2026-05-11",
                    "failure_types": "Client Card Failure; Low Credits Failure",
                },
                {
                    "client_name": "Kimberly Hailey",
                    "decision": "active_standard_billing_review",
                    "next_charge_date": "2026-05-20",
                    "failure_types": "Client Card Failure",
                },
                {
                    "client_name": "Paid Client",
                    "decision": "owner_reported_paid_active_monitor_only",
                },
            ]
        )

        self.assertEqual([row["client_name"] for row in rows], ["Niala Agudelo", "Kimberly Hailey"])
        self.assertTrue(all(row["owner"] == "Lucy" for row in rows))
        self.assertEqual(rows[0]["priority"], "P1")
        self.assertIn("Review this client once", rows[0]["lucy_action"])

    def test_write_outputs_creates_markdown_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            csv_path = base / "lucy.csv"
            md_path = base / "lucy.md"
            rows = [
                {
                    field: ""
                    for field in lucy.FIELDS
                }
            ]
            rows[0].update({"owner": "Lucy", "client_name": "Ashley Foster", "billing_lane": "duplicate_review_once"})

            lucy.write_outputs(rows, csv_path, md_path, generated_at="2026-05-08T00:00:00")

            with csv_path.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))
            self.assertEqual(written[0]["owner"], "Lucy")
            text = md_path.read_text(encoding="utf-8")
            self.assertIn("A FUND Solution Billing Maintenance Work Queue - Lucy", text)
            self.assertIn("Ashley Foster", text)
            self.assertIn("Batch Update Path", text)
            self.assertIn("fundz-owner-billing-status-updates.csv", text)


if __name__ == "__main__":
    unittest.main()
