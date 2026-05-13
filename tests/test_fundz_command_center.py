from __future__ import annotations

import tempfile
import unittest
import json
import csv
from datetime import datetime, timedelta
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fundz_command_center as command_center


class FundzCommandCenterTests(unittest.TestCase):
    def sample_clients(self) -> list[dict]:
        return [
            {
                "client_key": "name:ada",
                "is_active_client": True,
                "client_name": "Ada Lovelace",
                "email": "ada@example.com",
                "status": "Due For Next Round",
                "stage_in_process": "Round 2 Sent",
                "next_import": "0 Days",
                "next_import_days": 0,
                "dispute_round": {"number": 2},
                "operational_flags": ["due_for_next_round"],
                "send_history": {
                    "latest_email": {"sent_date": "1 Hour ago"},
                    "recent_sms": [{"sent_to": "15555550123"}],
                    "recipients": ["ada@example.com", "15555550123"],
                },
                "recommended_next_action": "Review next-round readiness.",
            },
            {
                "client_key": "name:ben",
                "is_active_client": True,
                "client_name": "Ben Franklin",
                "email": "",
                "status": "In Dispute",
                "stage_in_process": "Round 1 Sent",
                "dispute_round": {"number": 1},
                "operational_flags": ["missing_next_import"],
                "send_history": {"latest_email": {}, "recent_sms": [], "recipients": []},
                "recommended_next_action": "Confirm next import date.",
            },
        ]

    def test_contact_ledger_prioritizes_next_round_and_owner_review(self) -> None:
        ledger = command_center.build_contact_ledger(self.sample_clients())
        rows = {row["client_name"]: row for row in ledger}

        self.assertEqual(rows["Ada Lovelace"]["phase"], "next-round-window")
        self.assertEqual(rows["Ada Lovelace"]["cadence"], "daily-business-day")
        self.assertEqual(rows["Ada Lovelace"]["next_touch_status"], "prepare-owner-approved-next-round-touch")
        self.assertEqual(rows["Ben Franklin"]["next_touch_status"], "owner-review-before-message")
        self.assertGreater(rows["Ada Lovelace"]["priority_score"], 0)

    def test_build_command_center_collects_core_sections(self) -> None:
        state = {"summary": {"active_clients": 2, "clients": 2}, "clients": self.sample_clients()}
        queue = {
            "summary": {"draft_for_approval": 1, "owner_review": 1},
            "actions": [
                {
                    "action_type": "draft_for_approval",
                    "client_name": "Ada Lovelace",
                    "reason": "Client is due for next round.",
                    "risky_hits": [],
                }
            ],
        }

        with (
            mock.patch.object(command_center, "load_env_file"),
            mock.patch.object(command_center, "build_operational_state", return_value=state),
            mock.patch.object(command_center, "build_action_queue", return_value=queue),
            mock.patch.object(command_center, "collect_autofox_audit", return_value={"records": 0}),
            mock.patch.object(command_center, "bridge_status", return_value={"recent_events": 0, "kinds": {}}),
            mock.patch.object(command_center, "scorefusion_snapshot", return_value={"ok": True, "enrolled": 2}),
            mock.patch.object(command_center, "receipt_summary", return_value={"recent_receipts": [], "pilot_clients": {}}),
            mock.patch.object(command_center, "build_pilot_status_report", return_value={"summary": {"clients": 5}, "pilot_clients": []}),
            mock.patch.object(command_center, "highlevel_blocker", return_value="HighLevel blocked."),
            mock.patch.object(command_center, "cloudflare_blocker", return_value="Cloudflare blocked."),
            mock.patch.object(command_center, "read_json", return_value=None),
        ):
            report = command_center.build_command_center(limit=1)

        self.assertEqual(report["summary"]["active_clients"], 2)
        self.assertEqual(report["summary"]["owner_review_before_message"], 1)
        self.assertEqual(len(report["top_actions"]), 1)
        self.assertEqual(report["next_safe_batch_candidates"][0]["client_name"], "Ada Lovelace")
        self.assertIn("HighLevel blocked.", report["blockers"])
        self.assertIn("release_checklist", report)
        self.assertEqual(report["pilot_status"]["summary"]["clients"], 5)
        self.assertEqual(report["scorefusion"]["enrolled"], 2)
        self.assertIn("backlog_coverage", report)
        self.assertIn("no_approval_work_queue", report)

    def test_pilot_status_report_reads_provider_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "app-result.json").write_text(
                json.dumps(
                    {
                        "mode": "batch_result",
                        "results": [
                            {
                                "client_name": "Anitra Thomas",
                                "sent": True,
                                "result": {"body": "{\"messageId\":\"msg-1\",\"conversationId\":\"conv-1\"}"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (base / "email-result.json").write_text(
                json.dumps(
                    {
                        "mode": "email_companion_result",
                        "results": [
                            {
                                "client_name": "Anitra Thomas",
                                "sent": True,
                                "result": {"body": "{\"emailMessageId\":\"email-1\",\"conversationId\":\"conv-1\"}"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(command_center, "RECEIPTS_DIR", base):
                report = command_center.build_pilot_status_report()

        anitra = next(item for item in report["pilot_clients"] if item["client_name"] == "Anitra Thomas")
        self.assertTrue(anitra["app_or_sms_sent"])
        self.assertTrue(anitra["email_sent"])
        self.assertIn("msg-1", anitra["provider_message_ids"])
        self.assertIn("email-1", anitra["provider_message_ids"])
        self.assertIn("Credit Tracker app/portal visibility not confirmed", anitra["unresolved"])

    def test_release_checklist_blocks_known_external_dependencies(self) -> None:
        report = {
            "summary": {"owner_review_before_message": 2},
            "blockers": ["HighLevel inbox poller is blocked.", "Permanent Cloudflare tunnel is blocked.", "Credit Tracker app/portal visual confirmation is still pending."],
            "autofox_audit": {"failures": 1, "duplicates": 1, "after_hours": 1},
        }

        checklist = command_center.release_checklist(report)
        statuses = {item["check"]: item["status"] for item in checklist}

        self.assertEqual(statuses["HighLevel inbox readable"], "blocked")
        self.assertEqual(statuses["Cloudflare named tunnel stable"], "blocked")
        self.assertEqual(statuses["App visibility confirmed"], "blocked")
        self.assertEqual(statuses["AutoFox failures reviewed"], "review")

    def test_write_outputs_command_center_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = {
                "generated_at": "2026-05-05T12:00:00-0500",
                "summary": {"active_clients": 1, "owner_review_before_message": 0, "no_recent_contact_found": 0, "action_counts": {}},
                "blockers": [],
                "communication_coverage": {"active_clients": 1, "with_email": 1, "with_phone_history": 1},
                "top_actions": [],
                "next_safe_batch_candidates": [],
                "autofox_audit": {},
                "scorefusion": {},
                "receipts": {"recent_receipts": []},
                "pilot_status": {"summary": {"clients": 0}, "pilot_clients": []},
                "what_changed_since_last_run": {"available": False, "note": "none"},
                "release_checklist": [],
                "backlog_coverage": [],
                "no_approval_work_queue": [],
                "missing_steps_recheck": [],
                "ledger": [
                    {
                        "priority_score": 1,
                        "client_name": "Ada Lovelace",
                        "phase": "round-1",
                        "cadence": "every-other-business-day",
                        "status": "In Dispute",
                    }
                ],
            }
            patch_values = {
                "OUTPUT_DIR": base,
                "COMMAND_CENTER_JSON": base / "cc.json",
                "COMMAND_CENTER_MD": base / "cc.md",
                "TODAY_OPERATING_BOARD_MD": base / "today.md",
                "TODAY_DECISION_QUEUE_CSV": base / "today.csv",
                "DAILY_BOARD_MD": base / "daily.md",
                "WORK_QUEUE_CSV": base / "work-queue.csv",
                "WORK_QUEUE_SHEET_IMPORT_CSV": base / "sheet-import.csv",
                "GOVERNOR_SAFE_FIXES_MD": base / "governor.md",
                "GOVERNOR_ALERTS_CSV": base / "alerts.csv",
                "COMMUNICATION_CONTROL_BOARD_MD": base / "control-board.md",
                "COMMUNICATION_CONTROL_BOARD_CSV": base / "control-board.csv",
                "CONTACT_LEDGER_CSV": base / "ledger.csv",
                "PILOT_REPORT_MD": base / "pilot.md",
                "WEEKLY_SUMMARY_MD": base / "weekly.md",
                "RELEASE_CHECKLIST_MD": base / "checklist.md",
                "OWNER_REVIEW_CSV": base / "owner.csv",
                "NO_RECENT_CONTACT_CSV": base / "no-recent.csv",
                "SAFE_BATCH_CSV": base / "safe-batch.csv",
                "AUTOFOX_MIGRATION_MD": base / "migration.md",
                "MEMBER_EXPERIENCE_MD": base / "member-experience.md",
                "MEMBER_EXPERIENCE_TIPS_CSV": base / "tips.csv",
                "OWNER_REVIEW_ACTIONS_MD": base / "owner-actions.md",
                "OWNER_REVIEW_ACTIONS_CSV": base / "owner-actions.csv",
                "OWNER_REVIEW_PACKET_MD": base / "owner-packet.md",
                "OWNER_DECISION_QUEUE_CSV": base / "owner-decision.csv",
                "OWNER_DECISION_PACKET_MD": base / "owner-decision.md",
                "NO_RECENT_CONTACT_INVESTIGATION_MD": base / "no-recent-investigation.md",
                "NO_RECENT_CONTACT_INVESTIGATION_CSV": base / "no-recent-investigation.csv",
                "GAP_CLOSURE_MD": base / "gaps.md",
                "MISSING_STEPS_RECHECK_MD": base / "missing.md",
                "BUSINESS_REVIEW_ROLLOUT_MD": base / "business-rollout.md",
                "PREVIEW_PACKET_DECISION_MD": base / "preview-decision.md",
                "BILLING_ROLLOUT_TRIAGE_MD": base / "billing-triage.md",
                "BILLING_ROLLOUT_TRIAGE_CSV": base / "billing-triage.csv",
                "BILLING_MAINTENANCE_FOCUS_MD": base / "billing-maintenance.md",
                "BILLING_MAINTENANCE_FOCUS_CSV": base / "billing-maintenance.csv",
                "ARCHIVE_RECEIPT_TRAIL_MD": base / "archive-receipts.md",
                "SEND_VISIBILITY_MD": base / "send-visibility.md",
                "SEND_LEDGER_CSV": base / "send-ledger.csv",
                "NEXT_SEND_QUEUE_CSV": base / "next-send.csv",
                "SEND_KILL_SWITCH_MD": base / "kill-switch.md",
                "SEND_KILL_SWITCH_JSON": base / "kill-switch.json",
                "SEND_GATE_LOCK_MD": base / "send-gate-lock.md",
                "CLEAN_BACKUP_PREVIEW_MD": base / "clean-backups.md",
                "CLEAN_BACKUP_PREVIEW_CSV": base / "clean-backups.csv",
                "NO_APPROVAL_WORK_CSV": base / "no-approval.csv",
            }
            with ExitStack() as stack:
                for attr, value in patch_values.items():
                    stack.enter_context(mock.patch.object(command_center, attr, value))
                stack.enter_context(mock.patch.object(command_center, "build_operational_state", return_value={"clients": []}))
                stack.enter_context(mock.patch.object(command_center, "write_json"))
                stack.enter_context(mock.patch.object(command_center, "write_summary_csv"))
                paths = command_center.write_command_center(report)

            self.assertTrue((base / "cc.json").exists())
            self.assertTrue((base / "cc.md").exists())
            self.assertTrue((base / "control-board.md").exists())
            self.assertTrue((base / "control-board.csv").exists())
            self.assertTrue((base / "ledger.csv").exists())
            self.assertTrue((base / "pilot.md").exists())
            self.assertTrue((base / "weekly.md").exists())
            self.assertTrue((base / "checklist.md").exists())
            self.assertTrue((base / "owner.csv").exists())
            self.assertTrue((base / "no-recent.csv").exists())
            self.assertTrue((base / "safe-batch.csv").exists())
            self.assertTrue((base / "migration.md").exists())
            self.assertTrue((base / "member-experience.md").exists())
            self.assertTrue((base / "tips.csv").exists())
            self.assertTrue((base / "owner-actions.md").exists())
            self.assertTrue((base / "owner-actions.csv").exists())
            self.assertTrue((base / "owner-packet.md").exists())
            self.assertTrue((base / "owner-decision.csv").exists())
            self.assertTrue((base / "owner-decision.md").exists())
            self.assertTrue((base / "no-recent-investigation.md").exists())
            self.assertTrue((base / "no-recent-investigation.csv").exists())
            self.assertTrue((base / "gaps.md").exists())
            self.assertTrue((base / "missing.md").exists())
            self.assertTrue((base / "business-rollout.md").exists())
            self.assertTrue((base / "preview-decision.md").exists())
            self.assertTrue((base / "billing-triage.md").exists())
            self.assertTrue((base / "billing-triage.csv").exists())
            self.assertTrue((base / "billing-maintenance.md").exists())
            self.assertTrue((base / "billing-maintenance.csv").exists())
            self.assertTrue((base / "archive-receipts.md").exists())
            self.assertTrue((base / "send-gate-lock.md").exists())
            self.assertTrue((base / "clean-backups.md").exists())
            self.assertTrue((base / "clean-backups.csv").exists())
            self.assertTrue((base / "no-approval.csv").exists())
            self.assertIn("cc.md", paths["markdown"])
            self.assertIn("control-board.md", paths["communication_control_board"])
            self.assertIn("member-experience.md", paths["member_experience"])
            self.assertIn("owner-actions.md", paths["owner_review_actions"])
            self.assertIn("no-recent-investigation.md", paths["no_recent_contact_investigation"])
            self.assertIn("business-rollout.md", paths["business_review_rollout"])
            self.assertIn("preview-decision.md", paths["preview_packet_decision"])
            self.assertIn("billing-triage.md", paths["billing_rollout_triage"])
            self.assertIn("billing-maintenance.md", paths["billing_maintenance_focus"])
            self.assertIn("archive-receipts.md", paths["archive_receipt_trail"])
            self.assertIn("send-gate-lock.md", paths["send_gate_lock"])
            self.assertIn("clean-backups.md", paths["clean_backup_preview"])

    def test_communication_control_board_blocks_mobile_app_sms_until_app_ready(self) -> None:
        report = {
            "ledger": [
                {
                    "client_name": "Anthony Williams",
                    "client_key": "name:anthony-williams",
                    "phase": "onboarding",
                    "status": "Due For Next Round",
                    "stage": "Round 7 Ready",
                    "next_import": "-86 Days",
                    "latest_touch": "sms: present in latest SMS history",
                    "next_touch_status": "owner-review-before-message",
                    "has_email": True,
                    "flags": "due_for_next_round;onboarding_incomplete",
                    "recommended_next_action": "Review next-round readiness.",
                    "priority_score": 165,
                }
            ],
            "work_queue": [
                {
                    "client_name": "Anthony Williams",
                    "client_key": "name:anthony-williams",
                    "queue_status": "Failed",
                    "next_step": "Investigate failed App SMS.",
                    "proof_required": "Failure receipt required.",
                    "evidence": "receipt.md",
                    "do_not_send_because": "Status is not approved for live outreach.",
                }
            ],
        }

        rows = command_center.build_communication_control_board(
            report,
            owner_decisions={"anthony williams": {"owner_decision": "approved"}},
            failed_clients={"anthony williams": "receipt.md"},
            rollout_reconciliation={},
        )

        self.assertEqual(rows[0]["communication_status"], "Failed - fix first")
        self.assertEqual(rows[0]["message_lane"], "Problem / Owner Review")
        self.assertEqual(rows[0]["mobile_app_sms_allowed"], "no")
        self.assertIn("Installed/Logged In", rows[0]["block_reason"])

    def test_writes_communication_control_board_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = {
                "generated_at": "2026-05-05T12:00:00-0500",
                "communication_control_board": [
                    {
                        "client_name": "Ada",
                        "message_lane": "Round Updates",
                        "communication_status": "Blocked",
                        "app_readiness": "Unknown - verify DF app status",
                        "mobile_app_sms_allowed": "no",
                        "email_allowed": "yes - approval/proof gated",
                        "block_reason": "Global proof gate",
                        "recommended_next_action": "Verify app status.",
                        "billing_or_problem_flag": "missing_next_import",
                    }
                ],
            }
            md = base / "board.md"
            csv_path = base / "board.csv"

            command_center.write_communication_control_board(report, md, csv_path)

            self.assertIn("Client Communication Control Board", md.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["client_name"], "Ada")
            self.assertEqual(rows[0]["communication_status"], "Blocked")

    def test_member_experience_system_contains_four_lanes_and_twenty_tips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "member-experience.md"
            tips_csv = Path(temp) / "tips.csv"
            report = {"generated_at": "2026-05-05T12:00:00-0500"}

            command_center.write_member_experience_system(report, path, tips_csv)

            text = path.read_text(encoding="utf-8")
            with tips_csv.open(encoding="utf-8", newline="") as handle:
                tip_rows = list(csv.DictReader(handle))
            self.assertIn("Onboarding", text)
            self.assertIn("Round Updates", text)
            self.assertIn("Education / Credit Tips", text)
            self.assertIn("Problem / Owner Review", text)
            self.assertIn("Next Controlled Tip 04 Review Packet", text)
            self.assertIn("Step 9 - Credit Tip 04 - Statement Dates (24 Days)", text)
            self.assertIn("Interval Value = 24", text)
            self.assertIn("FUNDz marker - Credit Tip 04 Step 9", text)
            self.assertIn("No manual client send or campaign assignment was performed", text)
            self.assertIn("Credit Tip 20 - Long-Term Habits", text)
            self.assertIn("Owner Review - App SMS Failed", text)
            self.assertEqual(len(tip_rows), 20)

    def test_owner_review_action_catalog_contains_problem_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "owner-actions.md"
            csv_path = Path(temp) / "owner-actions.csv"
            report = {"generated_at": "2026-05-05T12:00:00-0500"}

            command_center.write_owner_review_action_catalog(report, path, csv_path)

            text = path.read_text(encoding="utf-8")
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertIn("Billing issue", text)
            self.assertIn("App SMS failed", text)
            self.assertIn("No app login", text)
            self.assertEqual(len(rows), 8)

    def test_writes_drilldown_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = {
                "ledger": [
                    {"client_name": "Ada", "next_touch_status": "owner-review-before-message", "priority_score": 10},
                    {"client_name": "Ben", "next_touch_status": "no-recent-contact-found", "priority_score": 1},
                ],
                "next_safe_batch_candidates": [{"client_name": "Grace", "action_type": "draft_for_approval"}],
                "sequence_assignments": {"ben": {"result": "assigned", "evidence": "receipt.csv"}},
            }
            with (
                mock.patch.object(command_center, "OWNER_REVIEW_CSV", base / "owner.csv"),
                mock.patch.object(command_center, "NO_RECENT_CONTACT_CSV", base / "no-recent.csv"),
                mock.patch.object(command_center, "SAFE_BATCH_CSV", base / "safe-batch.csv"),
            ):
                command_center.write_drilldown_csvs(report)

            self.assertIn("Ada", (base / "owner.csv").read_text(encoding="utf-8"))
            no_recent_text = (base / "no-recent.csv").read_text(encoding="utf-8")
            self.assertIn("Ben", no_recent_text)
            self.assertIn("sequence_assignment", no_recent_text)
            self.assertIn("receipt.csv", no_recent_text)
            self.assertIn("Grace", (base / "safe-batch.csv").read_text(encoding="utf-8"))

    def test_writes_owner_review_packet_grouped_by_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "packet.md"
            report = {
                "generated_at": "2026-05-05T12:00:00-0500",
                "ledger": [
                    {
                        "client_name": "Ada",
                        "next_touch_status": "owner-review-before-message",
                        "flags": "payment_attention",
                        "priority_score": 95,
                        "status": "In Dispute",
                        "recommended_next_action": "Review billing.",
                    },
                    {
                        "client_name": "Ben",
                        "next_touch_status": "owner-review-before-message",
                        "flags": "missing_next_import",
                        "priority_score": 70,
                        "status": "In Dispute",
                        "recommended_next_action": "Confirm next import.",
                    },
                ],
            }

            command_center.write_owner_review_packet(report, path)

            text = path.read_text(encoding="utf-8")
            self.assertIn("Billing Attention: 1", text)
            self.assertIn("Missing Next Import: 1", text)
            self.assertIn("Ada", text)
            self.assertIn("Ben", text)

    def test_gap_closure_plan_lists_coverage_and_work_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gaps.md"
            report = {
                "generated_at": "2026-05-05T12:00:00-0500",
                "backlog_coverage": [{"area": "Command Center / Operator UX", "status": "done", "gap": "Ready."}],
                "no_approval_work_queue": [{"priority": "1", "work_item": "Review packet", "input": "packet.md", "output": "Decision list."}],
                "blockers": ["HighLevel blocked."],
            }

            command_center.write_gap_closure_plan(report, path)

            text = path.read_text(encoding="utf-8")
            self.assertIn("Command Center / Operator UX", text)
            self.assertIn("Review packet", text)
            self.assertIn("HighLevel blocked", text)

    def test_business_review_controlled_rollout_blocks_live_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "business-rollout.md"
            report = {
                "generated_at": "2026-05-07T08:00:00-0500",
                "scorefusion": {
                    "enrolled": 2,
                    "owed_payments": 2,
                    "total_amount_due": "55.98",
                    "billing_risk_unique_keys": 2,
                    "billing_risk_duplicate_keys": 1,
                    "billing_risk_rows_in_duplicate_keys": 2,
                    "billing_review_bucket_summary": {"dual_failure_review": 1},
                },
                "release_checklist": [
                    {"check": "Human approval captured", "status": "blocked", "note": "Approval required."},
                    {
                        "check": "Dry run disabled only for approved command",
                        "status": "blocked",
                        "note": "Keep dry-run on.",
                    },
                ],
                "pilot_status": {"summary": {"clients": 1, "app_visibility_confirmed": 0}},
                "autofox_audit": {"failures": 0, "duplicates": 0, "after_hours": 0},
                "no_approval_work_queue": [
                    {"priority": "1", "work_item": "Review billing risk queue", "output": "Review first."}
                ],
            }

            command_center.write_business_review_controlled_rollout(report, path)

            text = path.read_text(encoding="utf-8")
            self.assertIn("Business Review + Controlled Rollout", text)
            self.assertIn("Do not run broad live outreach", text)
            self.assertIn("dual_failure_review: 1", text)
            self.assertIn("Human approval captured: blocked", text)

    def test_billing_rollout_triage_classifies_date_sensitive_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "billing.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "client_name",
                        "risk_level",
                        "review_bucket",
                        "next_charge_date",
                        "failure_types",
                        "amount_due",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "client_name": "Ada",
                        "risk_level": "high",
                        "review_bucket": "urgent_due_now_or_past_due",
                        "next_charge_date": "2026-05-07",
                        "failure_types": "Client Card Failure",
                        "amount_due": "27.99",
                    }
                )
                writer.writerow(
                    {
                        "client_name": "Ben",
                        "risk_level": "high",
                        "review_bucket": "date_sensitive_next_7_days",
                        "next_charge_date": "2026-05-09",
                        "failure_types": "Client Card Failure",
                        "amount_due": "27.99",
                    }
                )
                writer.writerow(
                    {
                        "client_name": "Grace",
                        "risk_level": "medium",
                        "review_bucket": "date_sensitive_next_7_days",
                        "next_charge_date": "2026-05-12",
                        "failure_types": "Low Credits Failure",
                        "amount_due": "27.99",
                    }
                )
                writer.writerow(
                    {
                        "client_name": "Not Date Sensitive",
                        "risk_level": "high",
                        "review_bucket": "standard_high_risk_review",
                        "next_charge_date": "",
                        "failure_types": "Client Card Failure",
                        "amount_due": "27.99",
                    }
                )

            with mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", path):
                rows = command_center.billing_rollout_triage_rows()

            decisions = {row["client_name"]: row["rollout_decision"] for row in rows}
            self.assertEqual(decisions["Ada"], "hold")
            self.assertEqual(decisions["Ben"], "owner_override_needed")
            self.assertEqual(decisions["Grace"], "exclude_from_rollout")
            self.assertNotIn("Not Date Sensitive", decisions)

    def test_clean_backup_preview_pool_excludes_billing_risk_and_blocked_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            billing_path = base / "billing.csv"
            packet_path = base / "packet.json"
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["client_name", "email"])
                writer.writeheader()
                writer.writerow({"client_name": "Ada Lovelace", "email": "ada@example.com"})
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-1",
                        "channel": "Email",
                        "items": [
                            {
                                "client_name": "Grace Hopper",
                                "client_key": "name:grace",
                                "send_ready": True,
                                "resolution": {"ok": True},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "communication_control_board": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "communication_status": "Prepare only"},
                    {"client_name": "Ben Franklin", "client_key": "name:ben", "communication_status": "Blocked"},
                ]
            }
            queue = {
                "actions": [
                    {"client_name": "Ada Lovelace", "client_key": "name:ada", "action_type": "draft_for_approval", "risky_hits": []},
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "action_type": "draft_for_approval", "risky_hits": []},
                    {"client_name": "Ben Franklin", "client_key": "name:ben", "action_type": "draft_for_approval", "risky_hits": []},
                ]
            }

            with (
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
            ):
                rows = command_center.clean_backup_preview_pool(report, queue)

            self.assertEqual([row["client_name"] for row in rows], ["Grace Hopper"])
            self.assertEqual(rows[0]["candidate_use"], "active_approved_preview")
            self.assertEqual(rows[0]["billing_risk_match"], "no")

    def test_clean_backup_preview_pool_drops_current_preview_after_send(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            billing_path = base / "billing.csv"
            packet_path = base / "packet.json"
            receipts = base / "receipts"
            receipts.mkdir()
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=["client_name", "email"]).writeheader()
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-1",
                        "channel": "Email",
                        "items": [
                            {
                                "client_name": "Grace Hopper",
                                "client_key": "name:grace",
                                "send_ready": True,
                                "resolution": {"ok": True},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (receipts / "batch-1-result.json").write_text(
                json.dumps({"sent": 1, "blocked_or_failed": 0, "skipped": 0}),
                encoding="utf-8",
            )
            report = {
                "communication_control_board": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "communication_status": "Prepare only"},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "communication_status": "Prepare only"},
                ]
            }
            queue = {
                "actions": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "action_type": "draft_for_approval", "risky_hits": []},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "action_type": "draft_for_approval", "risky_hits": []},
                ]
            }

            with (
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
                mock.patch.object(command_center, "RECEIPTS_DIR", receipts),
            ):
                rows = command_center.clean_backup_preview_pool(report, queue)

            self.assertEqual([row["client_name"] for row in rows], ["Katherine Johnson"])
            self.assertEqual(rows[0]["candidate_use"], "backup_preview_candidate")

    def test_clean_backup_preview_pool_drops_current_preview_when_not_send_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            billing_path = base / "billing.csv"
            packet_path = base / "packet.json"
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=["client_name", "email"]).writeheader()
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-1",
                        "channel": "Email",
                        "items": [
                            {
                                "client_name": "Grace Hopper",
                                "client_key": "name:grace",
                                "send_ready": False,
                                "blocked_reason": "HighLevel contact was not found.",
                                "do_not_send_because": ["HighLevel contact was not found."],
                                "resolution": {"ok": False},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "communication_control_board": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "communication_status": "Prepare only"},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "communication_status": "Prepare only"},
                ]
            }
            queue = {
                "actions": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "action_type": "draft_for_approval", "risky_hits": []},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "action_type": "draft_for_approval", "risky_hits": []},
                ]
            }

            with (
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
            ):
                rows = command_center.clean_backup_preview_pool(report, queue)

            self.assertEqual([row["client_name"] for row in rows], ["Katherine Johnson"])
            self.assertEqual(rows[0]["candidate_use"], "backup_preview_candidate")

    def test_clean_backup_preview_pool_excludes_prior_sent_client_after_new_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            billing_path = base / "billing.csv"
            packet_path = base / "packet.json"
            receipts = base / "receipts"
            receipts.mkdir()
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=["client_name", "email"]).writeheader()
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-2",
                        "channel": "Email",
                        "items": [
                            {
                                "client_name": "Grace Hopper",
                                "client_key": "name:grace",
                                "send_ready": True,
                                "resolution": {"ok": True},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (receipts / "batch-1-result.json").write_text(
                json.dumps(
                    {
                        "mode": "batch_result",
                        "batch_id": "batch-1",
                        "sent": 1,
                        "blocked_or_failed": 0,
                        "skipped": 0,
                        "results": [{"client_name": "Katherine Johnson", "sent": True, "status": 201}],
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "communication_control_board": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "communication_status": "Prepare only"},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "communication_status": "Prepare only"},
                    {"client_name": "Dorothy Vaughan", "client_key": "name:dorothy", "communication_status": "Prepare only"},
                ]
            }
            queue = {
                "actions": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "action_type": "draft_for_approval", "risky_hits": []},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "action_type": "draft_for_approval", "risky_hits": []},
                    {"client_name": "Dorothy Vaughan", "client_key": "name:dorothy", "action_type": "draft_for_approval", "risky_hits": []},
                ]
            }

            with (
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
                mock.patch.object(command_center, "RECEIPTS_DIR", receipts),
            ):
                rows = command_center.clean_backup_preview_pool(report, queue)

            self.assertEqual([row["client_name"] for row in rows], ["Grace Hopper", "Dorothy Vaughan"])
            self.assertEqual(rows[0]["candidate_use"], "active_approved_preview")
            self.assertEqual(rows[1]["candidate_use"], "backup_preview_candidate")

    def test_preview_packet_decision_holds_billing_risk_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            packet_path = base / "packet.json"
            preview_path = base / "preview.md"
            billing_path = base / "billing.csv"
            control_path = base / "control.csv"
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-1",
                        "mode": "batch_preview",
                        "channel": "Email",
                        "live_send_allowed": False,
                        "items": [
                            {
                                "client_name": "Ada Lovelace",
                                "client_key": "name:ada",
                                "status": "Due For Next Round",
                                "stage_in_process": "Round 5 Ready",
                                "send_ready": True,
                                "risky_hits": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "client_name",
                        "review_bucket",
                        "next_charge_date",
                        "rollout_treatment",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "client_name": "Ada Lovelace",
                        "review_bucket": "date_sensitive_next_7_days",
                        "next_charge_date": "2026-05-08",
                        "rollout_treatment": "Prioritize for human decision before the next charge date.",
                    }
                )
            with control_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["client_name", "communication_status", "block_reason"])
                writer.writeheader()
                writer.writerow({"client_name": "Ada Lovelace", "communication_status": "Prepare only", "block_reason": "Proof gated."})

            report = {"generated_at": "2026-05-07T08:00:00-0500", "release_checklist": []}
            with (
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PREVIEW_MD", preview_path),
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "COMMUNICATION_CONTROL_BOARD_CSV", control_path),
            ):
                decision = command_center.build_preview_packet_decision(report)

            self.assertEqual(decision["decision"], "hold")
            self.assertEqual(decision["billing_review_bucket"], "date_sensitive_next_7_days")
            self.assertIn("billing-risk review queue", decision["reason"])

    def test_preview_packet_decision_approves_capped_ready_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            packet_path = base / "packet.json"
            preview_path = base / "preview.md"
            billing_path = base / "billing.csv"
            receipts = base / "receipts"
            receipts.mkdir()
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "capped-batch-1",
                        "mode": "batch_preview",
                        "channel": "Email",
                        "batch_preset": "capped_ready_rollout",
                        "ready_only": True,
                        "capped_size": 5,
                        "max_batch_size": 5,
                        "live_send_allowed": False,
                        "skipped_candidates": [{"client_name": "Skipped Client", "reason": "not ready"}],
                        "items": [
                            {
                                "client_name": "Grace Hopper",
                                "client_key": "name:grace",
                                "status": "Due For Next Round",
                                "stage_in_process": "Round 5 Ready",
                                "send_ready": True,
                                "risky_hits": [],
                            },
                            {
                                "client_name": "Katherine Johnson",
                                "client_key": "name:katherine",
                                "status": "Due For Next Round",
                                "stage_in_process": "Round 4 Ready",
                                "send_ready": True,
                                "risky_hits": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["client_name", "review_bucket", "next_charge_date"])
                writer.writeheader()

            report = {
                "generated_at": "2026-05-07T10:00:00-0500",
                "release_checklist": [],
                "communication_control_board": [
                    {"client_name": "Grace Hopper", "client_key": "name:grace", "communication_status": "Prepare only"},
                    {"client_name": "Katherine Johnson", "client_key": "name:katherine", "communication_status": "Prepare only"},
                ],
            }
            with (
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PREVIEW_MD", preview_path),
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "RECEIPTS_DIR", receipts),
            ):
                decision = command_center.build_preview_packet_decision(report)

            self.assertEqual(decision["decision"], "approved_for_capped_batch_action")
            self.assertEqual(decision["selected"], 2)
            self.assertEqual(decision["send_ready_count"], 2)
            self.assertTrue(decision["send_ready"])
            self.assertEqual(decision["skipped_candidates"], 1)
            self.assertEqual([item["client_name"] for item in decision["preview_clients"]], ["Grace Hopper", "Katherine Johnson"])
            self.assertIn("exact capped packet", decision["next_step"])

    def test_preview_packet_decision_holds_capped_packet_with_not_ready_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            packet_path = base / "packet.json"
            preview_path = base / "preview.md"
            billing_path = base / "billing.csv"
            receipts = base / "receipts"
            receipts.mkdir()
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "capped-batch-2",
                        "mode": "batch_preview",
                        "channel": "Email",
                        "batch_preset": "capped_ready_rollout",
                        "ready_only": True,
                        "capped_size": 5,
                        "max_batch_size": 5,
                        "live_send_allowed": False,
                        "items": [
                            {
                                "client_name": "Ada Lovelace",
                                "client_key": "name:ada",
                                "status": "Due For Next Round",
                                "stage_in_process": "Round 5 Ready",
                                "send_ready": False,
                                "blocked_reason": "HighLevel contact was not found.",
                                "risky_hits": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with billing_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["client_name", "review_bucket", "next_charge_date"])
                writer.writeheader()

            report = {"generated_at": "2026-05-07T10:05:00-0500", "release_checklist": [], "communication_control_board": []}
            with (
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
                mock.patch.object(command_center, "EXPANSION_BATCH_PREVIEW_MD", preview_path),
                mock.patch.object(command_center, "BILLING_RISK_REVIEW_CSV", billing_path),
                mock.patch.object(command_center, "RECEIPTS_DIR", receipts),
            ):
                decision = command_center.build_preview_packet_decision(report)

            self.assertEqual(decision["decision"], "hold")
            self.assertIn("not send-ready", decision["reason"])
            self.assertIn("Hold this capped preview packet", decision["next_step"])

    def test_preview_packet_decision_marks_existing_successful_send_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            packet_path = base / "packet.json"
            receipts = base / "receipts"
            receipts.mkdir()
            packet_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-1",
                        "mode": "batch_preview",
                        "channel": "Email",
                        "live_send_allowed": False,
                        "items": [
                            {
                                "client_name": "Ada Lovelace",
                                "client_key": "name:ada",
                                "status": "Due For Next Round",
                                "stage_in_process": "Round 5 Ready",
                                "send_ready": True,
                                "risky_hits": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (receipts / "batch-1-result.json").write_text(
                json.dumps(
                    {
                        "mode": "batch_result",
                        "batch_id": "batch-1",
                        "approved_batch_send": True,
                        "sent": 1,
                        "blocked_or_failed": 0,
                        "skipped": 0,
                        "results": [{"client_name": "Ada Lovelace", "sent": True, "status": 201}],
                    }
                ),
                encoding="utf-8",
            )
            (receipts / "batch-1-receipt.md").write_text("receipt", encoding="utf-8")

            report = {"generated_at": "2026-05-07T09:10:00-0500", "release_checklist": []}
            with (
                mock.patch.object(command_center, "EXPANSION_BATCH_PACKET", packet_path),
                mock.patch.object(command_center, "RECEIPTS_DIR", receipts),
            ):
                decision = command_center.build_preview_packet_decision(report)

            self.assertEqual(decision["decision"], "sent_complete")
            self.assertEqual(decision["result_sent"], 1)
            self.assertIn("already sent", decision["reason"])

    def test_owner_decision_queue_turns_flags_into_decisions(self) -> None:
        report = {
            "ledger": [
                {
                    "client_name": "Ada",
                    "next_touch_status": "owner-review-before-message",
                    "flags": "payment_attention",
                    "priority_score": 95,
                    "status": "In Dispute",
                    "recommended_next_action": "Review billing.",
                },
                {
                    "client_name": "Ben",
                    "next_touch_status": "owner-review-before-message",
                    "flags": "missing_next_import",
                    "priority_score": 70,
                    "status": "In Dispute",
                    "recommended_next_action": "Confirm next import.",
                },
            ],
        }

        rows = command_center.build_owner_decision_queue(report)

        decisions = {row["client_name"]: row["decision_needed"] for row in rows}
        self.assertEqual(decisions["Ada"], "billing_review_before_outreach")
        self.assertEqual(decisions["Ben"], "confirm_next_import_or_round_status")

    def test_owner_decision_queue_skips_existing_approved_or_hold_decisions(self) -> None:
        report = {
            "ledger": [
                {"client_name": "Ada", "next_touch_status": "owner-review-before-message", "flags": "payment_attention", "priority_score": 95},
                {"client_name": "Ben", "next_touch_status": "owner-review-before-message", "flags": "missing_next_import", "priority_score": 70},
                {"client_name": "Grace", "next_touch_status": "owner-review-before-message", "flags": "onboarding_incomplete", "priority_score": 60},
            ],
        }
        decisions = {
            "ada": {"owner_decision": "approved"},
            "ben": {"owner_decision": "hold"},
        }

        rows = command_center.build_owner_decision_queue(report, owner_decisions=decisions)

        self.assertEqual([row["client_name"] for row in rows], ["Grace"])

    def test_today_decision_queue_turns_hold_rows_into_actions(self) -> None:
        report = {
            "work_queue": [
                {
                    "queue_status": "Hold",
                    "owner": "Brandon",
                    "lane": "billing-review",
                    "client_name": "Ada",
                    "next_step": "Keep hold until billing proof is checked.",
                    "proof_required": "Billing proof.",
                    "evidence": "queue.csv",
                    "priority_score": "100",
                    "work_order_id": "WO-1",
                },
                {
                    "queue_status": "Approved",
                    "client_name": "Ben",
                },
            ]
        }

        rows = command_center.build_today_decision_queue(report)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_name"], "Ada")
        self.assertEqual(rows[0]["decision"], "still_hold_until_required_proof")

    def test_safety_gate_snapshot_keeps_runtime_findings_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            autonomy = base / "autonomy.json"
            maintenance = base / "maintenance.json"
            autonomy.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-08T13:23:17-0500",
                        "ok": False,
                        "successful_steps": 6,
                        "total_steps": 6,
                        "runtime": {
                            "quiet": False,
                            "active_screens": ["fundz-live-send"],
                            "active_processes": ["999 python3 scripts/fundz_autofox_live_sender.py"],
                        },
                        "safety_findings": ["Unsafe: live FUNDz runtime process(es) appear to be running."],
                    }
                ),
                encoding="utf-8",
            )
            maintenance.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "successful_steps": 7,
                        "total_steps": 7,
                        "rollout_packet": {"approval_required": True, "live_send_allowed": False, "selected": 0},
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(command_center, "AUTONOMY_STATUS_JSON", autonomy),
                mock.patch.object(command_center, "MAINTENANCE_AUTOPILOT_STATUS_JSON", maintenance),
            ):
                snapshot = command_center.build_safety_gate_snapshot()

        self.assertEqual(snapshot["state"], "Review local runtime")
        self.assertFalse(snapshot["live_send_allowed"])
        self.assertEqual(snapshot["rollout_selected"], 0)
        self.assertEqual(snapshot["maintenance_steps"], "7/7")
        self.assertEqual(snapshot["unexpected_runtime_screens"], ["fundz-live-send"])
        self.assertEqual(snapshot["unexpected_runtime_processes"], ["999 python3 scripts/fundz_autofox_live_sender.py"])

    def test_safety_gate_allows_dashboard_reporting_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            autonomy = base / "autonomy.json"
            maintenance = base / "maintenance.json"
            autonomy.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-08T13:23:17-0500",
                        "ok": False,
                        "successful_steps": 6,
                        "total_steps": 6,
                        "runtime": {
                            "quiet": False,
                            "active_screens": ["fundz-command-center"],
                            "active_processes": [
                                "123 python3 scripts/fundz_command_center_server.py --host 127.0.0.1 --port 8797",
                                "456 cloudflared tunnel --config /Users/turbo/.cloudflared/fundz-command-center.yml run",
                            ],
                        },
                        "safety_findings": [
                            "Unsafe: live FUNDz screen session(s) are running: fundz-command-center.",
                            "Unsafe: live FUNDz runtime process(es) appear to be running.",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            maintenance.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "successful_steps": 7,
                        "total_steps": 7,
                        "rollout_packet": {"approval_required": True, "live_send_allowed": False, "selected": 0},
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(command_center, "AUTONOMY_STATUS_JSON", autonomy),
                mock.patch.object(command_center, "MAINTENANCE_AUTOPILOT_STATUS_JSON", maintenance),
            ):
                snapshot = command_center.build_safety_gate_snapshot()

        self.assertEqual(snapshot["state"], "Local reporting safe")
        self.assertTrue(snapshot["runtime_quiet"])
        self.assertTrue(snapshot["allowed_reporting_runtime"])
        self.assertEqual(snapshot["safety_findings"], [])
        self.assertEqual(snapshot["unexpected_runtime_screens"], [])
        self.assertEqual(snapshot["unexpected_runtime_processes"], [])

    def test_writes_owner_decision_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = {
                "generated_at": "2026-05-05T12:00:00-0500",
                "ledger": [
                    {
                        "client_name": "Ada",
                        "next_touch_status": "owner-review-before-message",
                        "flags": "onboarding_incomplete",
                        "priority_score": 60,
                        "status": "Active",
                        "recommended_next_action": "Finish onboarding.",
                    }
                ],
            }
            with (
                mock.patch.object(command_center, "OWNER_DECISION_QUEUE_CSV", base / "queue.csv"),
                mock.patch.object(command_center, "OWNER_DECISION_PACKET_MD", base / "packet.md"),
            ):
                command_center.write_owner_decision_outputs(report)

            self.assertIn("finish_onboarding_or_setup", (base / "queue.csv").read_text(encoding="utf-8"))
            self.assertIn("Ada", (base / "packet.md").read_text(encoding="utf-8"))

    def test_missing_steps_recheck_marks_external_blockers_and_ci(self) -> None:
        report = {
            "blockers": [
                "HighLevel inbox poller is blocked by 401; token needs conversation/message read scope.",
                "Permanent Cloudflare tunnel is blocked by missing origin certificate.",
            ],
            "pilot_status": {"summary": {"clients": 5, "app_visibility_confirmed": 0}},
            "release_checklist": [{"check": "App visibility confirmed", "status": "blocked"}],
        }

        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(command_center, "RECEIPTS_DIR", Path(temp)):
                rows = command_center.missing_steps_recheck(report)
        statuses = {row["area"]: row["status"] for row in rows}

        self.assertEqual(statuses["HighLevel inbox reading"], "blocked")
        self.assertEqual(statuses["Permanent Cloudflare tunnel"], "blocked")
        self.assertEqual(statuses["Credit Tracker app visibility proof"], "blocked")
        self.assertIn(statuses["CI full test coverage"], {"pass", "blocked"})
        self.assertEqual(statuses["Branch protection requires full tests"], "review")

    def test_highlevel_blocker_clears_after_successful_poll(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp) / "highlevel-inbox-poller.jsonl"
            log_path.write_text(
                '{"kind":"poll_failed","status":401}\n'
                '{"kind":"poll_complete","ok":true,"status":200}\n',
                encoding="utf-8",
            )
            with mock.patch.object(command_center, "POLLER_LOG", log_path):
                self.assertEqual(command_center.highlevel_blocker(), "")

    def test_highlevel_score_question_enters_work_queue_as_proof_needed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue_path = Path(temp) / "classified-replies.jsonl"
            queue_path.write_text(
                json.dumps(
                    {
                        "time": "2026-05-06T19:08:45-0500",
                        "message_id": "msg-erika",
                        "name": "Erika Jordan",
                        "message_preview": "Had my credit score changed?",
                        "classification": {
                            "labels": ["question"],
                            "needs_brandon_reply": False,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(command_center, "HIGHLEVEL_REPLY_QUEUE_JSONL", queue_path):
                rows = command_center.highlevel_reply_work_queue_rows("2026-05-06T19:10:00-0500")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_name"], "Erika Jordan")
        self.assertEqual(rows[0]["queue_status"], "Proof Needed")
        self.assertIn("Verify current Credit Tracker", rows[0]["next_step"])

    def test_highlevel_reply_receipt_marks_work_queue_sent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            queue_path = base / "classified-replies.jsonl"
            receipts_path = base / "reply-receipts.jsonl"
            queue_path.write_text(
                json.dumps(
                    {
                        "time": "2026-05-06T19:08:45-0500",
                        "message_id": "msg-erika",
                        "name": "Erika Jordan",
                        "message_preview": "Had my credit score changed?",
                        "classification": {
                            "labels": ["question"],
                            "needs_brandon_reply": False,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            receipts_path.write_text(
                json.dumps({"message_id": "msg-erika", "sent": True, "status": 201}) + "\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(command_center, "HIGHLEVEL_REPLY_QUEUE_JSONL", queue_path),
                mock.patch.object(command_center, "HIGHLEVEL_REPLY_RECEIPTS_JSONL", receipts_path),
            ):
                rows = command_center.highlevel_reply_work_queue_rows("2026-05-06T19:10:00-0500")

        self.assertEqual(rows[0]["queue_status"], "Sent")
        self.assertIn("reply_sent", rows[0]["flags"])
        self.assertTrue(rows[0]["proof"])

    def test_highlevel_no_action_decision_marks_work_queue_done(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            queue_path = base / "classified-replies.jsonl"
            decisions_path = base / "reply-decisions.csv"
            queue_path.write_text(
                json.dumps(
                    {
                        "time": "2026-05-07T09:10:50-0500",
                        "message_id": "msg-promo",
                        "name": "23808",
                        "message_preview": "Funding promo.",
                        "classification": {
                            "labels": ["no_action"],
                            "needs_brandon_reply": False,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            decisions_path.write_text(
                "work_order_id,decision,owner,proof,notes\n"
                "FUNDZ-HL-29BB38645237,no-action,Brandon,Reviewed as vendor promo,No response needed\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(command_center, "HIGHLEVEL_REPLY_QUEUE_JSONL", queue_path),
                mock.patch.object(command_center, "HIGHLEVEL_REPLY_DECISIONS_CSV", decisions_path),
            ):
                rows = command_center.highlevel_reply_work_queue_rows("2026-05-07T09:20:00-0500")

        self.assertEqual(rows[0]["queue_status"], "Done")
        self.assertEqual(rows[0]["browser_required"], "no")
        self.assertIn("decision_no_action", rows[0]["flags"])
        self.assertTrue(rows[0]["proof"])
        self.assertIn("No-action", rows[0]["do_not_send_because"])

    def test_done_queue_status_wins_over_prior_owner_hold_in_control_board(self) -> None:
        status = command_center.control_status({"queue_status": "Done"}, {}, "hold", False)

        self.assertEqual(status, "Done")

    def test_missing_steps_recheck_uses_app_communication_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipts = Path(temp)
            (receipts / "app-communication-erika-sent-proof-20260505.png").write_text("proof", encoding="utf-8")
            (receipts / "app-communication-regular-sms-paused-20260505.png").write_text("proof", encoding="utf-8")
            report = {
                "blockers": [],
                "pilot_status": {"summary": {"clients": 5, "app_visibility_confirmed": 0}},
                "release_checklist": [{"check": "App visibility confirmed", "status": "blocked"}],
            }

            with mock.patch.object(command_center, "RECEIPTS_DIR", receipts):
                rows = command_center.missing_steps_recheck(report)

        by_area = {row["area"]: row for row in rows}
        self.assertEqual(by_area["One-member app-communication campaign pilot"]["status"], "review")
        self.assertIn("Erika Jordan assignment proof exists", by_area["One-member app-communication campaign pilot"]["evidence"])
        self.assertEqual(by_area["Permanent Cloudflare tunnel"]["status"], "pass")
        self.assertIn("webhook-probe", by_area["Permanent Cloudflare tunnel"]["next_step"])
        self.assertIn("Round 1-10 sent campaigns", by_area["Old AutoFox workflow cleanup"]["evidence"])

    def test_missing_steps_recheck_uses_app_message_visibility_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipts = Path(temp)
            (receipts / "app-communication-erika-sent-proof-20260505.png").write_text("proof", encoding="utf-8")
            (receipts / "erika-app-message-history-sent-proof-20260506.png").write_text("proof", encoding="utf-8")
            report = {
                "blockers": [],
                "pilot_status": {"summary": {"clients": 5, "app_visibility_confirmed": 0}},
                "release_checklist": [
                    {"check": "Human approval captured", "status": "blocked"},
                    {"check": "App visibility confirmed", "status": "pass"},
                ],
            }

            with mock.patch.object(command_center, "RECEIPTS_DIR", receipts):
                rows = command_center.missing_steps_recheck(report)

        by_area = {row["area"]: row for row in rows}
        self.assertEqual(by_area["Credit Tracker app visibility proof"]["status"], "pass")
        self.assertIn("Workflow App Message rows marked Sent", by_area["Credit Tracker app visibility proof"]["evidence"])
        self.assertEqual(by_area["One-member app-communication campaign pilot"]["status"], "pass")
        self.assertIn("App Message visibility proof", by_area["One-member app-communication campaign pilot"]["evidence"])
        self.assertEqual(by_area["Broad outreach rollout closeout"]["status"], "pass")
        self.assertIn("parked/gated closeout", by_area["Broad outreach rollout closeout"]["evidence"])

    def test_writes_missing_steps_recheck(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.md"
            report = {
                "generated_at": "2026-05-05T12:00:00-0500",
                "missing_steps_recheck": [
                    {
                        "area": "HighLevel inbox reading",
                        "status": "blocked",
                        "evidence": "401",
                        "next_step": "Fix scope.",
                    }
                ],
            }

            command_center.write_missing_steps_recheck(report, path)

            text = path.read_text(encoding="utf-8")
            self.assertIn("HighLevel inbox reading", text)
            self.assertIn("Fix scope", text)

    def test_command_center_report_includes_operating_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "command-center.md"
            report = {
                "generated_at": "2026-05-08T12:00:00-0500",
                "summary": {"active_clients": 2, "owner_review_before_message": 1, "action_counts": {}},
                "daily_board": [],
                "work_queue": [
                    {"queue_status": "Approved"},
                    {"queue_status": "Needs Brandon"},
                    {"queue_status": "Done"},
                    {"queue_status": "Proof Needed"},
                ],
                "communication_control_board": [],
                "governor_alerts": [],
                "blockers": [],
            }

            command_center.write_markdown(report, path)

            text = path.read_text(encoding="utf-8")
            self.assertIn("## Operating Map", text)
            self.assertIn("A FUND Solution has one Command Center", text)
            self.assertIn("Message receipts and gates", text)
            self.assertIn("## Queue Truth", text)
            self.assertIn("Approved: 1 prepared-but-gated row(s)", text)
            self.assertIn("Done/Sent: 1 receipt-backed outcome(s)", text)

    def test_daily_board_outputs_exactly_five_lines(self) -> None:
        report = {
            "blockers": ["HighLevel blocked."],
            "work_queue": [
                {
                    "queue_status": "Blocked",
                    "next_step": "Fix token scope.",
                    "proof_required": "Poller returns 200.",
                }
            ],
        }

        board = command_center.build_daily_board(report)

        self.assertEqual([item["label"] for item in board], [
            "Today’s Objective",
            "Next Action",
            "Blocked",
            "Needs Brandon",
            "Proof Required",
        ])

    def test_daily_board_uses_no_approval_work_when_no_active_problem(self) -> None:
        report = {
            "blockers": [],
            "work_queue": [{"queue_status": "Hold", "next_step": "Do not send."}],
            "no_approval_work_queue": [
                {"work_item": "Review billing risk queue", "output": "Identify high-risk billing rows."}
            ],
        }

        board = command_center.build_daily_board(report)

        self.assertIn("Review billing risk queue", board[1]["value"])

    def test_daily_board_switches_to_maintenance_cleanup_objective(self) -> None:
        report = {
            "blockers": [],
            "work_queue": [],
            "maintenance_cleanup_summary": {"next_action": "Use the maintenance cleanup board."},
            "no_approval_work_queue": [
                {"work_item": "Use maintenance cleanup board", "output": "Use the maintenance cleanup board."}
            ],
        }

        board = command_center.build_daily_board(report)

        self.assertIn("Clean client records", board[0]["value"])
        self.assertIn("maintenance cleanup board", board[1]["value"])

    def test_no_approval_work_queue_surfaces_maintenance_cleanup_first(self) -> None:
        rows = command_center.no_approval_work_queue(
            {
                "work_queue": [],
                "maintenance_cleanup_summary": {"next_action": "Use the maintenance cleanup board."},
            }
        )

        self.assertEqual(rows[0]["work_item"], "Use maintenance cleanup board")
        self.assertIn("Refresh maintenance cleanup board", {row["work_item"] for row in rows})
        self.assertNotIn("Prepare preview-only tiny pilot", {row["work_item"] for row in rows})

    def test_no_approval_work_queue_surfaces_live_hold_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            live_hold_csv = base / "live-hold.csv"
            live_hold_md = base / "live-hold.md"
            live_hold_csv.write_text(
                "client_name,cleanup_decision\nDarryl Hatcher,repair_bounced_email_route\n",
                encoding="utf-8",
            )
            live_hold_md.write_text("# Live Hold\n", encoding="utf-8")

            with (
                mock.patch.object(command_center, "LIVE_HOLD_CLEANUP_CSV", live_hold_csv),
                mock.patch.object(command_center, "LIVE_HOLD_CLEANUP_MD", live_hold_md),
            ):
                rows = command_center.no_approval_work_queue({"work_queue": []})

        self.assertEqual(rows[0]["work_item"], "Review bounce/live-hold cleanup")

    def test_no_approval_work_queue_skips_excluded_bounce_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            live_hold_csv = base / "live-hold.csv"
            live_hold_md = base / "live-hold.md"
            live_hold_csv.write_text(
                "client_name,cleanup_decision\nDarryl Hatcher,exclude_bounced_email_route\n",
                encoding="utf-8",
            )
            live_hold_md.write_text("# Live Hold\n", encoding="utf-8")

            with (
                mock.patch.object(command_center, "LIVE_HOLD_CLEANUP_CSV", live_hold_csv),
                mock.patch.object(command_center, "LIVE_HOLD_CLEANUP_MD", live_hold_md),
            ):
                rows = command_center.no_approval_work_queue({"work_queue": []})

        self.assertNotEqual(rows[0]["work_item"], "Review bounce/live-hold cleanup")

    def test_no_approval_work_queue_skips_terminal_live_hold_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            live_hold_csv = base / "live-hold.csv"
            live_hold_md = base / "live-hold.md"
            live_hold_csv.write_text(
                "client_name,cleanup_decision\n"
                "Darryl Hatcher,exclude_bounced_email_route\n"
                "Jessica Saizan,exclude_live_billing_or_payment_hold\n",
                encoding="utf-8",
            )
            live_hold_md.write_text("# Live Hold\n", encoding="utf-8")

            with (
                mock.patch.object(command_center, "LIVE_HOLD_CLEANUP_CSV", live_hold_csv),
                mock.patch.object(command_center, "LIVE_HOLD_CLEANUP_MD", live_hold_md),
            ):
                rows = command_center.no_approval_work_queue({"work_queue": []})

        self.assertNotEqual(rows[0]["work_item"], "Review bounce/live-hold cleanup")

    def test_sequence_assignment_does_not_clear_no_recent_contact_gate(self) -> None:
        report = {
            "ledger": [
                {
                    "client_key": "name:ben",
                    "client_name": "Ben",
                    "next_touch_status": "no-recent-contact-found",
                    "has_email": True,
                    "priority_score": 1,
                    "flags": "no_send_history_linked",
                }
            ],
            "work_queue": [
                {
                    "client_key": "name:ben",
                    "client_name": "Ben",
                    "queue_status": "Needs Brandon",
                    "next_step": "Confirm contact history before outreach.",
                    "proof_required": "Queue proof required.",
                    "do_not_send_because": "Status is not approved for live outreach.",
                }
            ],
            "sequence_assignments": {"ben": {"result": "assigned", "evidence": "receipt.csv"}},
        }

        rows = command_center.build_communication_control_board(
            report,
            owner_decisions={},
            failed_clients={},
            rollout_reconciliation={},
            sequence_assignments=report["sequence_assignments"],
        )

        self.assertEqual(rows[0]["communication_status"], "Needs Brandon")
        self.assertEqual(rows[0]["mobile_app_sms_allowed"], "no")
        self.assertIn("Sequence assignment receipt exists", rows[0]["block_reason"])

    def test_no_recent_contact_investigation_treats_dry_run_as_nonproof(self) -> None:
        report = {
            "ledger": [
                {
                    "client_key": "name:ben",
                    "client_name": "Ben",
                    "next_touch_status": "no-recent-contact-found",
                }
            ],
            "sequence_assignments": {
                "ben": {
                    "customer_id": "contact-1",
                    "result": "assigned",
                    "evidence": "sequence.csv",
                }
            },
        }
        dry_runs = {"contact-1": {"timestamp": "2026-05-02T07:22:32-0500", "channel": "Email", "evidence": "bridge.jsonl"}}

        rows = command_center.no_recent_contact_investigations(report, dry_runs_by_contact=dry_runs)

        self.assertEqual(rows[0]["status"], "owner_review_required")
        self.assertEqual(rows[0]["delivered_message_proof"], "no")
        self.assertEqual(rows[0]["sequence_assignment"], "assigned")
        self.assertEqual(rows[0]["dry_run_found"], "yes")
        self.assertIn("Keep Needs Brandon", rows[0]["recommended_resolution"])

    def test_held_clients_never_become_send_ready(self) -> None:
        row = {"client_name": "Vera Davis", "next_touch_status": "owner-review-before-message"}
        decisions = {"vera davis": {"owner_decision": "hold"}}

        status, owner, next_step, _proof = command_center.work_queue_status_for_ledger_row(
            row,
            owner_decisions=decisions,
            failed_clients={},
        )

        self.assertEqual(status, "Hold")
        self.assertEqual(owner, "Brandon")
        self.assertIn("Do not send", next_step)

    def test_app_sms_failure_blocks_broad_rollout_row(self) -> None:
        row = {"client_name": "Anthony Williams", "next_touch_status": "owner-review-before-message"}

        status, owner, next_step, proof = command_center.work_queue_status_for_ledger_row(
            row,
            owner_decisions={"anthony williams": {"owner_decision": "approved"}},
            failed_clients={"anthony williams": "receipt.md"},
        )

        self.assertEqual(status, "Failed")
        self.assertEqual(owner, "FUNDz")
        self.assertIn("App SMS", next_step)
        self.assertIn("Failure receipt", proof)

    def test_app_recovery_proof_closes_failed_rollout_row(self) -> None:
        report = {
            "generated_at": "2026-05-12T13:15:00-0500",
            "ledger": [
                {
                    "client_key": "name:anthony-williams",
                    "client_name": "Anthony Williams",
                    "next_touch_status": "owner-review-before-message",
                    "phase": "onboarding",
                    "priority_score": "165",
                    "flags": "onboarding_incomplete",
                }
            ],
            "blockers": [],
        }

        with (
            mock.patch.object(command_center, "load_owner_decisions", return_value={"anthony williams": {"owner_decision": "approved"}}),
            mock.patch.object(command_center, "load_queue_suppressions", return_value={}),
            mock.patch.object(command_center, "failed_rollout_clients", return_value={}),
            mock.patch.object(command_center, "app_recovery_proofs", return_value={"anthony williams": "proof.md"}),
            mock.patch.object(command_center, "highlevel_reply_work_queue_rows", return_value=[]),
        ):
            rows = command_center.build_work_queue(report)

        self.assertEqual(rows[0]["queue_status"], "Done")
        self.assertEqual(rows[0]["proof"], "proof.md")
        self.assertEqual(rows[0]["evidence"], "proof.md")
        self.assertIn("app_access_proof_captured", rows[0]["safe_fix_applied"])

    def test_queue_suppression_overrides_failed_row_without_deleting_evidence(self) -> None:
        report = {
            "generated_at": "2026-05-06T10:00:00-0500",
            "ledger": [
                {
                    "client_key": "name:anthony-williams",
                    "client_name": "Anthony Williams",
                    "next_touch_status": "owner-review-before-message",
                    "phase": "onboarding",
                    "priority_score": "165",
                    "flags": "onboarding_incomplete",
                }
            ],
            "blockers": [],
        }
        suppression = {
            "anthony williams": {
                "client_name": "Anthony Williams",
                "client_key": "name:anthony-williams",
                "queue_status": "Done",
                "owner": "Brandon",
                "next_step": "Ignore Anthony for now.",
                "proof_required": "Brandon suppression decision recorded.",
                "proof": "Brandon said ignore Anthony.",
                "evidence": "suppressions.csv",
                "do_not_send_because": "Suppressed by Brandon.",
            }
        }

        with (
            mock.patch.object(command_center, "load_owner_decisions", return_value={"anthony williams": {"owner_decision": "approved"}}),
            mock.patch.object(command_center, "load_queue_suppressions", return_value=suppression),
            mock.patch.object(command_center, "failed_rollout_clients", return_value={"anthony williams": "receipt.md"}),
            mock.patch.object(command_center, "highlevel_reply_work_queue_rows", return_value=[]),
        ):
            rows = command_center.build_work_queue(report)

        row = rows[0]
        self.assertEqual(row["queue_status"], "Done")
        self.assertEqual(row["owner"], "Brandon")
        self.assertEqual(row["evidence"], "suppressions.csv")
        self.assertEqual(row["browser_required"], "no")
        self.assertIn("operator_suppression", row["safe_fix_applied"])

    def test_governor_marks_missing_proof_as_proof_needed(self) -> None:
        rows = [
            {
                "work_order_id": "WO-1",
                "queue_status": "Sent",
                "owner": "FUNDz",
                "next_step": "Done.",
                "updated_at": datetime.now().isoformat(),
            }
        ]

        fixed, alerts = command_center.governor_safe_fix_queue(rows)

        self.assertEqual(fixed[0]["queue_status"], "Proof Needed")
        self.assertIn("required_missing_proof", fixed[0]["safe_fix_applied"])
        self.assertTrue(alerts)

    def test_approved_clean_row_remains_approved(self) -> None:
        rows = [
            {
                "work_order_id": "WO-2",
                "queue_status": "Approved",
                "owner": "FUNDz",
                "next_step": "Prepare next safe batch.",
                "updated_at": datetime.now().isoformat(),
                "do_not_send_because": "",
            }
        ]

        fixed, alerts = command_center.governor_safe_fix_queue(rows)

        self.assertEqual(fixed[0]["queue_status"], "Approved")
        self.assertFalse(fixed[0].get("safe_fix_applied"))
        self.assertEqual(alerts, [])

    def test_governor_flags_stale_work(self) -> None:
        rows = [
            {
                "work_order_id": "WO-3",
                "queue_status": "Approved",
                "owner": "FUNDz",
                "next_step": "Review.",
                "updated_at": (datetime.now() - timedelta(hours=25)).isoformat(),
            }
        ]

        fixed, alerts = command_center.governor_safe_fix_queue(rows)

        self.assertIn("stale_over_24h", fixed[0]["safe_fix_applied"])
        self.assertTrue(any(alert["reason"] == "stale-work" for alert in alerts))

    def test_send_kill_switch_blocks_next_send_queue(self) -> None:
        packet = {
            "batch_id": "batch-1",
            "channel": "Email",
            "approval_required": True,
            "live_send_allowed": False,
            "items": [
                {
                    "client_name": "Ada Lovelace",
                    "channel": "Email",
                    "message": "Hi Ada, quick FUNDz update.",
                    "message_phase": "next_round",
                    "status": "Due For Next Round",
                    "stage_in_process": "Round 2 Ready",
                    "send_ready": True,
                    "outbound_payload_preview": {"subject": "FUNDz update"},
                }
            ],
        }
        kill_switch = {"enabled": True, "status": "KILL_SWITCH_ON"}

        rows = command_center.build_next_send_queue(packet, kill_switch)

        self.assertEqual(rows[0]["send_allowed_now"], "no")
        self.assertIn("kill switch is ON", rows[0]["blocked_reason"])
        self.assertEqual(rows[0]["message_body"], "Hi Ada, quick FUNDz update.")

    def test_send_kill_switch_reads_control_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "kill.json"
            path.write_text(
                json.dumps({"enabled": True, "reason": "Owner pause", "owner": "Brandon"}),
                encoding="utf-8",
            )

            state = command_center.send_kill_switch_state(path)

        self.assertTrue(state["enabled"])
        self.assertEqual(state["status"], "KILL_SWITCH_ON")
        self.assertEqual(state["reason"], "Owner pause")


if __name__ == "__main__":
    unittest.main()
