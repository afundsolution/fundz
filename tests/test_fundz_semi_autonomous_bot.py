from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_semi_autonomous_bot as semi


class FundzSemiAutonomousBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.env_patch = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.path_patches = [
            mock.patch.object(semi, "RUN_DIR", self.base / "semi"),
            mock.patch.object(semi, "ACTION_QUEUE", self.base / "semi" / "queue.json"),
            mock.patch.object(semi, "ACTION_REPORT", self.base / "semi" / "queue.md"),
            mock.patch.object(semi, "PILOT_PACKET", self.base / "semi" / "pilot-packet.json"),
            mock.patch.object(semi, "BATCH_PACKET", self.base / "semi" / "batch-packet.json"),
            mock.patch.object(semi, "BATCH_REPORT", self.base / "semi" / "batch-preview.md"),
            mock.patch.object(semi, "BATCH_RECEIPT_DIR", self.base / "semi" / "receipts"),
            mock.patch.object(semi, "OWNER_PRE_SEND_NOTICE_RECEIPTS", self.base / "semi" / "receipts" / "fundz-owner-pre-send-notices.jsonl"),
            mock.patch.object(semi, "BILLING_RISK_REVIEW_CSV", self.base / "billing-risk-review.csv"),
        ]
        for patcher in self.path_patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.path_patches):
            patcher.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def sample_state(self) -> dict:
        return {
            "summary": {"active_clients": 2, "due_for_next_round": 1, "in_dispute": 1},
            "clients": [
                {
                    "client_key": "name:ada",
                    "is_active_client": True,
                    "client_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "status": "Due For Next Round",
                    "next_import": "0 Days",
                    "stage_in_process": "Round 2 Sent (05/01/26)",
                    "dispute_round": {"number": 2, "label": "Round 2", "date": "05/01/26"},
                    "operational_flags": ["due_for_next_round"],
                    "send_history": {"recipients": ["15555550123"], "recent_sms": []},
                },
                {
                    "client_key": "name:ben",
                    "is_active_client": True,
                    "client_name": "Ben Franklin",
                    "email": "ben@example.com",
                    "status": "In Dispute",
                    "next_import": "14 Days",
                    "next_import_days": 14,
                    "stage_in_process": "Round 1 Sent (04/15/26)",
                    "dispute_round": {"number": 1, "label": "Round 1", "date": "04/15/26"},
                    "operational_flags": ["in_dispute"],
                    "send_history": {"recipients": ["15555550124"], "recent_sms": []},
                },
            ],
        }

    def pilot_args(self, **overrides):
        defaults = {
            "pilot_name": "Test Client",
            "pilot_contact_id": "contact-test",
            "pilot_conversation_id": "conversation-test",
            "pilot_channel": "SMS",
            "pilot_phone": "+15555550123",
            "pilot_email": "",
            "pilot_message": "",
            "pilot_dry_run": True,
            "pilot_live": False,
            "approved_live_send": False,
            "resolve_contact": False,
            "pilot_location_id": "",
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def write_ready_owner_notice(self, packet: dict, seconds_ago: int = 180) -> None:
        sent_at = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")
        semi.append_owner_pre_send_notice(
            {
                "created_at": sent_at,
                "sent_at": sent_at,
                "notice_key": semi.packet_notice_key(packet),
                "sent": True,
                "dry_run": False,
                "wait_seconds": 120,
            }
        )

    def batch_args(self, **overrides):
        defaults = {
            "batch_size": 3,
            "batch_channel": "Email",
            "batch_location_id": "location-test",
            "batch_packet": str(semi.BATCH_PACKET),
            "batch_client": [],
            "batch_continue_on_failure": False,
            "approved_batch_send": False,
            "resolve_contact": False,
            "batch_preset": "safe_expansion",
            "limit": 250,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_build_action_queue_keeps_live_send_blocked(self) -> None:
        queue = semi.build_action_queue(self.sample_state())
        actions = {item["client_name"]: item for item in queue["actions"]}

        self.assertEqual(actions["Ada Lovelace"]["action_type"], "draft_for_approval")
        self.assertFalse(actions["Ada Lovelace"]["send_allowed_without_owner"])
        self.assertIn("next", actions["Ada Lovelace"]["draft"])
        self.assertEqual(actions["Ada Lovelace"]["message_phase"], "next_round")
        self.assertGreater(actions["Ada Lovelace"]["priority_score"], 0)
        self.assertEqual(actions["Ben Franklin"]["action_type"], "monitor")

    def test_safe_client_message_rotates_by_phase_without_risky_language(self) -> None:
        state = self.sample_state()
        message = semi.safe_client_message(state["clients"][0])

        self.assertIn("Ada", message)
        self.assertIn("next", message.lower())
        self.assertEqual(semi.risky_language_hits(message), [])

    def test_prepare_pilot_writes_packet_and_blocks_risky_text(self) -> None:
        args = self.pilot_args(pilot_message="We guarantee a deletion.")
        packet = semi.prepare_pilot(args)

        self.assertFalse(packet["allowed_by_safety_rules"])
        self.assertTrue(semi.PILOT_PACKET.exists())
        saved = json.loads(semi.PILOT_PACKET.read_text(encoding="utf-8"))
        self.assertIn("guarantee", saved["risky_hits"])

    def test_live_pilot_requires_approval(self) -> None:
        args = self.pilot_args(pilot_dry_run=False, pilot_live=True, approved_live_send=False)
        result = semi.run_pilot(args)

        self.assertFalse(result["sent"])
        self.assertTrue(result["blocked"])
        self.assertIn("approved", result["reason"])

    def test_live_pilot_failure_is_saved_as_blocked_result(self) -> None:
        args = self.pilot_args(pilot_dry_run=False, pilot_live=True, approved_live_send=True)
        os.environ["CREDIT_TRACKER_DRY_RUN"] = "false"
        os.environ["CREDIT_TRACKER_REPLY_URL"] = "https://example.test/reply"
        os.environ["CREDIT_TRACKER_API_TOKEN"] = "token"
        self.write_ready_owner_notice(semi.prepare_pilot(args))

        with (
            mock.patch.object(semi, "send_window_status", return_value=(True, "inside window")),
            mock.patch.object(semi, "send_reply", side_effect=RuntimeError("provider rejected request")),
        ):
            result = semi.run_pilot(args)

        self.assertFalse(result["sent"])
        self.assertTrue(result["blocked"])
        self.assertIn("provider rejected", result["reason"])
        self.assertTrue(Path(result["result_path"]).exists())

    def test_can_resolve_pilot_contact_before_send(self) -> None:
        args = self.pilot_args(pilot_contact_id="auto", resolve_contact=True, pilot_dry_run=True)
        resolved = {
            "ok": True,
            "contact": {"id": "real-contact-id", "firstName": "Test", "email": "test@example.com"},
            "error": None,
        }

        with mock.patch.object(semi, "resolve_contact", return_value=resolved):
            result = semi.run_pilot(args)

        self.assertFalse(result["sent"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["result"]["payload"]["contactId"], "real-contact-id")

    def test_email_pilot_uses_email_safe_payload_shape(self) -> None:
        args = self.pilot_args(
            pilot_channel="Email",
            pilot_phone="",
            pilot_email="test@example.com",
            pilot_dry_run=True,
        )
        result = semi.run_pilot(args)

        payload = result["result"]["payload"]
        self.assertEqual(payload["type"], "Email")
        self.assertEqual(payload["subject"], "FUNDz test message")
        self.assertIn("<p>Hi Test", payload["html"])
        self.assertIn("Please reply received", payload["message"])

    def test_batch_preview_resolves_contacts_and_writes_report(self) -> None:
        state = self.sample_state()
        queue = semi.build_action_queue(state)
        args = self.batch_args(resolve_contact=True)
        resolved = {
            "ok": True,
            "contact": {"id": "highlevel-contact", "firstName": "Ada", "email": "ada@example.com"},
            "error": None,
        }

        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", return_value=resolved),
        ):
            result = semi.build_batch_preview(args)

        self.assertTrue(result["prepared"])
        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["send_ready"], 1)
        self.assertTrue(semi.BATCH_PACKET.exists())
        self.assertTrue(semi.BATCH_REPORT.exists())
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertEqual(packet["items"][0]["payload"]["contact_id"], "highlevel-contact")
        self.assertEqual(packet["items"][0]["outbound_payload_preview"]["subject"], "FUNDz update")

    def test_batch_preview_without_resolution_is_not_send_ready(self) -> None:
        state = self.sample_state()
        queue = semi.build_action_queue(state)
        args = self.batch_args(resolve_contact=False)

        with mock.patch.object(semi, "run_once", return_value=(state, queue)):
            result = semi.build_batch_preview(args)

        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["send_ready"], 0)
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertFalse(packet["items"][0]["send_ready"])
        self.assertIn("resolution", packet["items"][0]["blocked_reason"])
        self.assertIn("do_not_send_because", packet["items"][0])

    def test_tiny_pilot_preset_caps_preview_to_one(self) -> None:
        state = {
            "summary": {"active_clients": 2},
            "clients": [
                {
                    **self.sample_state()["clients"][0],
                    "client_key": "name:ada",
                    "client_name": "Ada Lovelace",
                    "email": "ada@example.com",
                },
                {
                    **self.sample_state()["clients"][0],
                    "client_key": "name:grace",
                    "client_name": "Grace Hopper",
                    "email": "grace@example.com",
                },
            ],
        }
        queue = semi.build_action_queue(state)
        args = self.batch_args(batch_preset="tiny_pilot", batch_size=5, resolve_contact=False)

        with mock.patch.object(semi, "run_once", return_value=(state, queue)):
            result = semi.build_batch_preview(args)

        self.assertEqual(result["selected"], 1)
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertEqual(packet["batch_preset"], "tiny_pilot")
        self.assertEqual(packet["capped_size"], 1)

    def test_capped_ready_rollout_skips_unresolved_and_collects_ready_items(self) -> None:
        base_client = self.sample_state()["clients"][0]
        state = {
            "summary": {"active_clients": 3, "due_for_next_round": 3},
            "clients": [
                {**base_client, "client_key": "name:ada", "client_name": "Ada Lovelace", "email": "ada@example.com"},
                {**base_client, "client_key": "name:grace", "client_name": "Grace Hopper", "email": "grace@example.com"},
                {**base_client, "client_key": "name:katherine", "client_name": "Katherine Johnson", "email": "katherine@example.com"},
            ],
        }
        queue = semi.build_action_queue(state)
        args = self.batch_args(batch_preset=semi.READY_ROLLOUT_PRESET, batch_size=2, resolve_contact=True)
        resolutions = [
            {"ok": False, "contact": None, "error": "HighLevel contact was not found."},
            {"ok": True, "contact": {"id": "contact-grace", "firstName": "Grace", "email": "grace@example.com"}, "error": None},
            {"ok": True, "contact": {"id": "contact-katherine", "firstName": "Katherine", "email": "katherine@example.com"}, "error": None},
        ]

        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", side_effect=resolutions),
        ):
            result = semi.build_batch_preview(args)

        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["send_ready"], 2)
        self.assertEqual(result["skipped_candidates"], 1)
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertTrue(packet["ready_only"])
        self.assertEqual([item["client_name"] for item in packet["items"]], ["Grace Hopper", "Katherine Johnson"])
        self.assertEqual(packet["skipped_candidates"][0]["client_name"], "Ada Lovelace")
        self.assertTrue(all(item["send_ready"] for item in packet["items"]))

    def test_capped_ready_rollout_excludes_billing_risk_before_packet(self) -> None:
        base_client = self.sample_state()["clients"][0]
        state = {
            "summary": {"active_clients": 4, "due_for_next_round": 4},
            "clients": [
                {**base_client, "client_key": "name:ada", "client_name": "Ada Lovelace", "email": "ada@example.com"},
                {**base_client, "client_key": "name:grace", "client_name": "Grace Hopper", "email": "grace@example.com"},
                {**base_client, "client_key": "name:katherine", "client_name": "Katherine Johnson", "email": "katherine@example.com"},
                {**base_client, "client_key": "name:dorothy", "client_name": "Dorothy Vaughan", "email": "dorothy@example.com"},
            ],
        }
        with semi.BILLING_RISK_REVIEW_CSV.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["client_name", "review_bucket"])
            writer.writeheader()
            writer.writerow({"client_name": "Ada Lovelace", "review_bucket": "date_sensitive_next_7_days"})
            writer.writerow({"client_name": "Grace Hopper", "review_bucket": "standard_high_risk_review"})

        queue = semi.build_action_queue(state)
        args = self.batch_args(batch_preset=semi.READY_ROLLOUT_PRESET, batch_size=2, resolve_contact=True)
        resolutions = [
            {"ok": True, "contact": {"id": "contact-katherine", "firstName": "Katherine", "email": "katherine@example.com"}, "error": None},
            {"ok": True, "contact": {"id": "contact-dorothy", "firstName": "Dorothy", "email": "dorothy@example.com"}, "error": None},
        ]

        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", side_effect=resolutions) as resolver,
        ):
            result = semi.build_batch_preview(args)

        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["send_ready"], 2)
        self.assertEqual(result["skipped_candidates"], 2)
        self.assertEqual(resolver.call_count, 2)
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertEqual({item["client_name"] for item in packet["items"]}, {"Katherine Johnson", "Dorothy Vaughan"})
        self.assertEqual({item["client_name"] for item in packet["skipped_candidates"]}, {"Ada Lovelace", "Grace Hopper"})
        self.assertTrue(all("billing-risk review queue" in item["reason"] for item in packet["skipped_candidates"]))

    def test_capped_ready_rollout_excludes_prior_sent_receipts(self) -> None:
        base_client = self.sample_state()["clients"][0]
        state = {
            "summary": {"active_clients": 3, "due_for_next_round": 3},
            "clients": [
                {**base_client, "client_key": "name:karenthea", "client_name": "Karenthea Cameron *New", "email": "karenthea@example.com"},
                {**base_client, "client_key": "name:maurice", "client_name": "Maurice Bates", "email": "maurice@example.com"},
                {**base_client, "client_key": "name:dorothy", "client_name": "Dorothy Vaughan", "email": "dorothy@example.com"},
            ],
        }
        semi.BATCH_RECEIPT_DIR.mkdir(parents=True)
        (semi.BATCH_RECEIPT_DIR / "prior-result.json").write_text(
            json.dumps(
                {
                    "mode": "batch_result",
                    "batch_id": "prior-batch-1",
                    "sent": 1,
                    "results": [{"client_name": "Karenthea Cameron", "sent": True, "status": 201}],
                }
            ),
            encoding="utf-8",
        )
        queue = semi.build_action_queue(state)
        args = self.batch_args(batch_preset=semi.READY_ROLLOUT_PRESET, batch_size=2, resolve_contact=True)
        resolutions = [
            {"ok": True, "contact": {"id": "contact-maurice", "firstName": "Maurice", "email": "maurice@example.com"}, "error": None},
            {"ok": True, "contact": {"id": "contact-dorothy", "firstName": "Dorothy", "email": "dorothy@example.com"}, "error": None},
        ]

        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", side_effect=resolutions) as resolver,
        ):
            result = semi.build_batch_preview(args)

        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["send_ready"], 2)
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertEqual(resolver.call_count, 2)
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertEqual({item["client_name"] for item in packet["items"]}, {"Maurice Bates", "Dorothy Vaughan"})
        self.assertEqual(packet["skipped_candidates"][0]["client_name"], "Karenthea Cameron *New")
        self.assertIn("already sent in prior batch receipt", packet["skipped_candidates"][0]["reason"])

    def test_capped_ready_rollout_scans_past_blocked_front_of_queue(self) -> None:
        base_client = self.sample_state()["clients"][0]
        blocked_clients = [
            {
                **base_client,
                "client_key": f"name:a-billing-{idx:02d}",
                "client_name": f"A Billing {idx:02d}",
                "email": f"billing{idx:02d}@example.com",
            }
            for idx in range(35)
        ]
        ready_clients = [
            {**base_client, "client_key": "name:z-ready-one", "client_name": "Z Ready One", "email": "ready1@example.com"},
            {**base_client, "client_key": "name:z-ready-two", "client_name": "Z Ready Two", "email": "ready2@example.com"},
        ]
        state = {
            "summary": {"active_clients": len(blocked_clients) + len(ready_clients), "due_for_next_round": len(blocked_clients) + len(ready_clients)},
            "clients": blocked_clients + ready_clients,
        }
        with semi.BILLING_RISK_REVIEW_CSV.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["client_name", "review_bucket"])
            writer.writeheader()
            for client in blocked_clients:
                writer.writerow({"client_name": client["client_name"], "review_bucket": "standard_high_risk_review"})

        queue = semi.build_action_queue(state)
        args = self.batch_args(batch_preset=semi.READY_ROLLOUT_PRESET, batch_size=2, resolve_contact=True)
        resolutions = [
            {"ok": True, "contact": {"id": "contact-ready-1", "firstName": "Ready", "email": "ready1@example.com"}, "error": None},
            {"ok": True, "contact": {"id": "contact-ready-2", "firstName": "Ready", "email": "ready2@example.com"}, "error": None},
        ]

        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", side_effect=resolutions),
        ):
            result = semi.build_batch_preview(args)

        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["send_ready"], 2)
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.assertGreaterEqual(packet["selection"]["candidate_scan_limit"], 100)
        self.assertEqual([item["client_name"] for item in packet["items"]], ["Z Ready One", "Z Ready Two"])
        self.assertEqual(len(packet["skipped_candidates"]), 35)

    def test_batch_live_requires_approval(self) -> None:
        semi.BATCH_PACKET.parent.mkdir(parents=True, exist_ok=True)
        semi.BATCH_PACKET.write_text(
            json.dumps({"mode": "batch_preview", "batch_id": "batch-test", "channel": "Email", "items": []}) + "\n",
            encoding="utf-8",
        )
        result = semi.run_batch_live(self.batch_args(approved_batch_send=False))

        self.assertTrue(result["blocked"])
        self.assertIn("approved", result["reason"])

    def test_batch_live_sends_ready_items_and_writes_receipt(self) -> None:
        state = self.sample_state()
        queue = semi.build_action_queue(state)
        preview_args = self.batch_args(resolve_contact=True)
        resolved = {
            "ok": True,
            "contact": {"id": "highlevel-contact", "firstName": "Ada", "email": "ada@example.com"},
            "error": None,
        }
        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", return_value=resolved),
        ):
            semi.build_batch_preview(preview_args)

        os.environ["CREDIT_TRACKER_DRY_RUN"] = "false"
        packet = json.loads(semi.BATCH_PACKET.read_text(encoding="utf-8"))
        self.write_ready_owner_notice(packet)
        with (
            mock.patch.object(semi, "send_window_status", return_value=(True, "inside window")),
            mock.patch.object(semi, "send_reply", return_value={"sent": True, "status": 201, "body": "{}"}),
        ):
            result = semi.run_batch_live(self.batch_args(approved_batch_send=True))

        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["blocked_or_failed"], 0)
        self.assertTrue(Path(result["result_path"]).exists())
        self.assertTrue(Path(result["receipt_path"]).exists())

    def test_batch_live_sends_owner_notice_and_blocks_until_two_minute_window(self) -> None:
        state = self.sample_state()
        queue = semi.build_action_queue(state)
        preview_args = self.batch_args(resolve_contact=True)
        resolved = {
            "ok": True,
            "contact": {"id": "highlevel-contact", "firstName": "Ada", "email": "ada@example.com"},
            "error": None,
        }
        with (
            mock.patch.object(semi, "run_once", return_value=(state, queue)),
            mock.patch.object(semi, "resolve_contact", return_value=resolved),
        ):
            semi.build_batch_preview(preview_args)

        os.environ["CREDIT_TRACKER_DRY_RUN"] = "false"
        os.environ["FUNDZ_OWNER_NOTIFY_TARGET"] = "+18325551234"
        with (
            mock.patch.object(semi, "send_window_status", return_value=(True, "inside window")),
            mock.patch.object(semi, "send_owner_notice_text", return_value={"returncode": 0, "stdout": "ok", "stderr": "", "dry_run": False}) as send_notice,
            mock.patch.object(semi, "send_reply") as send_reply,
        ):
            result = semi.run_batch_live(self.batch_args(approved_batch_send=True))

        self.assertTrue(result["blocked"])
        self.assertIn("Owner text notice sent", result["reason"])
        send_notice.assert_called_once()
        send_reply.assert_not_called()

    def test_send_window_blocks_weekend_live_sends(self) -> None:
        allowed, reason = semi.send_window_status(datetime(2026, 5, 9, 12, 0, 0))

        self.assertFalse(allowed)
        self.assertIn("weekend", reason)

    def test_live_pilot_blocks_outside_send_window(self) -> None:
        args = self.pilot_args(pilot_dry_run=False, pilot_live=True, approved_live_send=True)
        os.environ["CREDIT_TRACKER_DRY_RUN"] = "false"
        os.environ["CREDIT_TRACKER_REPLY_URL"] = "https://example.test/reply"
        os.environ["CREDIT_TRACKER_API_TOKEN"] = "token"

        with mock.patch.object(semi, "send_window_status", return_value=(False, "outside window")):
            result = semi.run_pilot(args)

        self.assertFalse(result["sent"])
        self.assertTrue(result["blocked"])
        self.assertIn("outside window", result["reason"])


if __name__ == "__main__":
    unittest.main()
