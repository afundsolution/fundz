from __future__ import annotations

import json
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_postgres_memory as pgmem


class FundzPostgresMemoryTests(unittest.TestCase):
    def test_sql_literal_escapes_quotes(self) -> None:
        self.assertEqual(pgmem.sql_literal("Brandon's client"), "'Brandon''s client'")

    def test_json_literal_is_jsonb(self) -> None:
        literal = pgmem.json_literal({"b": 2, "a": 1})
        self.assertTrue(literal.endswith("::jsonb"))
        self.assertIn('"a": 1', literal)

    def test_build_sync_sql_upserts_snapshot_and_client(self) -> None:
        state = {
            "metadata": {"generated_at": "2026-05-04T12:00:00"},
            "summary": {"clients": 1, "active_clients": 1},
            "clients": [
                {
                    "client_key": "name:ada-lovelace",
                    "client_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "is_active_client": True,
                    "status": "In Dispute",
                    "stage_in_process": "Round 2 Sent",
                    "next_import": "14 Days",
                    "next_import_days": 14,
                    "assigned_to": "Brandon Jordan",
                    "dispute_round": {"number": 2, "label": "Round 2"},
                    "operational_flags": ["in_dispute"],
                    "recommended_next_action": "Monitor active dispute round.",
                    "send_history": {"email_count": 1, "sms_count": 1},
                    "dispute_items": {"all_items": 3},
                    "sources": ["sample.csv"],
                }
            ],
        }

        sql = pgmem.build_sync_sql(state)

        self.assertIn("insert into fundz_memory_snapshots", sql)
        self.assertIn("insert into fundz_client_memory", sql)
        self.assertIn("on conflict (client_key) do update", sql)
        self.assertIn("'name:ada-lovelace'", sql)
        self.assertIn("ARRAY['in_dispute']::text[]", sql)

    def test_state_hash_is_stable_for_sorted_json(self) -> None:
        left = {"summary": {"b": 2, "a": 1}, "clients": []}
        right = json.loads(json.dumps({"clients": [], "summary": {"a": 1, "b": 2}}))
        self.assertEqual(pgmem.state_hash(left), pgmem.state_hash(right))

    def test_dashboard_chunks_are_bounded_and_include_verify_query(self) -> None:
        state = {
            "summary": {"clients": 2, "active_clients": 1},
            "clients": [
                {
                    "client_key": "name:ada-lovelace",
                    "client_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "is_active_client": True,
                },
                {
                    "client_key": "name:grace-hopper",
                    "client_name": "Grace Hopper",
                    "email": "grace@example.com",
                    "is_active_client": False,
                },
            ],
        }

        chunks = pgmem.build_dashboard_chunks(state, max_bytes=10_000)

        self.assertEqual(chunks[0][0], "chunk-000-snapshot.sql")
        self.assertTrue(chunks[-1][0].endswith("-verify.sql"))
        self.assertIn("dashboard-sync-", chunks[0][1])
        self.assertIn("snapshot_marker_count", chunks[-1][1])
        joined_sql = "\n".join(sql for _, sql in chunks)
        self.assertIn("'name:ada-lovelace'", joined_sql)
        self.assertIn("'name:grace-hopper'", joined_sql)
        self.assertTrue(all(len(sql.encode("utf-8")) <= 10_000 for _, sql in chunks))


if __name__ == "__main__":
    unittest.main()
