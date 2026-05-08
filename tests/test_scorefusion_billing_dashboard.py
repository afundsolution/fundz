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

import scorefusion_billing_dashboard as sf


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class ScoreFusionBillingDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source_dir = Path(self.temp_dir.name) / "dispute-fox"
        write_csv(
            self.source_dir / "disputefox-active-clients-full-20260502.csv",
            [
                {
                    "source": "disputefox_active_clients_full",
                    "client_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "status": "In Dispute",
                    "messages": "None",
                    "billing": "",
                    "next_import": "29 Days",
                    "started": "01/31/2026",
                    "assigned_to": "Brandon Jordan",
                    "stage_in_process": "Round 1 Sent (05/01/26)",
                    "onboarding": "100%",
                    "action": "Email",
                },
                {
                    "source": "disputefox_active_clients_full",
                    "client_name": "Ben Franklin",
                    "email": "ben@example.com",
                    "status": "",
                    "messages": "None",
                    "billing": "",
                    "next_import": "",
                    "started": "05/06/2026",
                    "assigned_to": "Brandon Jordan",
                    "stage_in_process": "Customer Details",
                    "onboarding": "25%",
                    "action": "Email",
                },
            ],
        )
        write_csv(
            self.source_dir / "disputefox-invoice-due-20260502.csv",
            [
                {
                    "client_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "amount_due": "$79.00",
                    "billing_status": "Past Due",
                },
                {
                    "client_name": "Ben Franklin",
                    "email": "",
                    "amount_due": "40",
                    "billing_status": "Future Billing",
                },
                {
                    "client_name": "Unmatched Client",
                    "email": "missing@example.com",
                    "amount_due": "$20.00",
                    "billing_status": "Past Due",
                },
            ],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_month_end_charge_uses_last_valid_day(self) -> None:
        self.assertEqual(sf.next_monthly_charge(date(2026, 1, 31), date(2026, 2, 1)), date(2026, 2, 28))
        self.assertEqual(sf.next_monthly_charge(date(2026, 1, 31), date(2026, 3, 1)), date(2026, 3, 31))

    def test_builds_dashboard_from_active_and_billing_exports(self) -> None:
        dashboard = sf.build_dashboard(self.source_dir, today=date(2026, 5, 3))
        metrics = {row["metric"]: row["value"] for row in dashboard["dashboard"]}
        roster = {row["client_name"]: row for row in dashboard["roster"]}

        self.assertEqual(metrics["ScoreFusion Enrolled"], 2)
        self.assertEqual(metrics["Warnings Due"], 1)
        self.assertEqual(metrics["Owed Payments"], 2)
        self.assertEqual(metrics["Total Amount Due"], "119.00")
        self.assertEqual(metrics["Failed / At Risk"], 2)
        self.assertEqual(roster["Ada Lovelace"]["amount_due"], "79.00")
        self.assertEqual(roster["Ada Lovelace"]["next_charge_date"], "2026-05-31")
        self.assertEqual(roster["Ben Franklin"]["amount_due"], "40.00")
        self.assertEqual(roster["Ben Franklin"]["next_charge_date"], "2026-05-06")
        self.assertEqual(dashboard["billing_risk_summary"]["queue_count"], 2)
        self.assertEqual(dashboard["billing_risk_summary"]["counts"]["high"], 1)
        self.assertEqual(dashboard["billing_risk_queue"][0]["client_name"], "Ada Lovelace")
        self.assertEqual(len(dashboard["billing_risk_review_queue"]), 2)
        self.assertEqual(metrics["Billing Risk Review Rows"], 2)
        self.assertEqual(metrics["Billing Risk Unique Keys"], 2)
        self.assertEqual(metrics["Billing Risk Duplicate Keys"], 0)

    def test_flags_unmatched_billing_rows(self) -> None:
        dashboard = sf.build_dashboard(self.source_dir, today=date(2026, 5, 3))
        exception_types = [row["exception_type"] for row in dashboard["exceptions"]]

        self.assertIn("disputefox_client_missing_from_highlevel", exception_types)

    def test_billing_risk_summary_tracks_duplicate_keys(self) -> None:
        queue = [
            {"risk_level": "high", "email": "ada@example.com", "client_name": "Ada", "amount_due": "27.99"},
            {"risk_level": "high", "email": "ada@example.com", "client_name": "Ada", "amount_due": "27.99"},
            {"risk_level": "medium", "email": "", "client_name": "Ben Franklin", "amount_due": "10.00"},
        ]

        summary = sf.billing_risk_summary(queue)

        self.assertEqual(summary["unique_keys"], 2)
        self.assertEqual(summary["duplicate_keys"], 1)
        self.assertEqual(summary["rows_in_duplicate_keys"], 2)

    def test_billing_risk_review_queue_collapses_duplicate_keys(self) -> None:
        queue = [
            {
                "risk_level": "high",
                "email": "ada@example.com",
                "client_name": "Ada Lovelace",
                "amount_due": "27.99",
                "billing_status": "Client Card Failure: Failed 5/1 due Today",
                "pipeline_stage": "At Risk",
                "next_charge_date": "2026-05-07",
            },
            {
                "risk_level": "high",
                "email": "ada@example.com",
                "client_name": "Ada Lovelace",
                "amount_due": "27.99",
                "billing_status": "Low Credits Failure: Failed 5/1 due Today",
                "pipeline_stage": "At Risk",
                "next_charge_date": "2026-05-07",
            },
        ]

        review = sf.build_billing_risk_review_queue(queue, today=date(2026, 5, 3))

        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["row_count"], 2)
        self.assertEqual(review[0]["duplicate_row_count"], 1)
        self.assertIn("Client Card Failure", review[0]["failure_types"])
        self.assertIn("Low Credits Failure", review[0]["failure_types"])
        self.assertEqual(review[0]["review_bucket"], "dual_failure_review")
        self.assertIn("do not double-contact", review[0]["rollout_treatment"])

    def test_live_summary_overrides_dashboard_totals(self) -> None:
        live_summary = {
            "source": "DisputeFox ScoreFusion dashboard 2026-05-03",
            "active_clients": 234,
            "failed_payment_count": 246,
            "failed_invoices_total": "$15,256.55",
            "client_card_failures": 150,
            "low_credit_failures": 96,
            "credits_available": "$8.00",
        }
        dashboard = sf.build_dashboard(Path(self.temp_dir.name) / "empty", today=date(2026, 5, 3), live_summary=live_summary)
        metrics = {row["metric"]: row["value"] for row in dashboard["dashboard"]}
        exception_types = [row["exception_type"] for row in dashboard["exceptions"]]

        self.assertEqual(metrics["ScoreFusion Enrolled"], 234)
        self.assertEqual(metrics["Owed Payments"], 246)
        self.assertEqual(metrics["Total Amount Due"], "15256.55")
        self.assertEqual(metrics["Failed / At Risk"], 246)
        self.assertEqual(metrics["Client Card Failures"], 150)
        self.assertEqual(metrics["Low Credit Failures"], 96)
        self.assertIn("client_level_billing_export_needed", exception_types)

    def test_parses_raw_failed_payment_pages(self) -> None:
        raw_dir = Path(self.temp_dir.name) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "client-card-page-1.txt").write_text(
            "Header text\nbutton above\n"
            "Ada Lovelaceada@example.comActiveClient\n"
            "Failed 5/1\n"
            "May 11\n"
            "$27.99$27.99$5.60MessageEmail\n",
            encoding="utf-8",
        )
        (raw_dir / "low-credits-page-1.txt").write_text(
            "Ben Franklinben@example.comArchivedClient\n"
            "Failed 4/30\n"
            "N/A\n"
            "$40.00$0.00$0.00MessageEmail\n",
            encoding="utf-8",
        )

        rows = sf.parse_failed_payment_pages(raw_dir)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["client_name"], "Ada Lovelace")
        self.assertEqual(rows[0]["email"], "ada@example.com")
        self.assertEqual(rows[0]["amount_due"], "27.99")
        self.assertEqual(rows[0]["source_failure_bucket"], "Client Card Failure")
        self.assertEqual(rows[1]["status"], "Archived")
        self.assertEqual(rows[1]["amount_due"], "40.00")
        self.assertEqual(rows[1]["total_paid"], "0.00")
        self.assertEqual(rows[1]["source_failure_bucket"], "Low Credits Failure")

    def test_writes_drive_ready_outputs(self) -> None:
        dashboard = sf.build_dashboard(self.source_dir, today=date(2026, 5, 3))
        output_dir = Path(self.temp_dir.name) / "out"
        files = sf.write_outputs(output_dir, dashboard)

        for path in files.values():
            self.assertTrue(Path(path).exists())
        self.assertIn("client-billing-roster.csv", files["roster"])
        self.assertIn("billing-risk-queue.csv", files["billing_risk_queue"])
        self.assertIn("billing-risk-review-packet.md", files["billing_risk_review_packet"])
        packet = Path(files["billing_risk_review_packet"]).read_text(encoding="utf-8")
        self.assertIn("ScoreFusion Billing Risk Review Packet", packet)
        self.assertIn("Unique review rows", packet)
        self.assertIn("Business Review Buckets", packet)
        self.assertIn("Controlled Rollout Decision", packet)


if __name__ == "__main__":
    unittest.main()
