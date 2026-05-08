from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_autofox_rollout_packet as rollout


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class FundzAutoFoxRolloutPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.patches = [
            mock.patch.object(rollout, "OUTPUT_DIR", self.base / "autofox-rollout"),
            mock.patch.object(rollout, "PACKET_JSON", self.base / "autofox-rollout" / "packet.json"),
            mock.patch.object(rollout, "PREVIEW_MD", self.base / "autofox-rollout" / "preview.md"),
            mock.patch.object(rollout, "IMPORT_CSV", self.base / "autofox-rollout" / "import.csv"),
            mock.patch.object(rollout, "EXECUTION_MD", self.base / "autofox-rollout" / "execution.md"),
            mock.patch.object(rollout, "LIVE_REVIEW_CSV", self.base / "autofox-rollout" / "live-review.csv"),
            mock.patch.object(rollout, "MAINTENANCE_CLEANUP_CSV", self.base / "autofox-rollout" / "maintenance-cleanup.csv"),
            mock.patch.object(rollout, "CONTROL_BOARD_CSV", self.base / "control.csv"),
            mock.patch.object(rollout, "DISPUTE_FOX_DIR", self.base / "dispute-fox"),
            mock.patch.object(rollout.semi, "BATCH_RECEIPT_DIR", self.base / "receipts"),
            mock.patch.object(rollout.semi, "BILLING_RISK_REVIEW_CSV", self.base / "billing.csv"),
        ]
        for patcher in self.patches:
            patcher.start()
        write_csv(rollout.CONTROL_BOARD_CSV, [], fields=["client_name", "client_key", "communication_status", "app_readiness", "email_allowed"])
        write_csv(
            rollout.LIVE_REVIEW_CSV,
            [],
            fields=[
                "client_name",
                "client_key",
                "email",
                "df_client_status",
                "latest_email_status",
                "rollout_decision",
                "hold_reason",
            ],
        )
        write_csv(
            rollout.MAINTENANCE_CLEANUP_CSV,
            [],
            fields=[
                "client_name",
                "client_key",
                "stage_in_process",
                "blocker_type",
                "cleanup_decision",
                "source_reason",
                "next_step",
            ],
        )
        write_csv(rollout.semi.BILLING_RISK_REVIEW_CSV, [], fields=["client_name", "review_bucket"])
        rollout.DISPUTE_FOX_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp_dir.cleanup()

    def client(self, name: str, round_number: int = 13, **overrides: object) -> dict:
        data = {
            "client_key": f"name:{rollout.normalize_name(name).replace(' ', '-')}",
            "is_active_client": True,
            "client_name": name,
            "email": f"{rollout.normalize_name(name).replace(' ', '.')}@example.com",
            "status": "Due For Next Round",
            "stage_in_process": f"Round {round_number} Ready",
            "dispute_round": {"number": round_number, "label": f"Round {round_number}"},
            "operational_flags": ["due_for_next_round"],
            "send_history": {"recipients": [], "recent_sms": []},
        }
        data.update(overrides)
        return data

    def test_df_email_ready_does_not_require_highlevel_contact_resolution(self) -> None:
        client = self.client("James Hawkins", round_number=13)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        self.assertEqual(packet["selected"], 1)
        item = packet["items"][0]
        self.assertEqual(item["client_name"], "James Hawkins")
        self.assertTrue(item["df_email_ready"])
        self.assertFalse(item["mobile_app_sms_ready"])
        self.assertEqual(item["autofox_id"], "")
        self.assertIn("Send DF email only", item["recommended_df_action"])

    def test_excludes_billing_risk_and_prior_sent_clients(self) -> None:
        sent_client = self.client("Karenthea Cameron *New", round_number=5)
        billing_client = self.client("Bianca Alexander", round_number=5)
        ready_client = self.client("Jessica Saizan", round_number=5)
        state = {"clients": [sent_client, billing_client, ready_client], "summary": {"active_clients": 3}}
        queue = rollout.semi.build_action_queue(state)
        rollout.semi.BATCH_RECEIPT_DIR.mkdir(parents=True)
        (rollout.semi.BATCH_RECEIPT_DIR / "prior-result.json").write_text(
            json.dumps({"batch_id": "prior-batch", "sent": 1, "results": [{"client_name": "Karenthea Cameron", "sent": True}]}),
            encoding="utf-8",
        )
        write_csv(
            rollout.semi.BILLING_RISK_REVIEW_CSV,
            [{"client_name": "Bianca Alexander", "review_bucket": "date_sensitive_next_7_days"}],
            fields=["client_name", "review_bucket"],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=3, scan_limit=20)

        self.assertEqual([item["client_name"] for item in packet["items"]], ["Jessica Saizan"])
        reasons = {item["client_name"]: item["reason"] for item in packet["held_candidates"]}
        self.assertIn("already sent", reasons["Karenthea Cameron *New"])
        self.assertIn("billing-risk", reasons["Bianca Alexander"])

    def test_excludes_prior_single_client_df_receipt(self) -> None:
        sent_client = self.client("Marlon Moore", round_number=7)
        ready_client = self.client("Mia Bluitt", round_number=12)
        state = {"clients": [sent_client, ready_client], "summary": {"active_clients": 2}}
        queue = rollout.semi.build_action_queue(state)
        rollout.semi.BATCH_RECEIPT_DIR.mkdir(parents=True)
        (rollout.semi.BATCH_RECEIPT_DIR / "df-email-marlon-result.json").write_text(
            json.dumps(
                {
                    "client_name": "Marlon Moore",
                    "client_key": "name:marlon-moore",
                    "channel": "df_email",
                    "sent": True,
                    "provider_result": "success",
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=2, scan_limit=20)

        self.assertEqual([item["client_name"] for item in packet["items"]], ["Mia Bluitt"])
        reasons = {item["client_name"]: item["reason"] for item in packet["held_candidates"]}
        self.assertIn("already sent", reasons["Marlon Moore"])

    def test_excludes_archived_live_review_clients(self) -> None:
        client = self.client("James Hawkins", round_number=5)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.LIVE_REVIEW_CSV,
            [
                {
                    "client_name": "James Hawkins",
                    "client_key": "name:james-hawkins",
                    "email": "",
                    "df_client_status": "Archived - Round 5 Ready",
                    "latest_email_status": "",
                    "rollout_decision": "",
                    "hold_reason": "",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "email",
                "df_client_status",
                "latest_email_status",
                "rollout_decision",
                "hold_reason",
            ],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        self.assertEqual(packet["selected"], 0)
        reason = packet["held_candidates"][0]["reason"]
        self.assertIn("archived", reason.lower())

    def test_excludes_bounced_live_review_email_status(self) -> None:
        client = self.client("Darryl Hatcher", round_number=7)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.LIVE_REVIEW_CSV,
            [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "email": "",
                    "df_client_status": "Active - Round 7 Sent",
                    "latest_email_status": "bounce",
                    "rollout_decision": "",
                    "hold_reason": "",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "email",
                "df_client_status",
                "latest_email_status",
                "rollout_decision",
                "hold_reason",
            ],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        self.assertEqual(packet["selected"], 0)
        reason = packet["held_candidates"][0]["reason"]
        self.assertIn("email status", reason.lower())
        self.assertIn("bounce", reason.lower())

    def test_live_review_hold_reason_wins_over_generic_hold_decision(self) -> None:
        client = self.client("Lue L. Paige", round_number=7)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.LIVE_REVIEW_CSV,
            [
                {
                    "client_name": "Lue L. Paige",
                    "client_key": "name:lue-l-paige",
                    "email": "",
                    "df_client_status": "Active - Round 7 Sent",
                    "latest_email_status": "",
                    "rollout_decision": "hold",
                    "hold_reason": "Billing-risk cleanup decision excluded from normal outreach.",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "email",
                "df_client_status",
                "latest_email_status",
                "rollout_decision",
                "hold_reason",
            ],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        self.assertEqual(packet["selected"], 0)
        reason = packet["held_candidates"][0]["reason"]
        self.assertIn("Billing-risk cleanup decision", reason)

    def test_maintenance_cleanup_blocks_future_rollout_even_without_live_review_row(self) -> None:
        client = self.client("Darryl Hatcher", round_number=7)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.MAINTENANCE_CLEANUP_CSV,
            [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "stage_in_process": "Round 7 sent",
                    "blocker_type": "bounce_or_email_failure",
                    "cleanup_decision": "exclude_bounced_email_route",
                    "source_reason": "No verified replacement route.",
                    "next_step": "Keep out of outreach until a verified replacement email route is recorded.",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "stage_in_process",
                "blocker_type",
                "cleanup_decision",
                "source_reason",
                "next_step",
            ],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        self.assertEqual(packet["selected"], 0)
        reason = packet["held_candidates"][0]["reason"]
        self.assertIn("maintenance cleanup block", reason)
        self.assertIn("exclude_bounced_email_route", reason)

    def test_live_review_block_takes_precedence_over_maintenance_cleanup_row(self) -> None:
        client = self.client("Darryl Hatcher", round_number=7)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.LIVE_REVIEW_CSV,
            [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "email": "",
                    "df_client_status": "Active - Round 7 Sent",
                    "latest_email_status": "",
                    "rollout_decision": "hold",
                    "hold_reason": "Bounce-route excluded after cleanup review; no verified replacement email route is recorded.",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "email",
                "df_client_status",
                "latest_email_status",
                "rollout_decision",
                "hold_reason",
            ],
        )
        write_csv(
            rollout.MAINTENANCE_CLEANUP_CSV,
            [
                {
                    "client_name": "Darryl Hatcher",
                    "client_key": "name:darryl-hatcher",
                    "stage_in_process": "Round 7 sent",
                    "blocker_type": "bounce_or_email_failure",
                    "cleanup_decision": "repair_bounced_email_route",
                    "source_reason": "Older repair row.",
                    "next_step": "Verify route.",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "stage_in_process",
                "blocker_type",
                "cleanup_decision",
                "source_reason",
                "next_step",
            ],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        reason = packet["held_candidates"][0]["reason"]
        self.assertIn("Bounce-route excluded", reason)
        self.assertNotIn("maintenance cleanup block", reason)

    def test_maintenance_cleanup_allows_non_blocking_cleared_rows(self) -> None:
        client = self.client("Ada Lovelace", round_number=6)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.MAINTENANCE_CLEANUP_CSV,
            [
                {
                    "client_name": "Ada Lovelace",
                    "client_key": "name:ada-lovelace",
                    "stage_in_process": "Round 6 Ready",
                    "blocker_type": "bounce_or_email_failure",
                    "cleanup_decision": "cleared",
                    "source_reason": "Verified replacement route.",
                    "next_step": "Allow new packet preflight.",
                }
            ],
            fields=[
                "client_name",
                "client_key",
                "stage_in_process",
                "blocker_type",
                "cleanup_decision",
                "source_reason",
                "next_step",
            ],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        self.assertEqual(packet["selected"], 1)
        self.assertEqual(packet["items"][0]["client_name"], "Ada Lovelace")

    def test_mobile_app_sms_requires_installed_logged_in_and_round_campaign_map(self) -> None:
        client = self.client("Ada Lovelace", round_number=6)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.CONTROL_BOARD_CSV,
            [
                {
                    "client_name": "Ada Lovelace",
                    "client_key": "name:ada-lovelace",
                    "communication_status": "Prepare only",
                    "app_readiness": "Installed / Logged In",
                    "email_allowed": "yes - approval/proof gated",
                }
            ],
            fields=["client_name", "client_key", "communication_status", "app_readiness", "email_allowed"],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)

        item = packet["items"][0]
        self.assertTrue(item["mobile_app_sms_ready"])
        self.assertEqual(item["autofox_id"], "160063")
        self.assertIn("Round 6 Sent", item["autofox_workflow"])

    def test_outputs_include_direct_df_execution_links(self) -> None:
        client = self.client("James Hawkins", round_number=5)
        state = {"clients": [client], "summary": {"active_clients": 1}}
        queue = rollout.semi.build_action_queue(state)
        write_csv(
            rollout.DISPUTE_FOX_DIR / "disputefox-active-clients-20260502.csv",
            [
                {
                    "client_name": "James Hawkins",
                    "email": client["email"],
                    "customer_id": "customer-1",
                    "customer_url": "https://pulse.disputeprocess.com/jsp/admin/customer_dashboard.jsp?id=customer-1",
                }
            ],
            fields=["client_name", "email", "customer_id", "customer_url"],
        )

        with mock.patch.object(rollout.semi, "run_once", return_value=(state, queue)):
            packet = rollout.build_packet(size=1, scan_limit=20)
            outputs = rollout.write_outputs(packet)

        item = packet["items"][0]
        self.assertEqual(item["customer_id"], "customer-1")
        self.assertIn("customer-1", item["customer_url"])
        self.assertTrue(rollout.EXECUTION_MD.exists())
        self.assertIn("DF Email Execution Checklist", rollout.EXECUTION_MD.read_text(encoding="utf-8"))
        self.assertIn("execution", outputs)


if __name__ == "__main__":
    unittest.main()
