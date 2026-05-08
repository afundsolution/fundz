from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_billing_risk_cleanup_packet as cleanup


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class FundzBillingRiskCleanupPacketTests(unittest.TestCase):
    def test_builds_cleanup_rows_for_rollout_billing_blockers(self) -> None:
        packet = {
            "held_candidates": [
                {
                    "client_name": "Clean Client",
                    "stage_in_process": "Round 5 Ready",
                    "reason": "already sent in prior receipt: abc",
                },
                {
                    "client_name": "Sammy Adeiye",
                    "stage_in_process": "Round 5 Ready",
                    "reason": "billing-risk review queue: urgent_due_now_or_past_due",
                },
                {
                    "client_name": "Lisa Sennett",
                    "stage_in_process": "Round 8 Ready",
                    "reason": "billing-risk review queue: dual_failure_review",
                },
            ]
        }
        billing_rows = [
            {
                "client_name": "Lisa Sennett",
                "risk_level": "high",
                "review_bucket": "dual_failure_review",
                "amount_due": "27.99",
                "failure_types": "Client Card Failure; Low Credits Failure",
            },
            {
                "client_name": "Sammy Adeiye",
                "risk_level": "high",
                "review_bucket": "urgent_due_now_or_past_due",
                "amount_due": "27.99",
                "next_charge_date": "2026-05-07",
                "failure_types": "Client Card Failure",
            },
        ]

        rows = cleanup.build_cleanup_rows(packet, billing_rows)

        self.assertEqual([row["client_name"] for row in rows], ["Sammy Adeiye", "Lisa Sennett"])
        self.assertEqual(rows[0]["cleanup_decision"], "hold_manual_billing_review")
        self.assertEqual(rows[1]["cleanup_decision"], "dedupe_review_once")

    def test_writes_markdown_and_csv_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            packet_path = base / "packet.json"
            billing_path = base / "billing.csv"
            csv_path = base / "cleanup.csv"
            md_path = base / "cleanup.md"
            packet_path.write_text(
                json.dumps(
                    {
                        "held_candidates": [
                            {
                                "client_name": "Bianca Alexander",
                                "stage_in_process": "Round 5 Ready",
                                "reason": "billing-risk review queue: date_sensitive_next_7_days",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            write_csv(
                billing_path,
                [
                    {
                        "client_name": "Bianca Alexander",
                        "risk_level": "high",
                        "review_bucket": "date_sensitive_next_7_days",
                        "amount_due": "27.99",
                    }
                ],
                fields=["client_name", "risk_level", "review_bucket", "amount_due"],
            )

            rows = cleanup.build_from_files(packet_path, billing_path)
            outputs = cleanup.write_outputs(rows, csv_path=csv_path, md_path=md_path, generated_at="2026-05-07T00:00:00")

            self.assertEqual(outputs["csv"], str(csv_path))
            self.assertTrue(csv_path.exists())
            text = md_path.read_text(encoding="utf-8")
            self.assertIn("Rollout blockers: 1", text)
            self.assertIn("owner_override_needed", text)


if __name__ == "__main__":
    unittest.main()
