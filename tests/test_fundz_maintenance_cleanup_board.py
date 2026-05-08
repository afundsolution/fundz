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
            ):
                outputs = board.write_outputs(result)
                text = (base / "board.md").read_text(encoding="utf-8")

        self.assertIn("Maintenance Cleanup Board", text)
        self.assertIn("duplicates.csv", outputs["duplicates"])


if __name__ == "__main__":
    unittest.main()
