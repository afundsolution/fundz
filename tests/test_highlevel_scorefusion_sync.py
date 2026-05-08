from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import highlevel_scorefusion_sync as sync


class HighLevelScoreFusionSyncTests(unittest.TestCase):
    def test_maps_roster_values_to_highlevel_custom_fields(self) -> None:
        row = {
            "enrollment_date": "2026-05-01",
            "next_charge_date": "2026-06-01",
            "last_warning_sent_date": "",
            "last_charge_date": "",
            "highlevel_pipeline_stage": "Enrolled",
            "amount_due": "27.9",
            "billing_status": "Client Card Failure",
        }
        fields = {
            name: {"id": f"id-{index}", "fieldKey": f"contact.{sync.setup.normalize(name)}"}
            for index, name in enumerate(sync.FIELD_TO_ROSTER, start=1)
        }

        payload = sync.custom_field_payload(row, fields, "2026-05-04")
        by_key = {item["key"]: item["field_value"] for item in payload}

        self.assertEqual(by_key["sf_status"], "Active")
        self.assertEqual(by_key["sf_amount_due"], "27.90")
        self.assertEqual(by_key["sf_last_disputefox_sync"], "2026-05-04")
        self.assertNotIn("sf_warning_sent_date", by_key)

    def test_writes_import_ready_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            roster = Path(temp) / "roster.csv"
            output = Path(temp) / "import.csv"
            with roster.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "email",
                        "client_name",
                        "phone",
                        "enrollment_date",
                        "next_charge_date",
                        "last_warning_sent_date",
                        "last_charge_date",
                        "highlevel_pipeline_stage",
                        "amount_due",
                        "billing_status",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "email": "Ada@Example.com",
                        "client_name": "Ada Lovelace",
                        "phone": "",
                        "enrollment_date": "2026-05-01",
                        "next_charge_date": "2026-06-01",
                        "highlevel_pipeline_stage": "At Risk",
                        "amount_due": "40",
                        "billing_status": "Past Due",
                    }
                )

            result = sync.write_import_csv(roster, output, "2026-05-04")

            self.assertEqual(result["rows"], 1)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["Email"], "ada@example.com")
            self.assertEqual(rows[0]["First Name"], "Ada")
            self.assertEqual(rows[0]["Last Name"], "Lovelace")
            self.assertEqual(rows[0]["SF_Status"], "At Risk")
            self.assertEqual(rows[0]["SF_Amount_Due"], "40.00")

    def test_defaults_to_drive_roster_when_local_roster_is_missing(self) -> None:
        self.assertEqual(
            sync.default_roster_path(use_drive_paths=True),
            sync.DRIVE_DIR / sync.ROSTER_BASENAME,
        )


if __name__ == "__main__":
    unittest.main()
