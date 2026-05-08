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

import fundz_operational_state as ops


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class FundzOperationalStateTests(unittest.TestCase):
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
                    "status": "Due For Next Round",
                    "messages": "None",
                    "billing": "",
                    "next_import": "0 Days",
                    "started": "05/01/2026",
                    "assigned_to": "Brandon Jordan",
                    "stage_in_process": "Round 2 Sent (05/01/26)",
                    "onboarding": "100%",
                    "action": "Email",
                },
                {
                    "source": "disputefox_active_clients_full",
                    "client_name": "Ben Franklin",
                    "email": "ben@example.com",
                    "status": "In Dispute",
                    "messages": "None",
                    "billing": "",
                    "next_import": "14 Days",
                    "started": "04/15/2026",
                    "assigned_to": "Brandon Jordan",
                    "stage_in_process": "Round 1 Sent (04/15/26)",
                    "onboarding": "100%",
                    "action": "Email",
                },
                {
                    "source": "disputefox_active_clients_full",
                    "client_name": "Erika Jordan *New",
                    "email": "erika@example.com",
                    "status": "In Dispute",
                    "messages": "None",
                    "billing": "",
                    "next_import": "18 Days",
                    "started": "04/17/2026",
                    "assigned_to": "Brandon Jordan",
                    "stage_in_process": "Round 1 Sent (04/17/26)",
                    "onboarding": "75%",
                    "action": "Email",
                },
            ],
        )
        write_csv(
            self.source_dir / "disputefox-dispute-deleted-repaired-report-20260502.csv",
            [
                {
                    "source": "disputefox_dispute_deleted_repaired_report",
                    "page": "001",
                    "client_name": "Ada Lovelace",
                    "all_items": "10",
                    "in_dispute_count": "7",
                    "deleted_count": "3",
                    "repaired_count": "0",
                },
                {
                    "source": "disputefox_dispute_deleted_repaired_report",
                    "page": "001",
                    "client_name": "Erika Jordan",
                    "all_items": "38",
                    "in_dispute_count": "38",
                    "deleted_count": "0",
                    "repaired_count": "0",
                }
            ],
        )
        write_csv(
            self.source_dir / "disputefox-email-report-20260502.csv",
            [
                {
                    "source": "disputefox_email_report",
                    "page": "1",
                    "client_name": "Ada Lovelace",
                    "sent_to": "ada@example.com",
                    "email_from": "Brandon",
                    "subject": "Ada - Your Second Round has Been Sent Out!",
                    "sent_date": "1 Hour ago",
                },
                {
                    "source": "disputefox_email_report",
                    "page": "1",
                    "client_name": "Ada Lovelace",
                    "sent_to": "ada@example.com",
                    "email_from": "noreply",
                    "subject": "Payment Failure for 3B Credit Report",
                    "sent_date": "2 Hours ago",
                },
            ],
        )
        write_csv(
            self.source_dir / "disputefox-sms-report-20260502.csv",
            [
                {
                    "source": "disputefox_sms_report",
                    "page": "1",
                    "customer_name": "Ada Lovelace",
                    "sent_to": "15555550123",
                    "sms_from": "+18559145567",
                },
                {
                    "source": "disputefox_sms_report",
                    "page": "1",
                    "customer_name": "Rhaunn Franklin",
                    "sent_to": "15555550124",
                    "sms_from": "+18559145567",
                }
            ],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_builds_master_state_from_disputefox_reports(self) -> None:
        state = ops.build_operational_state(self.source_dir, recent_limit=1)
        clients = {client["client_name"]: client for client in state["clients"]}
        ada = clients["Ada Lovelace"]
        ben = clients["Ben Franklin"]

        self.assertEqual(state["summary"]["active_clients"], 3)
        self.assertEqual(state["summary"]["clients"], 4)
        self.assertEqual(state["summary"]["due_for_next_round"], 1)
        self.assertEqual(state["summary"]["email_sends_linked"], 2)
        self.assertEqual(state["summary"]["sms_sends_linked"], 2)
        self.assertEqual(ada["dispute_items"]["deleted_count"], 3)
        self.assertEqual(ada["dispute_round"]["number"], 2)
        self.assertEqual(ada["send_history"]["email_count"], 2)
        self.assertEqual(len(ada["send_history"]["recent_emails"]), 1)
        self.assertIn("dispute_round_sent", ada["send_history"]["email_subject_tags"])
        self.assertIn("payment_attention", ada["operational_flags"])
        self.assertIn("due_for_next_round", ada["operational_flags"])
        self.assertIn("in_dispute", ben["operational_flags"])
        self.assertIn("no_send_history_linked", ben["operational_flags"])

        rhaunn = clients["Rhaunn Franklin"]
        self.assertFalse(rhaunn["is_active_client"])
        self.assertIn("history_only_record", rhaunn["operational_flags"])
        self.assertIn("active-client export does not include current status", rhaunn["recommended_next_action"])

    def test_merges_new_label_and_prints_client_update(self) -> None:
        state = ops.build_operational_state(self.source_dir, recent_limit=1)
        matches = ops.find_client_matches(state, "Erika Jordan")

        self.assertEqual(len(matches), 1)
        erika = matches[0]
        self.assertEqual(erika["client_name"], "Erika Jordan *New")
        self.assertTrue(erika["is_active_client"])
        self.assertEqual(erika["status"], "In Dispute")
        self.assertEqual(erika["dispute_items"]["all_items"], 38)

        update = ops.format_client_update(erika)
        self.assertIn("Latest FUNDz update for Erika Jordan *New", update)
        self.assertIn("Status: In Dispute", update)
        self.assertIn("38 total, 38 in dispute", update)

    def test_every_active_client_can_be_found_by_name(self) -> None:
        state = ops.build_operational_state(self.source_dir, recent_limit=1)

        for client in state["clients"]:
            if not client["is_active_client"]:
                continue
            with self.subTest(client=client["client_name"]):
                matches = ops.find_client_matches(state, client["client_name"])
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["client_key"], client["client_key"])

    def test_client_index_supports_history_only_and_fuzzy_lookup(self) -> None:
        state = ops.build_operational_state(self.source_dir, recent_limit=1)
        index = ops.build_client_index(state)

        exact = ops.find_index_matches(index, "Rhaunn Franklin")
        fuzzy = ops.find_index_matches(index, "Rhaun Franklin")

        self.assertEqual(exact[0]["client_name"], "Rhaunn Franklin")
        self.assertEqual(fuzzy[0]["client_name"], "Rhaunn Franklin")
        self.assertFalse(fuzzy[0]["is_active_client"])
        self.assertEqual(fuzzy[0]["sms_count"], 1)

    def test_writes_json_and_summary_csv(self) -> None:
        state = ops.build_operational_state(self.source_dir)
        output = Path(self.temp_dir.name) / "state.json"
        summary = Path(self.temp_dir.name) / "summary.csv"
        client_index = Path(self.temp_dir.name) / "client-index.json"

        ops.write_json(output, state)
        ops.write_summary_csv(summary, state["clients"])
        ops.write_client_index(client_index, state)

        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["active_clients"], 3)
        with summary.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["is_active_client"], "true")
        index = json.loads(client_index.read_text(encoding="utf-8"))
        self.assertEqual(len(index["clients"]), 4)
        self.assertIn("ada lovelace", index["by_normalized_name"])
        self.assertIn("rhaunn franklin", index["by_normalized_name"])
        self.assertIn("Use this index before saying a client record is unavailable", index["lookup_policy"])


if __name__ == "__main__":
    unittest.main()
