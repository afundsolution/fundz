from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_ai_router as router


def ok_local(prompt: str, env: dict[str, str] | None = None) -> router.AIResponse:
    return router.AIResponse(True, "local answer", "ollama", "test-local")


def missing_local(prompt: str, env: dict[str, str] | None = None) -> router.AIResponse:
    return router.AIResponse(False, "", "ollama", "test-local", "Ollama missing")


def ok_paid(prompt: str, env: dict[str, str] | None = None) -> router.AIResponse:
    return router.AIResponse(True, f"paid answer: {prompt}", "openai", "test-paid")


class FundzAIRouterTests(unittest.TestCase):
    def test_detects_sensitive_business_context(self) -> None:
        self.assertTrue(router.is_sensitive_prompt("Can you review Dedrick Williams credit payment?"))
        self.assertTrue(router.is_sensitive_prompt("Summarize this iMessage thread for a client."))
        self.assertFalse(router.is_sensitive_prompt("Write a generic upbeat sales script."))

    def test_cleans_terminal_control_codes_from_model_text(self) -> None:
        dirty = "support you\x1b[3D\x1b[K\nyou?\x07"
        self.assertEqual(router.clean_model_text(dirty), "support you\nyou?")

    def test_uses_local_ai_first_even_when_paid_enabled(self) -> None:
        paid = mock.Mock(side_effect=ok_paid)

        result = router.route_question(
            "Write a generic follow-up script.",
            env={"FUNDZ_AI_PAID_ENABLED": "true"},
            local_caller=ok_local,
            paid_caller=paid,
        )

        self.assertEqual(result.route, "local_ai")
        self.assertEqual(result.reply, "local answer")
        paid.assert_not_called()

    def test_uses_paid_for_safe_prompt_when_local_missing_and_paid_enabled(self) -> None:
        result = router.route_question(
            "Write a generic follow-up script.",
            env={"FUNDZ_AI_PAID_ENABLED": "true"},
            local_caller=missing_local,
            paid_caller=ok_paid,
        )

        self.assertEqual(result.route, "paid_ai")
        self.assertIn("paid answer", result.reply)
        self.assertFalse(result.sensitive)

    def test_blocks_sensitive_prompt_from_paid_ai_by_default(self) -> None:
        paid = mock.Mock(side_effect=ok_paid)

        result = router.route_question(
            "APPROVE PAID AI: What should I do about Dedrick Williams credit payment?",
            env={"FUNDZ_AI_PAID_ENABLED": "true"},
            local_caller=missing_local,
            paid_caller=paid,
        )

        self.assertEqual(result.route, "paid_blocked_sensitive")
        self.assertTrue(result.sensitive)
        paid.assert_not_called()

    def test_can_allow_sensitive_paid_only_with_explicit_policy(self) -> None:
        paid = mock.Mock(side_effect=ok_paid)

        result = router.route_question(
            "APPROVE PAID AI: What should I do about Dedrick Williams credit payment?",
            env={"FUNDZ_AI_PAID_ENABLED": "true", "FUNDZ_AI_PAID_ALLOW_SENSITIVE": "true"},
            local_caller=missing_local,
            paid_caller=paid,
        )

        self.assertEqual(result.route, "paid_ai")
        self.assertTrue(result.sensitive)
        paid.assert_called_once()

    def test_receipts_store_redacted_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "receipt.jsonl"
            with (
                mock.patch.object(router, "RECEIPT_PATH", receipt_path),
                mock.patch.object(router, "route_question", return_value=router.AIRouteResult("local_ai", "ok", True, False)),
            ):
                router.route_with_receipt("Call me at 346-555-1212 about this client.")

            text = receipt_path.read_text(encoding="utf-8")

        self.assertIn("[redacted-phone:***1212]", text)
        self.assertNotIn("346-555-1212", text)


if __name__ == "__main__":
    unittest.main()
