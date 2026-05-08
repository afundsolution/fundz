from __future__ import annotations

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

import fundz_imessage_fallback as fallback


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class FundzIMessageFallbackTests(unittest.TestCase):
    def test_strips_openclaw_metadata(self) -> None:
        text = """Conversation info (untrusted metadata):
```json
{"message_id":"1186","sender_id":"+13466429919"}
```

Sender (untrusted metadata):
```json
{"label":"+13466429919"}
```

Can I get an update on Dedrick?"""

        self.assertEqual(fallback.strip_metadata(text), "Can I get an update on Dedrick?")
        self.assertEqual(
            fallback.metadata_json(text, "Conversation info (untrusted metadata):")["sender_id"],
            "+13466429919",
        )

    def test_client_query_supports_single_first_name(self) -> None:
        self.assertEqual(fallback.client_query_from_message("Can I get an update on Dedrick?"), "Dedrick")
        self.assertEqual(fallback.client_query_from_message("status for DeKosha Robinson"), "DeKosha Robinson")

    def test_detects_failed_openclaw_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sessions = base / "sessions"
            sessions.mkdir()
            session_file = sessions / "session.jsonl"
            index = sessions / "sessions.json"
            index.write_text(
                json.dumps(
                    {
                        "agent:fundz:imessage:direct:+13466429919": {
                            "sessionKey": "agent:fundz:imessage:direct:+13466429919",
                            "sessionFile": str(session_file),
                        }
                    }
                ),
                encoding="utf-8",
            )
            write_jsonl(
                session_file,
                [
                    {
                        "type": "message",
                        "id": "u1",
                        "timestamp": "2026-05-06T20:28:06+00:00",
                        "message": {
                            "role": "user",
                            "id": "msg-user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Conversation info (untrusted metadata):\n```json\n{\"message_id\":\"1186\",\"sender_id\":\"+13466429919\"}\n```\n\nCan I get an update on Dedrick?",
                                }
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "id": "a1",
                        "timestamp": "2026-05-06T20:28:07+00:00",
                        "message": {
                            "role": "assistant",
                            "stopReason": "error",
                            "errorMessage": "402 Insufficient credits",
                        },
                    },
                ],
            )

            with mock.patch.object(fallback, "OPENCLAW_SESSIONS_INDEX", index):
                candidates = fallback.fallback_candidates(sessions_dir=sessions, since_minutes=10_000)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].sender, "+13466429919")
        self.assertEqual(candidates[0].message, "Can I get an update on Dedrick?")

    def test_new_session_prompt_maps_to_new_command(self) -> None:
        message = {
            "id": "m1",
            "content": [
                {
                    "type": "text",
                    "text": "A new session was started via /new or /reset. Current time: now",
                }
            ],
        }

        text, _, _ = fallback.user_text_and_sender(message, "+13466429919")

        self.assertEqual(text, "/new")

    def test_run_fallback_blocks_non_owner_sender(self) -> None:
        candidate = fallback.FallbackCandidate(
            key="bad",
            sender="+15550001111",
            message="update on Dedrick",
            session_file=Path("/tmp/session.jsonl"),
            user_message_id="1",
            error="402",
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(fallback, "PROCESSED_PATH", Path(tmp) / "processed.json"),
            mock.patch.object(fallback, "RECEIPT_PATH", Path(tmp) / "receipts.jsonl"),
            mock.patch.object(fallback, "fallback_candidates", return_value=[candidate]),
            mock.patch.object(fallback, "load_env_file"),
            mock.patch.object(fallback, "sender_allowed", return_value=(False, "sender is not owner-allowlisted")),
            mock.patch.object(fallback, "build_reply") as build_reply,
        ):
            rows = fallback.run_fallback(since_minutes=10, dry_run=True, limit=10)

        self.assertEqual(rows[0]["status"], "blocked_sender")
        self.assertNotIn("reply", rows[0])
        build_reply.assert_not_called()

    def test_dry_run_does_not_mark_candidate_processed(self) -> None:
        candidate = fallback.FallbackCandidate(
            key="dry",
            sender="+13466429919",
            message="/new",
            session_file=Path("/tmp/session.jsonl"),
            user_message_id="1",
            error="402",
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(fallback, "PROCESSED_PATH", Path(tmp) / "processed.json"),
            mock.patch.object(fallback, "RECEIPT_PATH", Path(tmp) / "receipts.jsonl"),
            mock.patch.object(fallback, "fallback_candidates", return_value=[candidate]),
            mock.patch.object(fallback, "load_env_file"),
            mock.patch.object(fallback, "sender_allowed", return_value=(True, "sender is owner-allowlisted")),
            mock.patch.object(
                fallback,
                "send_imessage",
                return_value={"returncode": 0, "stdout": "{}", "stderr": "", "dry_run": True},
            ),
        ):
            fallback.run_fallback(since_minutes=10, dry_run=True, limit=10)
            processed = json.loads((Path(tmp) / "processed.json").read_text(encoding="utf-8"))

        self.assertEqual(processed["processed_keys"], [])
        self.assertEqual(processed["attempt_counts"], {})

    def test_send_failure_records_attempt_count(self) -> None:
        candidate = fallback.FallbackCandidate(
            key="retry",
            sender="+13466429919",
            message="/new",
            session_file=Path("/tmp/session.jsonl"),
            user_message_id="1",
            error="402",
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(fallback, "PROCESSED_PATH", Path(tmp) / "processed.json"),
            mock.patch.object(fallback, "RECEIPT_PATH", Path(tmp) / "receipts.jsonl"),
            mock.patch.object(fallback, "fallback_candidates", return_value=[candidate]),
            mock.patch.object(fallback, "load_env_file"),
            mock.patch.object(fallback, "sender_allowed", return_value=(True, "sender is owner-allowlisted")),
            mock.patch.object(
                fallback,
                "send_imessage",
                return_value={"returncode": 1, "stdout": "", "stderr": "send failed", "dry_run": False},
            ),
        ):
            fallback.run_fallback(since_minutes=10, dry_run=False, limit=10)
            processed = json.loads((Path(tmp) / "processed.json").read_text(encoding="utf-8"))

        self.assertEqual(processed["attempt_counts"], {"retry": 1})
        self.assertEqual(processed["processed_keys"], [])

    def test_build_reply_uses_daily_board_local_tool(self) -> None:
        board = "# FUNDz Daily Board\n\nGenerated: now\n\nToday’s Objective: Stay focused.\nNext Action: Use local tools.\nBlocked: none.\nNeeds Brandon: nothing.\nProof Required: receipt.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board_path = root / "data" / "local" / "command-center" / "fundz-daily-board.md"
            board_path.parent.mkdir(parents=True)
            board_path.write_text(board, encoding="utf-8")
            with (
                mock.patch.object(fallback, "ROOT", root),
                mock.patch.object(fallback, "FUNDZ_COMMAND_CENTER", root / "scripts" / "fundz_command_center.py"),
                mock.patch.object(
                    fallback.subprocess,
                    "run",
                    return_value=mock.Mock(returncode=0, stdout="", stderr=""),
                ),
            ):
                kind, reply = fallback.build_reply("What should I do next?")

        self.assertEqual(kind, "daily_board")
        self.assertIn("Today’s Objective", reply)
        self.assertNotIn("Generated:", reply)

    def test_build_reply_routes_random_owner_question_to_ai_router(self) -> None:
        with mock.patch.object(
            fallback,
            "route_with_receipt",
            return_value=mock.Mock(reply="local AI answer"),
        ) as route:
            kind, reply = fallback.build_reply("Help me think through my day")

        self.assertEqual(kind, "ai_router")
        self.assertEqual(reply, "local AI answer")
        route.assert_called_once_with("Help me think through my day")

    def test_monitoring_question_uses_billing_lookup_before_ai(self) -> None:
        result = {
            "client_name": "Erika Jordan",
            "local_scorefusion_status": "not_found_check_alternate_monitoring_provider",
            "scorefusion_evidence": {
                "df_credit_monitoring": {
                    "monitoring_agency": "MyScoreIQ",
                    "app_status_provider": "Credit Tracker",
                    "app_status": "Logged In",
                }
            },
        }
        with (
            mock.patch.object(fallback, "build_billing_lookup", return_value=result) as lookup,
            mock.patch.object(fallback, "route_with_receipt") as route,
        ):
            kind, reply = fallback.build_reply("Is Erika Jordan active in ScoreFusion?")

        self.assertEqual(kind, "billing_monitoring")
        self.assertEqual(reply, "Erika Jordan: No active ScoreFusion. DF has MyScoreIQ as the CMS; Credit Tracker shows Logged In.")
        self.assertNotIn("Do not treat", reply)
        self.assertNotIn("blank ScoreFusion", reply)
        lookup.assert_called_once_with("Erika Jordan")
        route.assert_not_called()

    def test_monitoring_query_extracts_lowercase_name(self) -> None:
        self.assertEqual(
            fallback.monitoring_query_from_message("is erika jordan active in scorefusion"),
            "erika jordan",
        )


if __name__ == "__main__":
    unittest.main()
