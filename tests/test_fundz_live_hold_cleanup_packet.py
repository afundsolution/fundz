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

import fundz_live_hold_cleanup_packet as cleanup


class FundzLiveHoldCleanupPacketTests(unittest.TestCase):
    def test_build_cleanup_rows_classifies_bounce_archived_and_live_billing_holds(self) -> None:
        packet = {
            "held_candidates": [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "stage_in_process": "Round 7 sent",
                    "reason": "DF latest email status: bounce",
                },
                {
                    "client_name": "James Hawkins",
                    "client_key": "name:james-hawkins",
                    "stage_in_process": "Round 5 Ready",
                    "reason": "DF live client status: Archived - Round 5 Ready",
                },
                {
                    "client_name": "Jessica Saizan",
                    "client_key": "name:jessica-saizan",
                    "stage_in_process": "Round 7 sent",
                    "reason": "live DF review hold: Live DF dashboard showed a payment-failed warning banner during pre-send review.",
                },
                {
                    "client_name": "Marlon Moore",
                    "client_key": "name:marlon-moore",
                    "stage_in_process": "Round 7 sent",
                    "reason": "already sent in prior receipt: batch-1",
                },
            ]
        }

        rows = cleanup.build_cleanup_rows(packet)
        decisions = {row["client_name"]: row["cleanup_decision"] for row in rows}

        self.assertEqual(decisions["Darryl Hatcher"], "repair_bounced_email_route")
        self.assertEqual(decisions["James Hawkins"], "exclude_archived_or_inactive")
        self.assertEqual(decisions["Jessica Saizan"], "hold_live_billing_warning")
        self.assertNotIn("Marlon Moore", decisions)

    def test_bounce_route_exclusion_is_not_listed_as_repairable(self) -> None:
        packet = {
            "held_candidates": [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "stage_in_process": "Round 7 sent",
                    "reason": "live DF review hold: Bounce-route excluded after cleanup review; no verified replacement email route is recorded.",
                }
            ]
        }

        rows = cleanup.build_cleanup_rows(packet)

        self.assertEqual(rows[0]["cleanup_decision"], "exclude_bounced_email_route")

    def test_maintenance_cleanup_exclusion_stays_excluded(self) -> None:
        packet = {
            "held_candidates": [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "stage_in_process": "Round 7 sent",
                    "reason": "maintenance cleanup block: exclude_bounced_email_route / bounce_or_email_failure - Keep out of outreach.",
                }
            ]
        }

        rows = cleanup.build_cleanup_rows(packet)

        self.assertEqual(rows[0]["cleanup_decision"], "exclude_bounced_email_route")

    def test_final_live_billing_exclusion_is_terminal(self) -> None:
        packet = {
            "held_candidates": [
                {
                    "client_name": "Jessica Saizan",
                    "client_key": "name:jessica-saizan",
                    "stage_in_process": "Round 7 sent",
                    "reason": "live DF review hold: Final rollout exclusion: payment-failed warning remained uncleared.",
                }
            ]
        }

        rows = cleanup.build_cleanup_rows(packet)

        self.assertEqual(rows[0]["cleanup_decision"], "exclude_live_billing_or_payment_hold")

    def test_write_outputs_creates_review_packet(self) -> None:
        rows = [
            {
                "client_name": "Darryl Hatcher",
                "client_key": "name:darryl-hatcher",
                "stage_in_process": "Round 7 sent",
                "blocker_type": "bounce_or_email_failure",
                "cleanup_decision": "repair_bounced_email_route",
                "source_reason": "DF latest email status: bounce",
                "next_step": "Repair email route.",
            }
        ]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            outputs = cleanup.write_outputs(
                rows,
                csv_path=base / "cleanup.csv",
                md_path=base / "cleanup.md",
                generated_at="2026-05-07T18:00:00-0500",
            )

            self.assertTrue((base / "cleanup.csv").exists())
            text = (base / "cleanup.md").read_text(encoding="utf-8")

        self.assertIn("Bounce + Live-Hold Cleanup", text)
        self.assertIn("repair_bounced_email_route", text)
        self.assertIn("cleanup.csv", outputs["csv"])

    def test_build_from_files_reads_packet_json(self) -> None:
        packet = {
            "held_candidates": [
                {
                    "client_name": "Lisa Sennett",
                    "client_key": "name:lisa-sennett",
                    "stage_in_process": "Round 8 Ready",
                    "reason": "live DF review hold: Billing-risk cleanup decision held for one unique-client duplicate failure review before any outreach.",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "packet.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            rows = cleanup.build_from_files(path)

        self.assertEqual(rows[0]["cleanup_decision"], "already_excluded_until_billing_clears")


if __name__ == "__main__":
    unittest.main()
