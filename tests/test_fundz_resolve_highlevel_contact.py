from __future__ import annotations

import os
import unittest
from unittest import mock

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_resolve_highlevel_contact as resolver


class FundzResolveHighLevelContactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_builds_duplicate_search_url_with_location_and_email(self) -> None:
        url = resolver.build_duplicate_search_url("loc-123", email="client@example.com")

        self.assertIn("locationId=loc-123", url)
        self.assertIn("email=client%40example.com", url)

    def test_extracts_contact_from_common_response_shapes(self) -> None:
        self.assertEqual(resolver.extract_contact({"contact": {"id": "abc"}})["id"], "abc")
        self.assertEqual(resolver.extract_contact({"contacts": [{"id": "abc"}]})["id"], "abc")
        self.assertEqual(resolver.extract_contact({"id": "abc"})["id"], "abc")

    def test_resolve_contact_reports_missing_location_id(self) -> None:
        with mock.patch.object(resolver, "load_env_file"), self.assertRaises(SystemExit):
            resolver.resolve_contact(email="client@example.com")

    def test_resolve_contact_returns_contact_summary(self) -> None:
        os.environ["CREDIT_TRACKER_API_TOKEN"] = "token"
        with mock.patch.object(
            resolver,
            "request_get",
            return_value=(200, '{"contact":{"id":"abc123","firstName":"Ada","email":"ada@example.com"}}'),
        ):
            result = resolver.resolve_contact(email="ada@example.com", location_id="loc-123")

        self.assertTrue(result["ok"])
        self.assertEqual(resolver.contact_summary(result["contact"])["id"], "abc123")


if __name__ == "__main__":
    unittest.main()
