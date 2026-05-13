import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scripts.fundz_highlevel_inbox_poller as poller


class FundzHighLevelInboxPollerTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "CREDIT_TRACKER_LOCATION_ID": "loc-123",
                "CREDIT_TRACKER_DRY_RUN": "true",
                "HIGHLEVEL_INBOX_LAST_DIRECTION": "inbound",
            },
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    def test_build_conversation_search_url(self):
        url = poller.build_conversation_search_url("loc-123", 10, "unread")

        self.assertIn("locationId=loc-123", url)
        self.assertIn("limit=10", url)
        self.assertIn("status=unread", url)
        self.assertIn("lastMessageDirection=inbound", url)

    def test_normalize_conversation_to_bridge_payload(self):
        payload = poller.normalize_conversation(
            {
                "id": "conv-1",
                "contactId": "contact-1",
                "lastMessageId": "msg-1",
                "lastMessageType": "TYPE_SMS",
                "lastMessageBody": "Any update on my file?",
                "lastMessageDate": "2026-05-03T20:00:00.000Z",
                "contact": {"firstName": "Erika", "lastName": "Jordan", "phone": "+18324137108"},
            },
            "loc-123",
        )

        self.assertEqual(payload["message_id"], "msg-1")
        self.assertEqual(payload["conversation_id"], "conv-1")
        self.assertEqual(payload["contact_id"], "contact-1")
        self.assertEqual(payload["messageType"], "SMS")
        self.assertEqual(payload["first_name"], "Erika")
        self.assertEqual(payload["message"], "Any update on my file?")

    def test_normalize_app_message_conversation(self):
        payload = poller.normalize_conversation(
            {
                "id": "conv-app",
                "contactId": "contact-app",
                "lastMessageId": "msg-app",
                "lastMessageType": "TYPE_APP_MESSAGE",
                "lastMessageBody": "Can I talk with FUNDz in the Credit Tracker app?",
                "lastMessageDate": "2026-05-03T20:00:00.000Z",
                "contact": {"firstName": "Erika", "lastName": "Jordan"},
            },
            "loc-123",
        )

        self.assertEqual(payload["messageType"], "App_Message")
        self.assertEqual(payload["channel"], "credit-tracker")

    def test_normalize_whatsapp_is_not_app_message(self):
        self.assertEqual(poller.normalize_message_type("TYPE_WHATSAPP"), "WhatsApp")
        self.assertEqual(poller.normalize_message_type("WhatsApp"), "WhatsApp")

    def test_poll_once_previews_without_live_send(self):
        response = {
            "conversations": [
                {
                    "id": "conv-1",
                    "contactId": "contact-1",
                    "lastMessageId": "msg-preview",
                    "lastMessageType": "TYPE_SMS",
                    "lastMessageBody": "Any update on my file?",
                    "lastMessageDirection": "inbound",
                }
            ]
        }

        with (
            mock.patch.object(poller, "load_env_file"),
            mock.patch.object(poller, "request_get", return_value=(200, __import__("json").dumps(response))),
            mock.patch.object(poller, "has_seen", return_value=False),
            mock.patch.object(poller, "write_poll_log"),
            mock.patch.object(poller, "write_reply_queue"),
            mock.patch.object(poller, "draft_bridge_reply", return_value="Hi, quick FUNDz update."),
            mock.patch.object(poller, "send_reply") as send_reply,
        ):
            summary = poller.poll_once(limit=1, status="unread", live=False)

        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(summary["preview"], 1)
        self.assertEqual(summary["sent"], 0)
        send_reply.assert_not_called()

    def test_empty_message_body_does_not_enter_reply_queue(self):
        response = {
            "conversations": [
                {
                    "id": "conv-empty",
                    "contactId": "contact-empty",
                    "lastMessageId": "msg-empty",
                    "lastMessageType": "TYPE_SMS",
                    "lastMessageBody": "",
                    "lastMessageDirection": "inbound",
                }
            ]
        }

        with (
            mock.patch.object(poller, "load_env_file"),
            mock.patch.object(poller, "request_get", return_value=(200, __import__("json").dumps(response))),
            mock.patch.object(poller, "has_seen", return_value=False),
            mock.patch.object(poller, "write_poll_log"),
            mock.patch.object(poller, "write_reply_queue") as write_reply_queue,
            mock.patch.object(poller, "mark_seen"),
        ):
            summary = poller.poll_once(limit=1, status="unread", live=False)

        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(summary["handled"], 0)
        self.assertEqual(summary["ignored"], 1)
        write_reply_queue.assert_not_called()

    def test_write_reply_queue_dedupes_message_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = {
                "message_id": "msg-1",
                "contact_id": "contact-1",
                "conversation_id": "conv-1",
                "name": "Erika Jordan",
                "message": "Had my credit score changed?",
            }
            classification = poller.classify_inbound_reply(payload["message"])

            with (
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "REPLY_QUEUE", base / "classified.jsonl"),
                mock.patch.object(poller, "CUSTOMER_MEMORY", base / "customer-memory.jsonl"),
                mock.patch.object(poller, "CUSTOMER_SUMMARIES", base / "customer-summaries.json"),
            ):
                poller.write_reply_queue(payload, classification)
                poller.write_reply_queue(payload, classification)

            rows = (base / "classified.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)

    def test_classifies_billing_reply_for_owner_review(self):
        classification = poller.classify_inbound_reply("Why was my card charged twice?")

        self.assertIn("billing", classification["labels"])
        self.assertTrue(classification["needs_brandon_reply"])
        self.assertTrue(classification["needs_follow_up"])
        self.assertEqual(classification["recommended_response_mode"], "owner_review_required")
        self.assertEqual(classification["safe_auto_reply_draft"], "")

    def test_classifies_simple_question_with_safe_draft(self):
        classification = poller.classify_inbound_reply("Any update on my file?")

        self.assertIn("question", classification["labels"])
        self.assertFalse(classification["needs_brandon_reply"])
        self.assertIn("right answer", classification["safe_auto_reply_draft"])

    def test_classifies_score_concern_as_verified_context_needed(self):
        classification = poller.classify_inbound_reply("My credit score dropped. What happened?")

        self.assertIn("score_concern", classification["labels"])
        self.assertNotIn("app_access", classification["labels"])
        self.assertFalse(classification["needs_brandon_reply"])
        self.assertTrue(classification["needs_follow_up"])
        self.assertEqual(classification["recommended_response_mode"], "reassure_with_verified_facts")

    def test_app_access_classifier_uses_whole_words(self):
        happened = poller.classify_inbound_reply("What happened to my credit score?")
        app_help = poller.classify_inbound_reply("I cannot log into the app.")

        self.assertNotIn("app_access", happened["labels"])
        self.assertIn("app_access", app_help["labels"])

    def test_app_portal_signal_uses_whole_words(self):
        regular_sms = {
            "messageType": "SMS",
            "source_file": "highlevel-happened-export.csv",
        }
        app_message = {
            "messageType": "TYPE_APP_MESSAGE",
            "source": "highlevel-poller",
        }

        self.assertEqual(poller.app_portal_signals(regular_sms), [])
        self.assertIn("app_message", poller.app_portal_signals(app_message))

    def test_write_reply_queue_updates_customer_memory_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = {
                "message_id": "msg-memory-1",
                "contact_id": "contact-memory-1",
                "conversation_id": "conv-memory-1",
                "name": "Erika Jordan",
                "message": "My credit score dropped. What happened?",
            }
            classification = poller.classify_inbound_reply(payload["message"])

            with (
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "REPLY_QUEUE", base / "classified.jsonl"),
                mock.patch.object(poller, "CUSTOMER_MEMORY", base / "customer-memory.jsonl"),
                mock.patch.object(poller, "CUSTOMER_SUMMARIES", base / "customer-summaries.json"),
            ):
                poller.write_reply_queue(payload, classification)

            memory_lines = (base / "customer-memory.jsonl").read_text(encoding="utf-8").splitlines()
            summaries = __import__("json").loads((base / "customer-summaries.json").read_text(encoding="utf-8"))

        self.assertEqual(len(memory_lines), 1)
        self.assertIn("contact:contact-memory-1", summaries)
        self.assertIn("score_concern", summaries["contact:contact-memory-1"]["recent_topics"])
        self.assertTrue(summaries["contact:contact-memory-1"]["open_follow_up"])

    def test_live_holds_proof_dependent_replies(self):
        billing = poller.classify_inbound_reply("Why was my card charged twice?")
        score = poller.classify_inbound_reply("My credit score dropped. What happened?")
        app_access = poller.classify_inbound_reply("I cannot log into the Credit Tracker app.")

        self.assertIn("owner review required", poller.live_reply_hold_reason(billing))
        self.assertIn("verified customer-service context", poller.live_reply_hold_reason(score))
        self.assertIn("verified customer-service context", poller.live_reply_hold_reason(app_access))

    def test_app_portal_payload_writes_local_proof_before_handle_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = {
                "message_id": "msg-app-proof-1",
                "conversation_id": "conv-app-proof-1",
                "name": "Brandon Jordan",
                "message": "hey",
                "messageType": "App_Message",
                "direction": "inbound",
                "lastMessageDate": "2026-05-13T09:10:00.000Z",
            }

            with (
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "APP_PORTAL_PROOF_JSONL", base / "app-proof.jsonl"),
                mock.patch.object(poller, "APP_PORTAL_PROOF_MD", base / "app-proof.md"),
                mock.patch.object(poller, "has_seen", return_value=False),
                mock.patch.object(poller, "write_poll_log"),
                mock.patch.object(poller, "mark_seen"),
                mock.patch.object(poller, "draft_bridge_reply") as draft_bridge_reply,
                mock.patch.object(poller, "send_reply") as send_reply,
            ):
                result = poller.handle_payload(payload, live=False)

            proof = __import__("json").loads((base / "app-proof.jsonl").read_text(encoding="utf-8").splitlines()[0])
            proof_markdown = (base / "app-proof.md").read_text(encoding="utf-8")

        self.assertFalse(result["handled"])
        self.assertEqual(result["reason"], "missing contact id")
        self.assertEqual(proof["message_id"], "msg-app-proof-1")
        self.assertEqual(proof["proof_status"], "captured_from_highlevel_poll_no_send")
        self.assertIn("app", proof["signals"])
        self.assertIn("No replies, sends", proof_markdown)
        draft_bridge_reply.assert_not_called()
        send_reply.assert_not_called()

    def test_manual_import_writes_app_portal_proof_without_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            import_dir = base / "imports"
            import_dir.mkdir()
            source = import_dir / "credit-tracker-app-export.csv"
            source.write_text(
                "contact,last message,date,direction,contact_id,conversation_id,lastMessageType\n"
                "Brandon Jordan,hey,2026-05-13T09:10:00Z,inbound,contact-app,conv-app,TYPE_APP_MESSAGE\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(poller, "MANUAL_QUEUE_CSV", base / "manual.csv"),
                mock.patch.object(poller, "MANUAL_QUEUE_MD", base / "manual.md"),
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "APP_PORTAL_PROOF_JSONL", base / "app-proof.jsonl"),
                mock.patch.object(poller, "APP_PORTAL_PROOF_MD", base / "app-proof.md"),
                mock.patch.object(poller, "load_env_file"),
                mock.patch.object(poller, "write_poll_log"),
                mock.patch.object(poller, "write_reply_queue"),
                mock.patch.object(poller, "send_reply") as send_reply,
            ):
                summary = poller.poll_manual_imports(import_dir)

            proof = __import__("json").loads((base / "app-proof.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(summary["sent"], 0)
        self.assertEqual(proof["message_type"], "App_Message")
        self.assertEqual(proof["proof_status"], "captured_from_manual_import_no_send")
        send_reply.assert_not_called()

    def test_live_hold_does_not_send_sensitive_reply(self):
        payload = {
            "message_id": "msg-hold-1",
            "contact_id": "contact-1",
            "conversation_id": "conv-1",
            "message": "My credit score dropped. What happened?",
            "messageType": "SMS",
            "phone": "+15555550123",
        }

        with (
            mock.patch.object(poller, "has_seen", return_value=False),
            mock.patch.object(poller, "write_reply_queue"),
            mock.patch.object(poller, "write_poll_log") as write_poll_log,
            mock.patch.object(poller, "draft_bridge_reply", return_value="Safe local reply."),
            mock.patch.object(poller, "send_reply") as send_reply,
            mock.patch.object(poller, "mark_seen") as mark_seen,
        ):
            result = poller.handle_payload(payload, live=True)

        self.assertTrue(result["held"])
        self.assertFalse(result["sent"])
        send_reply.assert_not_called()
        mark_seen.assert_called_once_with("msg-hold-1")
        self.assertTrue(any(call.args[0] == "reply_hold" for call in write_poll_log.call_args_list))

    def test_live_hold_score_sms_does_not_write_app_portal_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = {
                "message_id": "msg-hold-1",
                "contact_id": "contact-1",
                "conversation_id": "conv-1",
                "message": "My credit score dropped. What happened?",
                "messageType": "SMS",
                "phone": "+15555550123",
            }

            with (
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "APP_PORTAL_PROOF_JSONL", base / "app-proof.jsonl"),
                mock.patch.object(poller, "APP_PORTAL_PROOF_MD", base / "app-proof.md"),
                mock.patch.object(poller, "REPLY_QUEUE", base / "classified.jsonl"),
                mock.patch.object(poller, "CUSTOMER_MEMORY", base / "customer-memory.jsonl"),
                mock.patch.object(poller, "CUSTOMER_SUMMARIES", base / "customer-summaries.json"),
                mock.patch.object(poller, "has_seen", return_value=False),
                mock.patch.object(poller, "write_poll_log"),
                mock.patch.object(poller, "draft_bridge_reply", return_value="Safe local reply."),
                mock.patch.object(poller, "send_reply"),
                mock.patch.object(poller, "mark_seen"),
            ):
                result = poller.handle_payload(payload, live=True)

        self.assertTrue(result["held"])
        self.assertFalse((base / "app-proof.jsonl").exists())

    def test_successful_live_reply_writes_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = {
                "message_id": "msg-sent-1",
                "contact_id": "contact-1",
                "conversation_id": "conv-1",
                "name": "Ada Lovelace",
                "message": "Thanks!",
                "messageType": "SMS",
                "phone": "+15555550123",
            }
            send_result = {"sent": True, "status": 201}

            with (
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "REPLY_QUEUE", base / "classified.jsonl"),
                mock.patch.object(poller, "CUSTOMER_MEMORY", base / "customer-memory.jsonl"),
                mock.patch.object(poller, "CUSTOMER_SUMMARIES", base / "customer-summaries.json"),
                mock.patch.object(poller, "REPLY_RECEIPTS", base / "reply-receipts.jsonl"),
                mock.patch.object(poller, "has_seen", return_value=False),
                mock.patch.object(poller, "write_poll_log"),
                mock.patch.object(poller, "draft_bridge_reply", return_value="Received. Thank you."),
                mock.patch.object(poller, "send_reply", return_value=send_result),
                mock.patch.object(poller, "mark_seen"),
                mock.patch.object(poller, "log_event"),
            ):
                result = poller.handle_payload(payload, live=True)

            receipt = __import__("json").loads((base / "reply-receipts.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertTrue(result["sent"])
        self.assertEqual(receipt["message_id"], "msg-sent-1")
        self.assertTrue(receipt["sent"])
        self.assertEqual(receipt["status"], 201)

    def test_live_refuses_when_dry_run_enabled(self):
        with mock.patch.object(poller, "load_env_file"):
            with self.assertRaises(SystemExit):
                poller.poll_once(limit=1, status="unread", live=True)

    def test_manual_import_classifies_export_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            import_dir = base / "imports"
            import_dir.mkdir()
            source = import_dir / "highlevel-export.csv"
            source.write_text(
                "contact,phone,last message,date,direction,contact_id,conversation_id\n"
                "Ada Lovelace,+15555550123,Any update on my file?,2026-05-06,inbound,contact-1,conv-1\n"
                "Grace Hopper,+15555550124,Why was my card charged twice?,2026-05-06,inbound,contact-2,conv-2\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(poller, "MANUAL_QUEUE_CSV", base / "manual.csv"),
                mock.patch.object(poller, "MANUAL_QUEUE_MD", base / "manual.md"),
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "load_env_file"),
                mock.patch.object(poller, "write_poll_log"),
                mock.patch.object(poller, "write_reply_queue"),
                mock.patch.object(poller, "send_reply") as send_reply,
            ):
                summary = poller.poll_manual_imports(import_dir)

            self.assertEqual(summary["imported"], 2)
            self.assertEqual(summary["needs_reply"], 1)
            self.assertEqual(summary["needs_brandon"], 1)
            self.assertEqual(summary["sent"], 0)
            self.assertIn("Ada Lovelace", (base / "manual.csv").read_text(encoding="utf-8"))
            send_reply.assert_not_called()

    def test_manual_import_does_not_queue_no_action_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            import_dir = base / "imports"
            import_dir.mkdir()
            source = import_dir / "highlevel-export.csv"
            source.write_text(
                "contact,last message,date,direction,contact_id,conversation_id\n"
                "Ada Lovelace,Thanks!,2026-05-06,inbound,contact-1,conv-1\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(poller, "MANUAL_QUEUE_CSV", base / "manual.csv"),
                mock.patch.object(poller, "MANUAL_QUEUE_MD", base / "manual.md"),
                mock.patch.object(poller, "STATE_DIR", base),
                mock.patch.object(poller, "load_env_file"),
                mock.patch.object(poller, "write_poll_log"),
                mock.patch.object(poller, "write_reply_queue") as write_reply_queue,
            ):
                summary = poller.poll_manual_imports(import_dir)

        self.assertEqual(summary["imported"], 1)
        self.assertEqual(summary["review"], 1)
        write_reply_queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
