from __future__ import annotations

import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_autofox_audit as audit


class FundzAutofoxAuditTests(unittest.TestCase):
    def test_skips_generated_reporting_files_as_evidence(self) -> None:
        self.assertTrue(audit.is_generated_reporting_file(Path("data/local/command-center/fundz-command-center.json")))
        self.assertTrue(audit.is_generated_reporting_file(Path("data/local/scorefusion-billing-dashboard/billing-risk-queue.csv")))
        self.assertFalse(audit.is_generated_reporting_file(Path("data/exports/disputefox-sms-report-20260505.csv")))


if __name__ == "__main__":
    unittest.main()
