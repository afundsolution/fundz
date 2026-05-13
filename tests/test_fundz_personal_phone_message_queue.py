import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import fundz_personal_phone_message_queue as queue


APPLE_2026 = 799_200_000_000_000_000


class PersonalPhoneMessageQueueTests(unittest.TestCase):
    def build_messages_db(self, path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT);
                CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
                CREATE TABLE message (
                    ROWID INTEGER PRIMARY KEY,
                    date INTEGER,
                    text TEXT,
                    attributedBody BLOB,
                    is_from_me INTEGER,
                    service TEXT,
                    handle_id INTEGER
                );
                INSERT INTO handle (ROWID, id) VALUES
                    (1, '+15551234567'),
                    (2, '+15557654321'),
                    (3, '+15550001111'),
                    (4, '22000');
                INSERT INTO chat (ROWID, chat_identifier) VALUES
                    (1, '+15551234567'),
                    (2, '+15557654321'),
                    (3, '+15550001111'),
                    (4, '22000');
                """
            )
            connection.executemany(
                """
                INSERT INTO message (ROWID, date, text, attributedBody, is_from_me, service, handle_id) VALUES
                    (?, ?, ?, NULL, ?, ?, ?);
                """
                ,
                [
                    (1, APPLE_2026, "Can you check my credit report?", 0, "SMS", 1),
                    (2, APPLE_2026 + 1, "Dinner at 7?", 0, "SMS", 2),
                    (3, APPLE_2026 + 2, "Anthony Williams asked about round 2", 1, "iMessage", 3),
                    (4, APPLE_2026 + 3, "Thanks", 0, "SMS", 1),
                    (5, APPLE_2026 + 4, "Can you check my score?", 0, "SMS", 2),
                    (6, APPLE_2026 + 5, "Your app verification code is 123456.", 0, "SMS", 4),
                ],
            )
            connection.executescript(
                """
                INSERT INTO chat_message_join (chat_id, message_id) VALUES
                    (1, 1), (2, 2), (3, 3), (1, 4), (2, 5), (4, 6);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def test_exports_only_business_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "chat.db"
            self.build_messages_db(db_path)
            client_csv = tmp_path / "clients.csv"
            client_csv.write_text(
                "client_name,sent_to\nAnthony Williams,15550001111\nJane Client,15551234567\n",
                encoding="utf-8",
            )

            with mock.patch.object(queue, "CLIENT_SOURCES", [client_csv]):
                rows = queue.build_queue(
                    messages_db=db_path,
                    output=tmp_path / "queue.csv",
                    summary=tmp_path / "summary.md",
                    triage=tmp_path / "triage.csv",
                    triage_md=tmp_path / "triage.md",
                    candidates=tmp_path / "candidates.csv",
                    keywords=["credit", "report", "round"],
                    max_messages=10,
                )

            self.assertEqual(len(rows), 2)
            contacts = {row["contact"] for row in rows}
            self.assertEqual(contacts, {"Anthony Williams", "Jane Client"})
            self.assertNotIn("Dinner at 7?", "\n".join(row["last_message"] for row in rows))

    def test_queue_fields_and_needs_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "chat.db"
            self.build_messages_db(db_path)
            client_csv = tmp_path / "clients.csv"
            client_csv.write_text("client_name,sent_to\nJane Client,15551234567\n", encoding="utf-8")
            output = tmp_path / "queue.csv"

            with mock.patch.object(queue, "CLIENT_SOURCES", [client_csv]):
                queue.build_queue(
                    messages_db=db_path,
                    output=output,
                    summary=tmp_path / "summary.md",
                    triage=tmp_path / "triage.csv",
                    triage_md=tmp_path / "triage.md",
                    candidates=tmp_path / "candidates.csv",
                    keywords=["credit", "report"],
                    max_messages=10,
                )

            with output.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

            self.assertEqual(list(written[0].keys()), queue.QUEUE_FIELDS)
            jane = next(row for row in written if row["contact"] == "Jane Client")
            self.assertEqual(jane["direction"], "inbound")
            self.assertEqual(jane["needs_reply"], "yes")
            self.assertEqual(jane["status"], "Needs Reply")

    def test_unknown_keyword_only_inbound_is_review_not_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "chat.db"
            self.build_messages_db(db_path)
            client_csv = tmp_path / "clients.csv"
            client_csv.write_text("client_name,sent_to\nJane Client,15551234567\n", encoding="utf-8")

            with mock.patch.object(queue, "CLIENT_SOURCES", [client_csv]):
                rows = queue.build_queue(
                    messages_db=db_path,
                    output=tmp_path / "queue.csv",
                    summary=tmp_path / "summary.md",
                    triage=tmp_path / "triage.csv",
                    triage_md=tmp_path / "triage.md",
                    candidates=tmp_path / "candidates.csv",
                    keywords=["score"],
                    max_messages=10,
                )

            unknown = next(row for row in rows if row["contact"] == "Unknown business keyword match")
            self.assertEqual(unknown["direction"], "inbound")
            self.assertEqual(unknown["needs_reply"], "no")
            self.assertEqual(unknown["status"], "Review")

    def test_security_code_short_code_messages_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "chat.db"
            self.build_messages_db(db_path)
            client_csv = tmp_path / "clients.csv"
            client_csv.write_text("client_name,sent_to\nJane Client,15551234567\n", encoding="utf-8")

            with mock.patch.object(queue, "CLIENT_SOURCES", [client_csv]):
                rows = queue.build_queue(
                    messages_db=db_path,
                    output=tmp_path / "queue.csv",
                    summary=tmp_path / "summary.md",
                    triage=tmp_path / "triage.csv",
                    triage_md=tmp_path / "triage.md",
                    candidates=tmp_path / "candidates.csv",
                    keywords=["app"],
                    max_messages=10,
                )

            self.assertFalse(any(row["phone"] == "22000" for row in rows))
            self.assertNotIn("verification code", "\n".join(row["last_message"] for row in rows).lower())

    def test_owner_number_is_not_client_needs_reply(self) -> None:
        row = {
            "contact": "Brandon Jordan",
            "phone": "+13466429919",
            "last_message": "FUNDz status",
            "date": "2026-05-12T12:00:00-05:00",
            "direction": "inbound",
            "needs_reply": "no",
            "owner": "Brandon",
            "status": "Owner Review",
            "source": "Mac Messages chat.db | client_phone;owner_command_source",
        }

        triage = queue.triage_rows([row])

        self.assertEqual(triage[0]["classification"], "owner-command/private intake")
        self.assertEqual(triage[0]["move_to_work_queue"], "no")
        self.assertEqual(triage[0]["needs_brandon_decision"], "no")

    def test_travis_triage_generates_approval_candidate(self) -> None:
        row = {
            "contact": "Travis Vance",
            "phone": "+15042151873",
            "last_message": "Sensitive short message",
            "date": "2026-03-15T16:58:26-05:00",
            "direction": "inbound",
            "needs_reply": "yes",
            "owner": "Brandon",
            "status": "Needs Reply",
            "source": "Mac Messages chat.db | client_phone",
        }

        triage = queue.triage_rows([row])
        candidates = queue.candidate_rows_from_triage(triage, "2026-05-12T12:00:00-05:00")

        self.assertEqual(triage[0]["needs_brandon_decision"], "yes")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["client_name"], "Travis Vance")
        self.assertIn("sensitive_content", candidates[0]["flags"])

    def test_no_company_action_contact_is_closed(self) -> None:
        row = {
            "contact": "Travis Vance",
            "phone": "+15042151873",
            "last_message": "Sensitive short message",
            "date": "2026-03-15T16:58:26-05:00",
            "direction": "inbound",
            "needs_reply": "yes",
            "owner": "Brandon",
            "status": "Needs Reply",
            "source": "Mac Messages chat.db | client_phone",
        }

        triage = queue.triage_rows([row], {"travis vance"})
        candidates = queue.candidate_rows_from_triage(triage, "2026-05-12T12:00:00-05:00")

        self.assertEqual(triage[0]["classification"], "personal/no-company-action")
        self.assertEqual(triage[0]["needs_brandon_decision"], "no")
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
