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

import fundz_stale_import_archive_packet as packet


class FundzStaleImportArchivePacketTests(unittest.TestCase):
    def test_parse_next_import_days_accepts_negative_day_labels(self) -> None:
        self.assertEqual(packet.parse_next_import_days("-30 Days"), -30)
        self.assertEqual(packet.parse_next_import_days("-147 days"), -147)
        self.assertEqual(packet.parse_next_import_days("20 Days"), 20)
        self.assertIsNone(packet.parse_next_import_days("Tomorrow"))
        self.assertIsNone(packet.parse_next_import_days(""))

    def test_build_archive_rows_filters_threshold_and_omits_private_contact_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "data" / "dispute-fox" / "disputefox-active-clients-full-20260502.csv"
            source.parent.mkdir(parents=True)
            rows = [
                {
                    "client_name": "Kenyetta Martin",
                    "email": "private@example.com",
                    "status": "Due For Next Round",
                    "stage_in_process": "Round 7 Ready",
                    "next_import": "-147 Days",
                    "onboarding": "75%",
                },
                {
                    "client_name": "Raquel Dawson",
                    "email": "private2@example.com",
                    "status": "In Dispute",
                    "stage_in_process": "Round 2 Sent",
                    "next_import": "20 Days",
                    "onboarding": "50%",
                },
            ]
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

            built = packet.build_archive_rows(rows, threshold_days=-30, source=source)

        self.assertEqual([row["client_name"] for row in built], ["Kenyetta Martin"])
        self.assertEqual(built[0]["client_key"], "name:kenyetta-martin")
        self.assertNotIn("email", built[0])

    def test_build_archive_rows_honors_owner_exclusions(self) -> None:
        rows = [
            {
                "client_name": "Kenyetta Martin",
                "status": "Due For Next Round",
                "stage_in_process": "Round 7 Ready",
                "next_import": "-147 Days",
                "onboarding": "75%",
            },
            {
                "client_name": "Princess Johnson *New",
                "status": "In Dispute",
                "stage_in_process": "Round 19 Ready",
                "next_import": "-71 Days",
                "onboarding": "100%",
            },
        ]

        built = packet.build_archive_rows(
            rows,
            threshold_days=-30,
            source=ROOT / "data" / "dispute-fox" / "disputefox-active-clients-full-20260502.csv",
            excluded_keys={"name:princess-johnson"},
        )
        exceptions = packet.excluded_archive_rows(
            rows,
            threshold_days=-30,
            source=ROOT / "data" / "dispute-fox" / "disputefox-active-clients-full-20260502.csv",
            excluded_keys={"name:princess-johnson"},
        )

        self.assertEqual([row["client_name"] for row in built], ["Kenyetta Martin"])
        self.assertEqual([row["client_name"] for row in exceptions], ["Princess Johnson *New"])
        self.assertEqual(exceptions[0]["archive_decision"], "owner_excluded_from_archive_for_now")

    def test_merge_suppressions_preserves_live_archived_rows_and_updates_holds(self) -> None:
        existing = [
            {
                "client_name": "Sammy Adeiye",
                "client_key": "name:sammy-adeiye",
                "queue_status": "Done",
                "reason": "archive_review_completed_credit_monitoring",
                "do_not_send_because": "Archived in DF after live ScoreFusion monitoring confirmation; no normal outreach.",
            },
            {
                "client_name": "Kenyetta Martin",
                "client_key": "name:kenyetta-martin",
                "queue_status": "Hold",
                "reason": "still_hold_billing_and_onboarding",
            },
        ]
        archive_rows = [
            {
                "client_name": "Sammy Adeiye",
                "client_key": "name:sammy-adeiye",
                "next_import": "-73 Days",
            },
            {
                "client_name": "Kenyetta Martin",
                "client_key": "name:kenyetta-martin",
                "next_import": "-147 Days",
            },
        ]

        merged, counts = packet.merge_suppressions(
            existing,
            archive_rows,
            generated_date="2026-05-08",
            evidence=ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-stale-import-archive-review.csv",
        )
        by_key = {row["client_key"]: row for row in merged}

        self.assertEqual(counts["preserved_live_archived"], 1)
        self.assertEqual(by_key["name:sammy-adeiye"]["reason"], "archive_review_completed_credit_monitoring")
        self.assertEqual(by_key["name:kenyetta-martin"]["queue_status"], "Done")
        self.assertEqual(by_key["name:kenyetta-martin"]["reason"], "archive_directed_stale_next_import_30_days")

    def test_remove_excluded_stale_archive_suppressions_only_removes_archive_reason(self) -> None:
        existing = [
            {
                "client_name": "Princess Johnson *New",
                "client_key": "name:princess-johnson",
                "queue_status": "Done",
                "reason": "archive_directed_stale_next_import_30_days",
            },
            {
                "client_name": "Anthony Williams",
                "client_key": "name:anthony-williams",
                "queue_status": "Done",
                "reason": "done_no_action_owner_exception",
            },
        ]

        kept, removed = packet.remove_excluded_stale_archive_suppressions(
            existing,
            {"name:princess-johnson", "name:anthony-williams"},
        )

        self.assertEqual(removed, 1)
        self.assertEqual([row["client_name"] for row in kept], ["Anthony Williams"])

    def test_mark_live_archived_rows_keeps_confirmed_archives_distinct(self) -> None:
        rows = [
            {
                "client_name": "Sammy Adeiye",
                "client_key": "name:sammy-adeiye",
                "archive_decision": "archive_requested_stale_next_import_owner_directed",
                "reason": "Owner rule",
                "next_action": "Archive live.",
            }
        ]
        marked = packet.mark_live_archived_rows(
            rows,
            [
                {
                    "client_name": "Sammy Adeiye",
                    "client_key": "name:sammy-adeiye",
                    "reason": "archive_review_completed_credit_monitoring",
                    "do_not_send_because": "Archived in DF after live ScoreFusion monitoring confirmation; no normal outreach.",
                }
            ],
        )

        self.assertEqual(marked[0]["archive_decision"], "already_archived_live_confirmed")
        self.assertIn("already archived", marked[0]["reason"])
