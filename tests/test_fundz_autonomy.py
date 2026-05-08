from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_autonomy_daemon as autonomy
import fundz_credit_tracker_bridge as bridge


class FakeResponse:
    def __init__(self, status: int, payload: dict | str):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


class FundzAutonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.autonomy_dir = self.base / "autonomy"
        self.bridge_dir = self.base / "bridge"
        self.env_patch = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.path_patches = [
            mock.patch.object(autonomy, "AUTONOMY_DIR", self.autonomy_dir),
            mock.patch.object(autonomy, "QUARANTINE_DIR", self.autonomy_dir / "quarantine"),
            mock.patch.object(autonomy, "PROPOSAL_DIR", self.autonomy_dir / "proposals"),
            mock.patch.object(autonomy, "AUTONOMY_LOG", self.autonomy_dir / "autonomy-events.jsonl"),
            mock.patch.object(autonomy, "BRIDGE_LOG", self.bridge_dir / "credit-tracker-bridge.jsonl"),
            mock.patch.object(autonomy, "SEEN_EVENTS", self.bridge_dir / "seen-events.txt"),
            mock.patch.object(bridge, "LOG_DIR", self.bridge_dir),
            mock.patch.object(bridge, "STATE_DIR", self.bridge_dir),
            mock.patch.object(bridge, "EVENT_LOG", self.bridge_dir / "credit-tracker-bridge.jsonl"),
            mock.patch.object(bridge, "SEEN_EVENTS", self.bridge_dir / "seen-events.txt"),
        ]
        for patcher in self.path_patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.path_patches):
            patcher.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def valid_payload(self) -> dict:
        return {
            "event_id": "evt-1",
            "channel": "credit-tracker",
            "direction": "inbound",
            "first_name": "Ada",
            "contact_id": "contact-1",
            "conversation_id": "conversation-1",
            "phone": "+15555550123",
            "message": "Can I get an update?",
            "status": "active",
        }

    def test_redacts_secrets_email_and_phone(self) -> None:
        redacted = autonomy.redact_sensitive(
            {
                "Authorization": "Bearer secret-token",
                "email": "client@example.com",
                "phone": "+1 (555) 555-0199",
                "nested": {"refresh_token": "keep-private"},
            }
        )

        self.assertEqual(redacted["Authorization"], "[redacted]")
        self.assertEqual(redacted["nested"]["refresh_token"], "[redacted]")
        self.assertEqual(redacted["email"], "[redacted-email]")
        self.assertEqual(redacted["phone"], "[redacted-phone:***0199]")

    def test_classifies_retry_failures(self) -> None:
        self.assertEqual(autonomy.classify_send_failure(401).category, "config issue")
        self.assertEqual(autonomy.classify_send_failure(422).category, "payload mapping issue")
        self.assertEqual(autonomy.classify_send_failure(503).category, "provider/API issue")
        self.assertEqual(autonomy.classify_send_failure(error="timed out").category, "provider/API issue")

    def test_quarantine_writes_redacted_payload(self) -> None:
        path = autonomy.quarantine_event(
            "missing contact id",
            {"email": "client@example.com", "api_token": "secret", "phone": "555-555-0199"},
        )

        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["payload"]["api_token"], "[redacted]")
        self.assertEqual(saved["payload"]["email"], "[redacted-email]")
        self.assertEqual(saved["payload"]["phone"], "[redacted-phone:***0199]")

    def test_duplicate_event_tracking_uses_seen_file(self) -> None:
        self.assertFalse(bridge.has_seen("event:abc"))
        bridge.mark_seen("event:abc")
        self.assertTrue(bridge.has_seen("event:abc"))

    def test_bridge_blocks_unsafe_payloads(self) -> None:
        os.environ["CREDIT_TRACKER_REQUIRE_CHANNEL"] = "false"
        payload = self.valid_payload()
        payload["dnd"] = "true"
        self.assertEqual(bridge.should_auto_reply(payload), (False, "contact is marked do-not-disturb"))

        payload = self.valid_payload()
        payload.pop("contact_id")
        self.assertEqual(bridge.should_auto_reply(payload), (False, "missing contact id"))

        payload = self.valid_payload()
        payload["phone"] = "bad"
        self.assertEqual(bridge.should_auto_reply(payload), (False, "missing valid SMS-capable phone number"))

    def test_valid_dry_run_reply_does_not_send_live(self) -> None:
        os.environ["CREDIT_TRACKER_DRY_RUN"] = "true"
        os.environ["CREDIT_TRACKER_REQUIRE_CHANNEL"] = "false"
        payload = self.valid_payload()
        allowed, reason = bridge.should_auto_reply(payload)
        self.assertTrue(allowed, reason)

        result = bridge.send_reply(payload, bridge.draft_reply(payload))

        self.assertFalse(result["sent"])
        self.assertTrue(result["dry_run"])
        self.assertTrue(bridge.EVENT_LOG.exists())

    def test_webhook_probe_flag_is_test_only(self) -> None:
        payload = self.valid_payload()
        payload["fundz_test_only"] = True

        self.assertTrue(bridge.is_test_only_payload(payload))
        self.assertTrue(bridge.is_test_only_payload(self.valid_payload(), "true"))

    def test_named_update_answers_from_local_state_immediately(self) -> None:
        state = {
            "clients": [
                {
                    "client_key": "name:jean-miller",
                    "client_name": "Jean Miller",
                    "is_active_client": True,
                    "status": "In Dispute",
                    "stage_in_process": "Round 2 Sent (05/01/26)",
                    "next_import": "29 Days",
                    "assigned_to": "Brandon Jordan",
                    "onboarding": "75%",
                    "dispute_items": {
                        "all_items": 63,
                        "in_dispute_count": 56,
                        "deleted_count": 7,
                        "repaired_count": 0,
                    },
                    "send_history": {"email_count": 2, "sms_count": 16},
                    "operational_flags": ["in_dispute", "onboarding_incomplete"],
                    "recommended_next_action": "Finish onboarding requirements before automated follow-up.",
                },
                {
                    "client_key": "name:ada-lovelace",
                    "client_name": "Ada Lovelace",
                    "is_active_client": True,
                    "status": "Due For Next Round",
                    "stage_in_process": "Round 2 Sent (05/01/26)",
                    "next_import": "0 Days",
                    "assigned_to": "Brandon Jordan",
                    "onboarding": "100%",
                    "dispute_items": {
                        "all_items": 10,
                        "in_dispute_count": 7,
                        "deleted_count": 3,
                        "repaired_count": 0,
                    },
                    "send_history": {"email_count": 2, "sms_count": 1},
                    "operational_flags": ["due_for_next_round"],
                    "recommended_next_action": "Review next-round readiness and prepare the next dispute round.",
                },
                {
                    "client_key": "name:dekosha-robinson",
                    "client_name": "DeKosha Robinson",
                    "is_active_client": True,
                    "status": "In Dispute",
                    "stage_in_process": "Round 1 Sent (04/07/26)",
                    "next_import": "8 Days",
                    "assigned_to": "Brandon Jordan",
                    "onboarding": "100%",
                    "dispute_items": {
                        "all_items": 32,
                        "in_dispute_count": 32,
                        "deleted_count": 0,
                        "repaired_count": 0,
                    },
                    "send_history": {"email_count": 0, "sms_count": 5},
                    "operational_flags": ["in_dispute"],
                    "recommended_next_action": "Monitor Round 1; next import is in 8 day(s).",
                },
                {
                    "client_key": "name:brittany-preston",
                    "client_name": "Brittany Preston",
                    "is_active_client": True,
                    "status": "Due For Next Round",
                    "stage_in_process": "Round 8 sent (04/17/26)",
                    "next_import": "15 Days",
                    "assigned_to": "Dispute Team",
                    "onboarding": "75%",
                    "dispute_items": {
                        "all_items": 105,
                        "in_dispute_count": 15,
                        "deleted_count": 90,
                        "repaired_count": 0,
                    },
                    "send_history": {"email_count": 0, "sms_count": 4},
                    "operational_flags": ["due_for_next_round", "onboarding_incomplete"],
                    "recommended_next_action": "Review next-round readiness and prepare the next dispute round.",
                }
            ]
        }

        cases = [
            ("Give me a update on Jean Miller", "Jean Miller", "In Dispute", "Round 2 Sent", "63 total, 56 in dispute, 7 deleted"),
            ("Give me an update on Ada Lovelace", "Ada Lovelace", "Due For Next Round", "Round 2 Sent", "10 total, 7 in dispute, 3 deleted"),
            ("What's an update on the dekosha Robinson?", "DeKosha Robinson", "In Dispute", "Round 1 Sent", "32 total, 32 in dispute, 0 deleted"),
            ("What about an update on Brittany Preston?", "Brittany Preston", "Due For Next Round", "Round 8 sent", "105 total, 15 in dispute, 90 deleted"),
        ]
        for message, name, status, stage, dispute_counts in cases:
            matches = [client for client in state["clients"] if client["client_name"] == name]
            with self.subTest(name=name), mock.patch.object(bridge, "stored_client_matches", return_value=matches):
                payload = self.valid_payload()
                payload["message"] = message
                reply = bridge.draft_bridge_reply(payload)

            self.assertIn(f"latest FUNDz update for {name}", reply)
            self.assertIn(status, reply)
            self.assertIn(stage, reply)
            self.assertIn(dispute_counts, reply)
            self.assertNotIn("I don't have", reply)
            self.assertNotIn("get back", reply.lower())
            self.assertNotIn("shortly", reply.lower())

    def test_email_template_can_render_html_and_subject(self) -> None:
        os.environ["CREDIT_TRACKER_OUTBOUND_TEMPLATE"] = json.dumps(
            {
                "type": "{message_type}",
                "contactId": "{contact_id}",
                "subject": "{email_subject}",
                "html": "<p>{message_html}</p>",
            }
        )
        payload = self.valid_payload()
        payload.update(
            {
                "messageType": "Email",
                "email": "client@example.com",
                "email_subject": "Pilot subject",
            }
        )

        outbound = bridge.build_outbound_payload(payload, "Line 1\nLine <2>")

        self.assertEqual(outbound["type"], "Email")
        self.assertEqual(outbound["subject"], "Pilot subject")
        self.assertEqual(outbound["html"], "<p>Line 1<br>Line &lt;2&gt;</p>")

    def test_outbound_headers_include_integration_user_agent(self) -> None:
        os.environ["CREDIT_TRACKER_API_TOKEN"] = "token"

        headers = bridge.outbound_headers()

        self.assertEqual(headers["User-Agent"], bridge.DEFAULT_USER_AGENT)
        self.assertEqual(headers["Authorization"], "Bearer token")

    def test_token_refresh_retry_path(self) -> None:
        os.environ.update(
            {
                "CREDIT_TRACKER_DRY_RUN": "false",
                "CREDIT_TRACKER_REPLY_URL": "https://example.test/reply",
                "CREDIT_TRACKER_API_TOKEN": "expired",
                "CREDIT_TRACKER_REFRESH_TOKEN": "refresh",
                "CREDIT_TRACKER_FIREBASE_API_KEY": "firebase-key",
                "FUNDZ_AUTONOMY_RETRY_LIMIT": "2",
            }
        )
        first_failure = urllib.error.HTTPError(
            "https://example.test/reply",
            401,
            "Unauthorized",
            {},
            None,
        )
        first_failure.fp = mock.Mock()
        first_failure.fp.read.return_value = b"Invalid JWT"

        calls: list[str] = []

        def fake_urlopen(request, timeout=0):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise first_failure
            if "securetoken.googleapis.com" in request.full_url:
                return FakeResponse(200, {"access_token": "fresh-token", "expires_in": "3600"})
            return FakeResponse(200, {"ok": True})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = bridge.send_reply(self.valid_payload(), "Safe reply.")

        self.assertTrue(result["sent"])
        self.assertTrue(result["retried"])
        self.assertIn("securetoken.googleapis.com", calls[1])

    def test_cloudflare_signature_block_falls_back_to_curl_transport(self) -> None:
        os.environ.update(
            {
                "CREDIT_TRACKER_DRY_RUN": "false",
                "CREDIT_TRACKER_REPLY_URL": "https://example.test/reply",
                "CREDIT_TRACKER_API_TOKEN": "token",
                "CREDIT_TRACKER_HTTP_TRANSPORT": "auto",
                "FUNDZ_AUTONOMY_RETRY_LIMIT": "0",
            }
        )
        fake_completed = mock.Mock()
        fake_completed.returncode = 0
        fake_completed.stdout = '{"ok":true}\n200'
        fake_completed.stderr = ""

        with (
            mock.patch.object(
                bridge,
                "post_json_urllib",
                side_effect=bridge.OutboundHTTPError(
                    403,
                    '{"error_name":"browser_signature_banned","cloudflare_error":true}',
                    "urllib",
                ),
            ),
            mock.patch("subprocess.run", return_value=fake_completed) as run_mock,
        ):
            result = bridge.send_reply(self.valid_payload(), "Safe reply.")

        self.assertTrue(result["sent"])
        self.assertEqual(result["transport"], "curl")
        self.assertTrue(run_mock.called)

    def test_risky_language_and_proposal_generation(self) -> None:
        hits = autonomy.risky_language_hits("We guarantee a deletion and score increase.")
        self.assertIn("guarantee", hits)

        proposal = autonomy.write_proposal(
            "Repeated bridge failures need review",
            autonomy.classify_send_failure(503),
            [{"status": 503, "body": "temporarily unavailable"}],
        )

        text = proposal.read_text(encoding="utf-8")
        self.assertIn("Human review is required", text)
        self.assertIn("provider/API issue", text)


if __name__ == "__main__":
    unittest.main()
