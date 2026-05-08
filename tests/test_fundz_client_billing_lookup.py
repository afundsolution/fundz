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

import fundz_client_billing_lookup as lookup


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class FundzClientBillingLookupTests(unittest.TestCase):
    def test_scorefusion_blank_says_check_alternate_provider_not_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            state = base / "state.csv"
            empty = base / "empty.csv"
            write_csv(
                state,
                [
                    {
                        "client_name": "Erika Jordan",
                        "is_active_client": "true",
                        "status": "In Dispute",
                        "stage_in_process": "Round 1 Sent",
                        "onboarding_percent": "75",
                    }
                ],
                ["client_name", "is_active_client", "status", "stage_in_process", "onboarding_percent"],
            )
            write_csv(empty, [], ["client_name"])
            with (
                mock.patch.object(lookup, "CLIENT_STATE_SUMMARY_CSV", state),
                mock.patch.object(lookup, "BILLING_MAINTENANCE_CSV", empty),
                mock.patch.object(lookup, "DUPLICATE_BILLING_CSV", empty),
                mock.patch.object(lookup, "SCOREFUSION_ROSTER_CSV", empty),
                mock.patch.object(lookup, "SCOREFUSION_RISK_CSV", empty),
                mock.patch.object(lookup, "ARCHIVE_REVIEW_CSV", empty),
                mock.patch.object(lookup, "LIVE_HOLD_CSV", empty),
                mock.patch.object(lookup, "DF_MONITORING_PROOF_CSV", empty),
            ):
                result = lookup.build_lookup("Erika Jordan")
                answer = lookup.answer_text(result)

        self.assertEqual(result["local_scorefusion_status"], "not_found_check_alternate_monitoring_provider")
        self.assertIn("Check alternate monitoring provider", result["plain_status"])
        self.assertIn("MyScoreIQ", result["plain_status"])
        self.assertNotIn("inactive", result["plain_status"].lower())
        self.assertIn("ScoreFusion evidence does not show an active ScoreFusion record", answer)

    def test_scorefusion_roster_row_reports_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            state = base / "state.csv"
            roster = base / "roster.csv"
            empty = base / "empty.csv"
            write_csv(
                state,
                [{"client_name": "Jordan Castillo", "status": "In Dispute"}],
                ["client_name", "status"],
            )
            write_csv(
                roster,
                [
                    {
                        "client_name": "Jordan Castillo",
                        "billing_status": "Client Card Failure",
                        "next_charge_date": "2026-05-21",
                        "amount_due": "27.99",
                    }
                ],
                ["client_name", "billing_status", "next_charge_date", "amount_due"],
            )
            write_csv(empty, [], ["client_name"])
            with (
                mock.patch.object(lookup, "CLIENT_STATE_SUMMARY_CSV", state),
                mock.patch.object(lookup, "BILLING_MAINTENANCE_CSV", empty),
                mock.patch.object(lookup, "DUPLICATE_BILLING_CSV", empty),
                mock.patch.object(lookup, "SCOREFUSION_ROSTER_CSV", roster),
                mock.patch.object(lookup, "SCOREFUSION_RISK_CSV", empty),
                mock.patch.object(lookup, "ARCHIVE_REVIEW_CSV", empty),
                mock.patch.object(lookup, "LIVE_HOLD_CSV", empty),
                mock.patch.object(lookup, "DF_MONITORING_PROOF_CSV", empty),
            ):
                result = lookup.build_lookup("Jordan Castillo")

        self.assertEqual(result["local_scorefusion_status"], "found_in_local_scorefusion_evidence")
        self.assertEqual(result["scorefusion_evidence"]["roster"]["amount_due"], "27.99")

    def test_df_credit_monitoring_proof_reports_alternate_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            state = base / "state.csv"
            monitoring = base / "monitoring.csv"
            empty = base / "empty.csv"
            write_csv(
                state,
                [{"client_name": "Erika Jordan", "status": "In Dispute"}],
                ["client_name", "status"],
            )
            write_csv(
                monitoring,
                [
                    {
                        "client_name": "Erika Jordan",
                        "monitoring_agency": "MyScoreIQ",
                        "app_status_provider": "Credit Tracker",
                        "app_status": "Logged In",
                        "verified_at": "2026-05-07",
                    }
                ],
                ["client_name", "monitoring_agency", "app_status_provider", "app_status", "verified_at"],
            )
            write_csv(empty, [], ["client_name"])
            with (
                mock.patch.object(lookup, "CLIENT_STATE_SUMMARY_CSV", state),
                mock.patch.object(lookup, "BILLING_MAINTENANCE_CSV", empty),
                mock.patch.object(lookup, "DUPLICATE_BILLING_CSV", empty),
                mock.patch.object(lookup, "SCOREFUSION_ROSTER_CSV", empty),
                mock.patch.object(lookup, "SCOREFUSION_RISK_CSV", empty),
                mock.patch.object(lookup, "ARCHIVE_REVIEW_CSV", empty),
                mock.patch.object(lookup, "LIVE_HOLD_CSV", empty),
                mock.patch.object(lookup, "DF_MONITORING_PROOF_CSV", monitoring),
            ):
                result = lookup.build_lookup("Erika Jordan")
                answer = lookup.answer_text(result)

        self.assertEqual(result["scorefusion_evidence"]["df_credit_monitoring"]["monitoring_agency"], "MyScoreIQ")
        self.assertIn("DF credit monitoring proof", answer)
        self.assertIn("MyScoreIQ", answer)
        self.assertIn("Credit Tracker / Logged In", answer)
        self.assertEqual(
            lookup.monitoring_reply_text(result),
            "Erika Jordan: No active ScoreFusion. DF has MyScoreIQ as the CMS; Credit Tracker shows Logged In.",
        )


if __name__ == "__main__":
    unittest.main()
