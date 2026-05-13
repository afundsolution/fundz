from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_maintenance_cleanup_board as board


class FundzMaintenanceCleanupBoardTests(unittest.TestCase):
    def test_build_board_classifies_five_cleanup_goals(self) -> None:
        billing_rows = [
            {
                "risk_level": "high",
                "review_bucket": "urgent_due_now_or_past_due",
                "client_name": "Bianca Alexander",
                "email": "bianca@example.com",
                "amount_due": "27.99",
                "row_count": "1",
                "duplicate_row_count": "0",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-08",
            },
            {
                "risk_level": "high",
                "review_bucket": "dual_failure_review",
                "client_name": "Lisa Sennett",
                "email": "lisa@example.com",
                "amount_due": "27.99",
                "row_count": "2",
                "duplicate_row_count": "1",
                "failure_types": "Client Card Failure; Low Credits Failure",
                "next_charge_date": "2026-05-29",
            },
        ]
        archive_rows = [
            {
                "client_name": "Bianca Alexander",
                "archive_decision": "archived_live_confirmed",
            }
        ]
        live_hold_rows = [
            {
                "client_name": "Darryl Hatcher",
                "blocker_type": "bounce_or_email_failure",
                "cleanup_decision": "exclude_bounced_email_route",
            }
        ]

        result = board.build_board(billing_rows, archive_rows, live_hold_rows)
        summary = result["summary"]

        self.assertEqual(len(result["goal_rows"]), 5)
        self.assertEqual(summary["billing_unique_clients"], 2)
        self.assertEqual(summary["archived_billing_rows"], 1)
        self.assertEqual(summary["bounced_contact_routes"], 1)
        self.assertEqual(summary["duplicate_review_clients"], 1)
        decisions = {row["client_name"]: row["decision"] for row in result["billing_actions"]}
        self.assertEqual(decisions["Bianca Alexander"], "archived_monitor_only")
        self.assertEqual(decisions["Lisa Sennett"], "duplicate_review_once")

    def test_build_board_filters_billing_issue_side_by_active_next_import(self) -> None:
        billing_rows = [
            {
                "risk_level": "high",
                "review_bucket": "urgent_due_now_or_past_due",
                "client_name": "Active Client",
                "email": "active@example.com",
                "amount_due": "27.99",
                "row_count": "1",
                "duplicate_row_count": "0",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-08",
            },
            {
                "risk_level": "high",
                "review_bucket": "urgent_due_now_or_past_due",
                "client_name": "Stale Client",
                "email": "stale@example.com",
                "amount_due": "27.99",
                "row_count": "1",
                "duplicate_row_count": "0",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-08",
            },
            {
                "risk_level": "high",
                "review_bucket": "standard_high_risk_review",
                "client_name": "Missing Import Client",
                "email": "missing@example.com",
                "amount_due": "27.99",
                "row_count": "1",
                "duplicate_row_count": "0",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-20",
            },
            {
                "risk_level": "high",
                "review_bucket": "standard_high_risk_review",
                "client_name": "Not Found Client",
                "email": "missing-system@example.com",
                "amount_due": "27.99",
                "row_count": "1",
                "duplicate_row_count": "0",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-20",
            },
        ]
        active_rows = [
            {"client_name": "Active Client", "email": "active@example.com", "status": "In Dispute", "next_import": "-10 Days"},
            {"client_name": "Stale Client", "email": "stale@example.com", "status": "In Dispute", "next_import": "-30 Days"},
            {"client_name": "Missing Import Client", "email": "missing@example.com", "status": "In Dispute", "next_import": ""},
        ]

        result = board.build_board(billing_rows, [], [], active_rows, Path("active.csv"))
        decisions = {row["client_name"]: row["decision"] for row in result["billing_actions"]}

        self.assertEqual(result["summary"]["active_billing_issue_clients"], 1)
        self.assertEqual(result["summary"]["non_active_billing_clients"], 3)
        self.assertEqual(result["summary"]["stale_next_import_billing_clients"], 1)
        self.assertEqual(result["summary"]["not_in_active_system_billing_clients"], 1)
        self.assertEqual(result["summary"]["active_system_missing_next_import_clients"], 1)
        self.assertEqual(decisions["Active Client"], "active_urgent_billing_review")
        self.assertEqual(decisions["Stale Client"], "stale_next_import_monitor_only")
        self.assertEqual(decisions["Missing Import Client"], "active_system_missing_next_import_review")
        self.assertEqual(decisions["Not Found Client"], "not_in_active_system_monitor_only")

    def test_owner_billing_updates_remove_rows_from_issue_side(self) -> None:
        billing_rows = [
            {
                "risk_level": "high",
                "review_bucket": "date_sensitive_next_7_days",
                "client_name": "Corrissa Weaver",
                "email": "corrissa@example.com",
                "amount_due": "27.99",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-10",
            },
            {
                "risk_level": "high",
                "review_bucket": "date_sensitive_next_7_days",
                "client_name": "Don Dupre",
                "email": "don@example.com",
                "amount_due": "27.99",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-15",
            },
            {
                "risk_level": "medium",
                "review_bucket": "date_sensitive_next_7_days",
                "client_name": "Sakia Riley",
                "email": "sakia@example.com",
                "amount_due": "27.99",
                "failure_types": "Low Credits Failure",
                "next_charge_date": "2026-05-11",
            },
        ]
        active_rows = [
            {"client_name": "Corrissa Weaver", "email": "corrissa@example.com", "status": "In Dispute", "next_import": "21 Days"},
            {"client_name": "Don Dupre", "email": "don@example.com", "status": "Due For Next Round", "next_import": "-9 Days"},
            {"client_name": "Sakia Riley", "email": "sakia@example.com", "status": "Due For Next Round", "next_import": "19 Days"},
        ]
        owner_updates = [
            {
                "client_name": "Corrissa Weaver",
                "owner_update_status": "paid",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "Owner reported paid.",
            },
            {
                "client_name": "Don Dupre",
                "owner_update_status": "df_error_pending_fix",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "Owner emailed DF.",
            },
            {
                "client_name": "Sakia Riley",
                "owner_update_status": "paid_active",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "Owner reported paid and active.",
            },
        ]

        result = board.build_board(billing_rows, [], [], active_rows, Path("active.csv"), owner_updates)
        decisions = {row["client_name"]: row["decision"] for row in result["billing_actions"]}

        self.assertEqual(result["summary"]["active_billing_issue_clients"], 0)
        self.assertEqual(result["summary"]["non_active_billing_clients"], 3)
        self.assertEqual(result["summary"]["owner_updated_billing_clients"], 3)
        self.assertEqual(decisions["Corrissa Weaver"], "owner_reported_paid_monitor_only")
        self.assertEqual(decisions["Don Dupre"], "df_error_pending_fix_monitor_only")
        self.assertEqual(decisions["Sakia Riley"], "owner_reported_paid_active_monitor_only")

    def test_lucy_owner_status_options_are_supported(self) -> None:
        billing_rows = [
            {
                "risk_level": "medium",
                "review_bucket": "standard_high_risk_review",
                "client_name": name,
                "email": f"{index}@example.com",
                "amount_due": "27.99",
                "failure_types": "Client Card Failure",
                "next_charge_date": "2026-05-20",
            }
            for index, name in enumerate(
                [
                    "Archived Client",
                    "Vendor Error Client",
                    "Still Issue Client",
                    "Needs Brandon Client",
                ],
                start=1,
            )
        ]
        active_rows = [
            {
                "client_name": row["client_name"],
                "email": row["email"],
                "status": "Due For Next Round",
                "next_import": "10 Days",
            }
            for row in billing_rows
        ]
        owner_updates = [
            {
                "client_name": "Archived Client",
                "owner_update_status": "archived_or_not_active",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "Not active.",
            },
            {
                "client_name": "Vendor Error Client",
                "owner_update_status": "vendor_or_system_error",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "ScoreFusion needs a fix.",
            },
            {
                "client_name": "Still Issue Client",
                "owner_update_status": "still_billing_issue",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "Failure still real.",
            },
            {
                "client_name": "Needs Brandon Client",
                "owner_update_status": "needs_brandon",
                "owner_update_date": "2026-05-08",
                "owner_update_note": "Owner approval needed.",
            },
        ]

        result = board.build_board(billing_rows, [], [], active_rows, Path("active.csv"), owner_updates)
        decisions = {row["client_name"]: row["decision"] for row in result["billing_actions"]}

        self.assertEqual(result["summary"]["active_billing_issue_clients"], 1)
        self.assertEqual(result["summary"]["non_active_billing_clients"], 3)
        self.assertEqual(result["summary"]["owner_updated_billing_clients"], 3)
        self.assertEqual(decisions["Archived Client"], "owner_reported_archived_monitor_only")
        self.assertEqual(decisions["Vendor Error Client"], "vendor_or_system_error_monitor_only")
        self.assertEqual(decisions["Still Issue Client"], "owner_confirmed_still_billing_issue")
        self.assertEqual(decisions["Needs Brandon Client"], "needs_brandon_billing_hold")

    def test_write_outputs_creates_board_and_duplicate_csv(self) -> None:
        result = board.build_board(
            [
                {
                    "risk_level": "high",
                    "review_bucket": "dual_failure_review",
                    "client_name": "Lisa Sennett",
                    "email": "lisa@example.com",
                    "amount_due": "27.99",
                    "row_count": "2",
                    "duplicate_row_count": "1",
                    "failure_types": "Client Card Failure; Low Credits Failure",
                    "next_charge_date": "2026-05-29",
                }
            ],
            [],
            [],
        )
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with (
                mock.patch.object(board, "OUTPUT_DIR", base),
                mock.patch.object(board, "BOARD_MD", base / "board.md"),
                mock.patch.object(board, "SUMMARY_JSON", base / "summary.json"),
                mock.patch.object(board, "ACTIONS_CSV", base / "actions.csv"),
                mock.patch.object(board, "DUPLICATE_BILLING_CSV", base / "duplicates.csv"),
                mock.patch.object(board, "ACTIVE_BILLING_ISSUES_CSV", base / "active.csv"),
                mock.patch.object(board, "NON_ACTIVE_BILLING_CSV", base / "non-active.csv"),
            ):
                outputs = board.write_outputs(result)
                text = (base / "board.md").read_text(encoding="utf-8")

        self.assertIn("Maintenance Cleanup Board", text)
        self.assertIn("duplicates.csv", outputs["duplicates"])
        self.assertIn("active.csv", outputs["active_billing_issues"])
        self.assertIn("non-active.csv", outputs["non_active_billing"])


if __name__ == "__main__":
    unittest.main()
