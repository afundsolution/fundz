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
            ):
                poller.write_reply_queue(payload, classification)
                poller.write_reply_queue(payload, classification)

            rows = (base / "classified.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)

    def test_classifies_billing_reply_for_owner_review(self):
        classification = poller.classify_inbound_reply("Why was my card charged twice?")

        self.assertIn("billing", classification["labels"])
        self.assertTrue(classification["needs_brandon_reply"])
        self.assertEqual(classification["safe_auto_reply_draft"], "")

    def test_classifies_simple_question_with_safe_draft(self):
        classification = poller.classify_inbound_reply("Any update on my file?")

        self.assertIn("question", classification["labels"])
        self.assertFalse(classification["needs_brandon_reply"])
        self.assertIn("reviewing", classification["safe_auto_reply_draft"])

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


if __name__ == "__main__":
    unittest.main()
