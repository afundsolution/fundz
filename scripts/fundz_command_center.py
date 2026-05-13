#!/usr/bin/env python3
"""Build a daily FUNDz command-center report from local operational evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fundz_autofox_audit import audit_records, load_records as load_autofox_records, newest_candidate_files, normalize
from fundz_credit_tracker_bridge import load_env_file
from fundz_operational_state import build_operational_state, relative_label, write_json, write_summary_csv
from fundz_semi_autonomous_bot import (
    OWNER_PRE_SEND_NOTICE_RECEIPTS,
    build_action_queue,
    owner_pre_send_notice_seconds,
    packet_notice_key,
    read_owner_pre_send_notices,
)
from scorefusion_billing_dashboard import build_dashboard as build_scorefusion_dashboard


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "local" / "command-center"
COMMAND_CENTER_JSON = OUTPUT_DIR / "fundz-command-center.json"
COMMAND_CENTER_MD = OUTPUT_DIR / "fundz-command-center.md"
TODAY_OPERATING_BOARD_MD = OUTPUT_DIR / "fundz-today-operating-board.md"
TODAY_DECISION_QUEUE_CSV = OUTPUT_DIR / "fundz-today-decision-queue.csv"
DAILY_BOARD_MD = OUTPUT_DIR / "fundz-daily-board.md"
CONTACT_LEDGER_CSV = OUTPUT_DIR / "fundz-contact-ledger.csv"
WORK_QUEUE_CSV = OUTPUT_DIR / "fundz-work-queue.csv"
WORK_QUEUE_SHEET_IMPORT_CSV = OUTPUT_DIR / "fundz-work-queue-google-sheet-import.csv"
GOVERNOR_SAFE_FIXES_MD = OUTPUT_DIR / "fundz-governor-safe-fixes.md"
GOVERNOR_ALERTS_CSV = OUTPUT_DIR / "fundz-governor-alerts.csv"
PILOT_REPORT_MD = OUTPUT_DIR / "fundz-pilot-status.md"
WEEKLY_SUMMARY_MD = OUTPUT_DIR / "fundz-weekly-owner-summary.md"
RELEASE_CHECKLIST_MD = OUTPUT_DIR / "fundz-pre-send-release-checklist.md"
OWNER_REVIEW_CSV = OUTPUT_DIR / "fundz-owner-review-queue.csv"
NO_RECENT_CONTACT_CSV = OUTPUT_DIR / "fundz-no-recent-contact-exceptions.csv"
SAFE_BATCH_CSV = OUTPUT_DIR / "fundz-next-safe-batch-candidates.csv"
AUTOFOX_MIGRATION_MD = OUTPUT_DIR / "fundz-autofox-mobile-app-migration-checklist.md"
MEMBER_EXPERIENCE_MD = OUTPUT_DIR / "fundz-autofox-member-experience-system.md"
MEMBER_EXPERIENCE_TIPS_CSV = OUTPUT_DIR / "fundz-autofox-credit-tips-round1-10.csv"
OWNER_REVIEW_ACTIONS_MD = OUTPUT_DIR / "fundz-autofox-owner-review-actions.md"
OWNER_REVIEW_ACTIONS_CSV = OUTPUT_DIR / "fundz-autofox-owner-review-actions.csv"
OWNER_REVIEW_PACKET_MD = OUTPUT_DIR / "fundz-owner-review-packet.md"
OWNER_DECISION_QUEUE_CSV = OUTPUT_DIR / "fundz-owner-decision-queue.csv"
OWNER_DECISION_PACKET_MD = OUTPUT_DIR / "fundz-owner-decision-packet.md"
NO_RECENT_CONTACT_INVESTIGATION_MD = OUTPUT_DIR / "fundz-no-recent-contact-investigation.md"
NO_RECENT_CONTACT_INVESTIGATION_CSV = OUTPUT_DIR / "fundz-no-recent-contact-investigation.csv"
QUEUE_SUPPRESSIONS_CSV = OUTPUT_DIR / "fundz-work-queue-suppressions.csv"
GAP_CLOSURE_MD = OUTPUT_DIR / "fundz-gap-closure-plan.md"
NO_APPROVAL_WORK_CSV = OUTPUT_DIR / "fundz-no-approval-work-queue.csv"
MISSING_STEPS_RECHECK_MD = OUTPUT_DIR / "fundz-missing-steps-recheck.md"
BUSINESS_REVIEW_ROLLOUT_MD = OUTPUT_DIR / "fundz-business-review-controlled-rollout.md"
PREVIEW_PACKET_DECISION_MD = OUTPUT_DIR / "fundz-preview-packet-decision.md"
BILLING_ROLLOUT_TRIAGE_MD = OUTPUT_DIR / "fundz-billing-rollout-triage.md"
BILLING_ROLLOUT_TRIAGE_CSV = OUTPUT_DIR / "fundz-billing-rollout-triage.csv"
BILLING_MAINTENANCE_FOCUS_MD = OUTPUT_DIR / "fundz-billing-maintenance-focus.md"
BILLING_MAINTENANCE_FOCUS_CSV = OUTPUT_DIR / "fundz-billing-maintenance-focus.csv"
CLEAN_BACKUP_PREVIEW_MD = OUTPUT_DIR / "fundz-clean-preview-backup-candidates.md"
CLEAN_BACKUP_PREVIEW_CSV = OUTPUT_DIR / "fundz-clean-preview-backup-candidates.csv"
SEND_VISIBILITY_MD = OUTPUT_DIR / "fundz-send-visibility-command-center.md"
SEND_LEDGER_CSV = OUTPUT_DIR / "fundz-send-ledger.csv"
NEXT_SEND_QUEUE_CSV = OUTPUT_DIR / "fundz-next-send-queue.csv"
SEND_KILL_SWITCH_MD = OUTPUT_DIR / "fundz-send-kill-switch.md"
SEND_KILL_SWITCH_JSON = OUTPUT_DIR / "fundz-send-kill-switch.json"
SEND_GATE_LOCK_MD = OUTPUT_DIR / "fundz-send-gate-lock.md"
ARCHIVE_RECEIPT_TRAIL_MD = OUTPUT_DIR / "fundz-archive-receipt-trail.md"
LIVE_HOLD_CLEANUP_MD = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-live-hold-cleanup.md"
LIVE_HOLD_CLEANUP_CSV = ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-live-hold-cleanup.csv"
MAINTENANCE_CLEANUP_MD = ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-cleanup-board.md"
MAINTENANCE_CLEANUP_SUMMARY_JSON = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-cleanup-summary.json"
)
BILLING_MAINTENANCE_REVIEW_CSV = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-billing-maintenance-review.csv"
)
DUPLICATE_BILLING_REVIEW_CSV = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-duplicate-billing-review.csv"
)
ACTIVE_BILLING_ISSUES_CSV = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-active-billing-issues.csv"
)
NON_ACTIVE_BILLING_REVIEW_CSV = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-non-active-billing-review.csv"
)
AUTONOMY_STATUS_JSON = ROOT / "data" / "local" / "autonomy" / "fundz-autonomous-operator-status.json"
AUTONOMY_STATUS_MD = ROOT / "data" / "local" / "autonomy" / "fundz-autonomous-operator-status.md"
MAINTENANCE_AUTOPILOT_STATUS_JSON = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-autopilot-status.json"
)
MAINTENANCE_AUTOPILOT_STATUS_MD = (
    ROOT / "data" / "local" / "maintenance-cleanup" / "fundz-maintenance-autopilot-status.md"
)
OWNER_APPROVAL_DECISIONS_CSV = OUTPUT_DIR / "fundz-owner-approval-decisions-20260505.csv"
FULL_ROLLOUT_RECONCILIATION_CSV = OUTPUT_DIR / "fundz-full-180-app-email-rollout-reconciliation-20260505.csv"
COMMUNICATION_CONTROL_BOARD_MD = OUTPUT_DIR / "fundz-client-communication-control-board.md"
COMMUNICATION_CONTROL_BOARD_CSV = OUTPUT_DIR / "fundz-client-communication-control-board.csv"
RECEIPTS_DIR = ROOT / "data" / "local" / "semi-autonomous" / "receipts"
POLLER_LOG = ROOT / "logs" / "highlevel-inbox-poller.jsonl"
HIGHLEVEL_REPLY_QUEUE_JSONL = ROOT / "data" / "local" / "highlevel-inbox-poller" / "classified-replies.jsonl"
HIGHLEVEL_REPLY_RECEIPTS_JSONL = ROOT / "data" / "local" / "highlevel-inbox-poller" / "reply-receipts.jsonl"
HIGHLEVEL_REPLY_DECISIONS_CSV = ROOT / "data" / "local" / "highlevel-inbox-poller" / "reply-decisions.csv"
BRIDGE_LOG = ROOT / "logs" / "credit-tracker-bridge.jsonl"
STATE_JSON = ROOT / "data" / "local" / "fundz-client-state.json"
SUMMARY_CSV = ROOT / "data" / "local" / "fundz-client-state-summary.csv"
EXPANSION_BATCH_PACKET = ROOT / "data" / "local" / "semi-autonomous" / "expansion-batch-packet.json"
EXPANSION_BATCH_PREVIEW_MD = ROOT / "data" / "local" / "semi-autonomous" / "expansion-batch-preview.md"
BILLING_RISK_REVIEW_CSV = ROOT / "data" / "local" / "scorefusion-billing-dashboard" / "billing-risk-review-queue.csv"
STALE_IMPORT_ARCHIVE_REVIEW_MD = (
    ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-stale-import-archive-review.md"
)
STALE_IMPORT_ARCHIVE_REVIEW_CSV = (
    ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-stale-import-archive-review.csv"
)
STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV = (
    ROOT / "data" / "local" / "autofox-rollout" / "df-autofox-stale-import-archive-exclusions.csv"
)

PILOT_NAMES = {
    "anitra thomas",
    "ashley stancil",
    "brenda taylor",
    "deja eaton",
    "jasmine neeley",
}

OWNER_REVIEW_FLAGS = {
    "payment_attention",
    "setup_incomplete",
    "onboarding_incomplete",
    "missing_next_import",
}

QUEUE_STATUSES = (
    "Hold",
    "Needs Brandon",
    "Approved",
    "Sent",
    "Proof Needed",
    "Failed",
    "Blocked",
    "Done",
)

QUEUE_DONE_REQUIRES_PROOF = {"Sent", "Done"}

GOVERNOR_SAFE_FIX_POLICY = (
    "Governor may aggressively correct queue hygiene, status, proof, owner, due-date, "
    "dedupe, and escalation gaps. Governor must not send client messages, assign "
    "campaigns, edit client records, change billing/dispute strategy, disable live "
    "AutoFox actions, override DND/opt-out, or use new secrets/cloud permissions."
)

PROOF_NEEDED_INBOUND_RE = re.compile(
    r"\b(?:score|credit\s+score|changed|change|deleted?|collection|tradeline|report|round|bureau|experian|equifax|transunion)\b",
    re.I,
)

BACKLOG_AREAS = (
    "Immediate Live-Pilot Work",
    "HighLevel + Inbox Intelligence",
    "Credit Tracker / App-First Messaging",
    "Semi-Autonomous Outreach Engine",
    "AutoFox / DisputeFox Workflow Cleanup",
    "Cloudflare + Webhook Hardening",
    "Supabase / Durable Memory",
    "ScoreFusion Billing Power-Ups",
    "Command Center / Operator UX",
    "Safety, Tests, and Release Discipline",
)

ROUND_WORKFLOWS = (
    {"round": 1, "lane": "Round Updates", "workflow": "Client (step 04) - Round 1 Sent & Campaign", "autofox_id": "160038", "mobile_app_status": "verified", "score_update_id": "160040"},
    {"round": 2, "lane": "Round Updates", "workflow": "Client (step 06) - Round 2 Sent & Campaign", "autofox_id": "160044", "mobile_app_status": "verified", "score_update_id": "160042"},
    {"round": 3, "lane": "Round Updates", "workflow": "Client (step 08) - Round 3 Sent & Campaign", "autofox_id": "160054", "mobile_app_status": "verified", "score_update_id": "160043"},
    {"round": 4, "lane": "Round Updates", "workflow": "Client (step 10) - Round 4 Sent & Campaign", "autofox_id": "160055", "mobile_app_status": "verified", "score_update_id": "160056"},
    {"round": 5, "lane": "Round Updates", "workflow": "Client (step 12) - Round 5 Sent & Campaign", "autofox_id": "160061", "mobile_app_status": "verified", "score_update_id": "needs DF confirmation"},
    {"round": 6, "lane": "Round Updates", "workflow": "Client (step 14) - Round 6 Sent & Campaign", "autofox_id": "160063", "mobile_app_status": "verified", "score_update_id": "160064"},
    {"round": 7, "lane": "Round Updates", "workflow": "Client (step 16) - Round 7 Sent & Campaign", "autofox_id": "160065", "mobile_app_status": "verified", "score_update_id": "160066"},
    {"round": 8, "lane": "Round Updates", "workflow": "Client (step 18) - Round 8 Sent & Campaign", "autofox_id": "160067", "mobile_app_status": "verified", "score_update_id": "160068"},
    {"round": 9, "lane": "Round Updates", "workflow": "Client (step 20) - Round 9 Sent & Campaign", "autofox_id": "160069", "mobile_app_status": "verified", "score_update_id": "160070"},
    {"round": 10, "lane": "Round Updates", "workflow": "Client (step 22) - Round 10 Sent & Campaign", "autofox_id": "160071", "mobile_app_status": "verified", "score_update_id": "160072"},
)

CREDIT_TIPS = (
    {"round": 1, "tip": 1, "delay_days": 3, "topic": "App habit", "action_name": "Credit Tip 01 - App Habit", "message": "Credit Tip 1:\nYour Credit Tracker app is the best place to watch updates. Alerts can show differently depending on the bureau and monitoring source.\n\nQuick action:\nCheck the app before assuming something is good or bad."},
    {"round": 1, "tip": 2, "delay_days": 10, "topic": "Payment history", "action_name": "Credit Tip 02 - Payment History", "message": "Credit Tip 2:\nOn-time payments are one of the biggest parts of a credit profile.\n\nQuick action:\nKeep all current accounts paid on time while your dispute round is active."},
    {"round": 2, "tip": 3, "delay_days": 3, "topic": "Utilization", "action_name": "Credit Tip 03 - Utilization", "message": "Credit Tip 3:\nCredit card balances can affect scores when they report. Lower balances compared to limits may help your profile look stronger over time.\n\nQuick action:\nAvoid maxing out cards while we work your file."},
    {"round": 2, "tip": 4, "delay_days": 10, "topic": "Statement dates", "action_name": "Credit Tip 04 - Statement Dates", "message": "Credit Tip 4:\nA card payment may not show in monitoring right away. Many cards report around the statement date.\n\nQuick action:\nGive balance updates time to report before worrying."},
    {"round": 3, "tip": 5, "delay_days": 3, "topic": "New credit", "action_name": "Credit Tip 05 - New Credit", "message": "Credit Tip 5:\nNew applications can add inquiries and may affect how your file looks.\n\nQuick action:\nAvoid applying for new credit unless it is truly needed."},
    {"round": 3, "tip": 6, "delay_days": 10, "topic": "Alerts", "action_name": "Credit Tip 06 - Alerts", "message": "Credit Tip 6:\nNot every alert means bad news. Some alerts only mean information changed or updated.\n\nQuick action:\nSend confusing alerts through the app so we can review them."},
    {"round": 4, "tip": 7, "delay_days": 3, "topic": "Account age", "action_name": "Credit Tip 07 - Account Age", "message": "Credit Tip 7:\nOlder positive accounts can help support a credit profile.\n\nQuick action:\nAsk before closing old accounts so you understand how it could affect your file."},
    {"round": 4, "tip": 8, "delay_days": 10, "topic": "Collections", "action_name": "Credit Tip 08 - Collections", "message": "Credit Tip 8:\nIf a collector contacts you, do not panic or agree to anything you do not understand.\n\nQuick action:\nSave the notice and send it through the app for review."},
    {"round": 5, "tip": 9, "delay_days": 3, "topic": "Credit mix", "action_name": "Credit Tip 09 - Credit Mix", "message": "Credit Tip 9:\nCredit profiles are reviewed as a full picture: payment history, balances, account age, account types, and recent activity.\n\nQuick action:\nFocus on steady habits, not one single alert."},
    {"round": 5, "tip": 10, "delay_days": 10, "topic": "Bureau timing", "action_name": "Credit Tip 10 - Bureau Timing", "message": "Credit Tip 10:\nExperian, Equifax, and TransUnion can update at different speeds.\n\nQuick action:\nLet us review the full report before reacting to one bureau change."},
    {"round": 6, "tip": 11, "delay_days": 3, "topic": "Dispute patience", "action_name": "Credit Tip 11 - Dispute Patience", "message": "Credit Tip 11:\nDispute rounds take time because bureaus and furnishers do not all respond at the same pace.\n\nQuick action:\nKeep checking the app and avoid sending duplicate disputes yourself."},
    {"round": 6, "tip": 12, "delay_days": 10, "topic": "Documentation", "action_name": "Credit Tip 12 - Documentation", "message": "Credit Tip 12:\nGood documentation helps protect your progress.\n\nQuick action:\nUpload or send any new letters, alerts, or creditor notices through the app."},
    {"round": 7, "tip": 13, "delay_days": 3, "topic": "Address consistency", "action_name": "Credit Tip 13 - Address Consistency", "message": "Credit Tip 13:\nConsistent personal information can make your file easier to review.\n\nQuick action:\nLet us know if your name, address, phone, or email changes."},
    {"round": 7, "tip": 14, "delay_days": 10, "topic": "Hard vs soft inquiries", "action_name": "Credit Tip 14 - Hard vs Soft Inquiries", "message": "Credit Tip 14:\nHard inquiries usually come from applying for credit. Soft inquiries are usually checks or monitoring and normally do not affect scores the same way.\n\nQuick action:\nAsk before applying if you are unsure."},
    {"round": 8, "tip": 15, "delay_days": 3, "topic": "Authorized users", "action_name": "Credit Tip 15 - Authorized Users", "message": "Credit Tip 15:\nAn authorized-user account can help or hurt depending on its balance, age, and payment history.\n\nQuick action:\nDo not add or remove one without checking the details first."},
    {"round": 8, "tip": 16, "delay_days": 10, "topic": "Secured cards", "action_name": "Credit Tip 16 - Secured Cards", "message": "Credit Tip 16:\nA secured card can help build payment history when used carefully, but high balances can still hurt.\n\nQuick action:\nKeep balances low and pay on time if you use one."},
    {"round": 9, "tip": 17, "delay_days": 3, "topic": "Credit freezes", "action_name": "Credit Tip 17 - Credit Freezes", "message": "Credit Tip 17:\nA credit freeze can help protect against unwanted new accounts, but it may need to be lifted before applying for credit.\n\nQuick action:\nAsk before freezing or unfreezing if you are unsure."},
    {"round": 9, "tip": 18, "delay_days": 10, "topic": "Identity alerts", "action_name": "Credit Tip 18 - Identity Alerts", "message": "Credit Tip 18:\nNew-account or identity alerts should be reviewed quickly.\n\nQuick action:\nSend screenshots or notices through the app if something looks unfamiliar."},
    {"round": 10, "tip": 19, "delay_days": 3, "topic": "Maintenance", "action_name": "Credit Tip 19 - Maintenance", "message": "Credit Tip 19:\nCredit progress needs protection after each round.\n\nQuick action:\nKeep payments current, keep balances controlled, and check the app before major credit moves."},
    {"round": 10, "tip": 20, "delay_days": 10, "topic": "Long-term habits", "action_name": "Credit Tip 20 - Long-Term Habits", "message": "Credit Tip 20:\nStrong credit is built by consistent habits over time.\n\nQuick action:\nKeep using the app for updates, questions, and new notices so your file stays organized."},
)

OWNER_REVIEW_ACTIONS = (
    {
        "condition": "Billing issue",
        "internal_action_name": "Owner Review - Billing Issue",
        "action_type": "Create Task",
        "priority": "High",
        "task_note": "Review billing status before normal progress or education messages continue.",
        "member_message": "Hi [FIRST-NAME], your file may need a quick account review before we give the next full update. We are checking it so we do not give you the wrong information.",
    },
    {
        "condition": "App SMS failed",
        "internal_action_name": "Owner Review - App SMS Failed",
        "action_type": "Create Task",
        "priority": "High",
        "task_note": "Check app installed/logged-in status and use app invitation or email fallback before another Mobile App SMS attempt.",
        "member_message": "",
    },
    {
        "condition": "No app login",
        "internal_action_name": "Owner Review - No App Login",
        "action_type": "Create Task",
        "priority": "Medium",
        "task_note": "Send or confirm app invitation, then hold Mobile App SMS-only updates until installed/logged in.",
        "member_message": "Hi [FIRST-NAME], quick setup reminder from FUNDz. Please check your Credit Tracker app and complete any missing setup items so we can keep your file moving. If you need help, reply in the app.",
    },
    {
        "condition": "No import",
        "internal_action_name": "Owner Review - Missing Credit Tracker Import",
        "action_type": "Create Task",
        "priority": "High",
        "task_note": "Confirm whether Credit Tracker import is missing, stale, or failed before sending round/score language.",
        "member_message": "Hi [FIRST-NAME], quick setup reminder from FUNDz. Please check your Credit Tracker app and complete any missing setup items so we can keep your file moving. If you need help, reply in the app.",
    },
    {
        "condition": "No response",
        "internal_action_name": "Owner Review - No Response",
        "action_type": "Create Task",
        "priority": "Medium",
        "task_note": "Review recent emails, app messages, calls, and DND/opt-out before adding another follow-up.",
        "member_message": "",
    },
    {
        "condition": "Possible duplicate messaging",
        "internal_action_name": "Owner Review - Duplicate Messaging Risk",
        "action_type": "Create Task",
        "priority": "High",
        "task_note": "Check current AutoFox history and active workflows before assigning or restarting any communication campaign.",
        "member_message": "",
    },
    {
        "condition": "Stale round",
        "internal_action_name": "Owner Review - Stale Round",
        "action_type": "Create Task",
        "priority": "High",
        "task_note": "Confirm last letters printed/sent, next import, and current round before giving the next update.",
        "member_message": "Hi [FIRST-NAME], your file may need a quick account review before we give the next full update. We are checking it so we do not give you the wrong information.",
    },
    {
        "condition": "Client confusion/high-touch",
        "internal_action_name": "Owner Review - High Touch / Confusion",
        "action_type": "Create Task",
        "priority": "Medium",
        "task_note": "Review conversation history and prepare one clear app/email reply instead of sending normal automated updates.",
        "member_message": "Hi [FIRST-NAME], your file may need a quick account review before we give the next full update. We are checking it so we do not give you the wrong information.",
    },
)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_allowed_reporting_screen(screen: Any) -> bool:
    return str(screen or "").strip() == "fundz-command-center"


def is_allowed_reporting_process(process: Any) -> bool:
    text = str(process or "")
    if "fundz_command_center_server.py" in text:
        return True
    if "scripts/fundz_command_center_server.py" in text:
        return True
    if "SCREEN" in text and "fundz-command-center" in text:
        return True
    if "cloudflared" in text and "fundz-command-center.yml" in text:
        return True
    return False


def filter_runtime_findings(
    findings: list[Any],
    *,
    allowed_reporting_runtime: bool,
) -> list[str]:
    filtered: list[str] = []
    for item in findings:
        finding = str(item)
        lowered = finding.lower()
        generic_reporting_match = (
            "live fundz screen session" in lowered
            or "live fundz runtime process" in lowered
            or "unsafe: live fundz screen" in lowered
            or "unsafe: live fundz runtime" in lowered
        )
        if allowed_reporting_runtime and generic_reporting_match:
            continue
        filtered.append(finding)
    return filtered


def build_safety_gate_snapshot() -> dict[str, Any]:
    autonomy = read_json(AUTONOMY_STATUS_JSON)
    if not isinstance(autonomy, dict):
        autonomy = {}
    maintenance = read_json(MAINTENANCE_AUTOPILOT_STATUS_JSON)
    if not isinstance(maintenance, dict):
        maintenance = {}

    runtime = autonomy.get("runtime") if isinstance(autonomy.get("runtime"), dict) else {}
    rollout = maintenance.get("rollout_packet") if isinstance(maintenance.get("rollout_packet"), dict) else {}
    if not rollout:
        nested_maintenance = autonomy.get("maintenance") if isinstance(autonomy.get("maintenance"), dict) else {}
        rollout = nested_maintenance.get("rollout_packet") if isinstance(nested_maintenance.get("rollout_packet"), dict) else {}

    raw_safety_findings = autonomy.get("safety_findings") if isinstance(autonomy.get("safety_findings"), list) else []
    live_send_allowed = bool(rollout.get("live_send_allowed"))
    selected = safe_int(rollout.get("selected"))
    approval_required = rollout.get("approval_required", True)
    active_screens = runtime.get("active_screens") if isinstance(runtime.get("active_screens"), list) else []
    active_processes = runtime.get("active_processes") if isinstance(runtime.get("active_processes"), list) else []
    unexpected_screens = [str(screen) for screen in active_screens if not is_allowed_reporting_screen(screen)]
    unexpected_processes = [str(process) for process in active_processes if not is_allowed_reporting_process(process)]
    allowed_reporting_runtime = bool(active_screens or active_processes) and not unexpected_screens and not unexpected_processes
    safety_findings = filter_runtime_findings(
        raw_safety_findings,
        allowed_reporting_runtime=allowed_reporting_runtime,
    )
    runtime_quiet = bool(runtime.get("quiet", True)) or allowed_reporting_runtime

    if live_send_allowed or selected:
        state = "Live-send review"
        note = "A rollout has selected rows or live send is allowed; require action-time owner approval before any send."
    elif safety_findings or unexpected_screens or unexpected_processes:
        state = "Review local runtime"
        note = "Local reporting is awake, but the latest autonomy status flagged a FUNDz runtime. Do not treat this as live-send clearance."
    elif allowed_reporting_runtime:
        state = "Local reporting safe"
        note = "Only the allowed dashboard/reporting runtime is active; client sends remain off and approval gates still apply."
    elif autonomy.get("ok") is True and runtime_quiet:
        state = "Local safe"
        note = "Local boards are clean and no live runtime was flagged in the last status."
    else:
        state = "Local reporting only"
        note = "Client sends remain off; use this as an operating board, not live-send clearance."

    return {
        "state": state,
        "note": note,
        "generated_at": autonomy.get("generated_at") or maintenance.get("generated_at") or "",
        "autonomy_ok": bool(autonomy.get("ok")),
        "maintenance_ok": bool(maintenance.get("ok")),
        "successful_steps": safe_int(autonomy.get("successful_steps")),
        "total_steps": safe_int(autonomy.get("total_steps")),
        "maintenance_steps": f"{safe_int(maintenance.get('successful_steps'))}/{safe_int(maintenance.get('total_steps'))}",
        "approval_required": bool(approval_required),
        "live_send_allowed": live_send_allowed,
        "rollout_selected": selected,
        "runtime_quiet": runtime_quiet,
        "runtime_quiet_raw": bool(runtime.get("quiet", True)),
        "allowed_reporting_runtime": allowed_reporting_runtime,
        "active_screens": active_screens,
        "active_processes": active_processes,
        "unexpected_runtime_screens": unexpected_screens,
        "unexpected_runtime_processes": unexpected_processes,
        "safety_findings": [str(item) for item in safety_findings],
        "status_path": relative_label(AUTONOMY_STATUS_MD),
        "maintenance_status_path": relative_label(MAINTENANCE_AUTOPILOT_STATUS_MD),
    }


def read_jsonl(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def latest_receipt_file(pattern: str) -> Path | None:
    matches = sorted(RECEIPTS_DIR.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def load_sequence_assignment_receipts(pattern: str = "download-mobile-app-sequence-send-log-*.csv") -> dict[str, dict[str, str]]:
    path = latest_receipt_file(pattern)
    if not path:
        return {}
    assignments: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        client_name = str(row.get("client_name") or "").strip()
        if not client_name:
            continue
        result = str(row.get("result") or "").strip()
        if result not in {"assigned", "already_present_or_assigned"}:
            continue
        assignments[normalize_name(client_name)] = {
            "client_name": client_name,
            "customer_id": str(row.get("customer_id") or "").strip(),
            "result": result,
            "detail": str(row.get("detail") or "").strip(),
            "timestamp": str(row.get("timestamp") or "").strip(),
            "evidence": relative_label(path),
        }
    return assignments


def load_bridge_dry_runs_by_contact(path: Path = BRIDGE_LOG) -> dict[str, dict[str, str]]:
    dry_runs: dict[str, dict[str, str]] = {}
    for row in read_jsonl(path, limit=5000):
        if row.get("kind") != "reply_dry_run":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        contact_id = str(payload.get("contactId") or payload.get("contact_id") or "").strip()
        if not contact_id:
            continue
        dry_runs[contact_id] = {
            "timestamp": str(row.get("time") or ""),
            "channel": str(payload.get("type") or ""),
            "evidence": relative_label(path),
        }
    return dry_runs


def load_owner_decisions(path: Path = OWNER_APPROVAL_DECISIONS_CSV) -> dict[str, dict[str, str]]:
    decisions: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        client_name = normalize_name(str(row.get("client_name") or ""))
        if client_name:
            decisions[client_name] = row
    return decisions


def load_rollout_reconciliation(path: Path = FULL_ROLLOUT_RECONCILIATION_CSV) -> dict[str, dict[str, str]]:
    reconciliation: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        client_name = normalize_name(str(row.get("client_name") or ""))
        client_key = str(row.get("client_key") or "").strip()
        if client_name:
            reconciliation[client_name] = row
        if client_key:
            reconciliation[client_key] = row
    return reconciliation


def load_queue_suppressions(path: Path = QUEUE_SUPPRESSIONS_CSV) -> dict[str, dict[str, str]]:
    suppressions: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        client_name = normalize_name(str(row.get("client_name") or ""))
        client_key = str(row.get("client_key") or "").strip()
        if client_name:
            suppressions[client_name] = row
        if client_key:
            suppressions[client_key] = row
    return suppressions


def failed_rollout_clients() -> dict[str, str]:
    """Collect known failed client rollout evidence from local receipts/notes."""
    failures: dict[str, str] = {}
    suppressions = load_queue_suppressions()
    recovered = app_recovery_proofs()
    send_log = RECEIPTS_DIR / "app-email-rollout-send-log-20260505.md"
    if send_log.exists():
        text = send_log.read_text(encoding="utf-8", errors="ignore")
        current_client = ""
        for line in text.splitlines():
            match = re.search(r"Client:\s*(.+)$", line)
            if match:
                current_client = normalize_name(match.group(1))
            if current_client and re.search(r"App SMS Sent`?:?\s*`?Failed", line, re.IGNORECASE):
                if current_client in suppressions:
                    continue
                if current_client in recovered:
                    continue
                failures[current_client] = relative_label(send_log)
    return failures


def app_recovery_proofs() -> dict[str, str]:
    """Collect DF Installed/Logged In proof receipts that close App SMS recovery rows."""
    proofs: dict[str, str] = {}
    for receipt in RECEIPTS_DIR.glob("*df-app-status-installed-logged-in-proof-*.md"):
        text = receipt.read_text(encoding="utf-8", errors="ignore")
        if "installed" not in text.lower() or "logged in" not in text.lower():
            continue
        match = re.search(r"Client:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        if not match:
            continue
        client_name = normalize_name(match.group(1))
        if client_name:
            proofs[client_name] = relative_label(receipt)
    return proofs


def row_id_for_queue(row: dict[str, Any], suffix: str = "OUTREACH") -> str:
    base = normalize_name(str(row.get("client_key") or row.get("client_name") or "unknown")).replace(" ", "-")
    return f"FUNDZ-{suffix}-{base[:60] or 'unknown'}".upper()


def work_queue_status_for_ledger_row(
    row: dict[str, Any],
    *,
    owner_decisions: dict[str, dict[str, str]],
    failed_clients: dict[str, str],
) -> tuple[str, str, str, str]:
    """Return queue status, owner, next step, and proof requirement."""
    name_key = normalize_name(str(row.get("client_name") or ""))
    owner_decision = (owner_decisions.get(name_key) or {}).get("owner_decision", "").strip().lower()
    next_touch = str(row.get("next_touch_status") or "")
    proof_required = "Queue row, approval/proof receipt, and no active blocker before client-facing action."

    if owner_decision == "hold":
        return "Hold", "Brandon", "Do not send. Re-review only if Brandon changes the hold decision.", proof_required
    if name_key in failed_clients:
        return "Failed", "FUNDz", "Investigate failed App SMS, confirm app installed/logged-in status, then choose invite/email fallback.", "Failure receipt and follow-up resolution proof required."
    if next_touch == "owner-review-before-message":
        if owner_decision == "approved":
            return "Approved", "FUNDz", "Prepare only a gated app/email action; do not broaden while global blockers remain.", proof_required
        return "Needs Brandon", "Brandon", "Review the client issue and choose approve, hold, or blocked.", proof_required
    if next_touch == "no-recent-contact-found":
        return (
            "Needs Brandon",
            "Brandon",
            "Owner review required: verify delivered-message/contact proof or explicitly override before outreach.",
            proof_required,
        )
    if next_touch == "prepare-owner-approved-next-round-touch":
        return "Approved", "FUNDz", "Prepare next-round touch after proof gates pass.", proof_required
    if next_touch == "monitor-and-touch-on-cadence":
        return "Approved", "FUNDz", "Keep on cadence; prepare draft only when send window and proof gates pass.", proof_required
    return "Done", "FUNDz", "Monitor only. Reopen if new issue, reply, import, or billing risk appears.", "Monitoring rationale and latest ledger row."


def build_work_queue(report: dict[str, Any]) -> list[dict[str, Any]]:
    generated_at = str(report.get("generated_at") or time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    owner_decisions = load_owner_decisions()
    suppressions = load_queue_suppressions()
    failures = failed_rollout_clients()
    recoveries = app_recovery_proofs()
    rows: list[dict[str, Any]] = []

    for ledger_row in report.get("ledger", []):
        name_key = normalize_name(str(ledger_row.get("client_name") or ""))
        status, owner, next_step, proof_required = work_queue_status_for_ledger_row(
            ledger_row,
            owner_decisions=owner_decisions,
            failed_clients=failures,
        )
        evidence = recoveries.get(name_key) or failures.get(name_key) or relative_label(CONTACT_LEDGER_CSV)
        row = {
            "work_order_id": row_id_for_queue(ledger_row),
            "created_at": generated_at,
            "updated_at": generated_at,
            "actor": "FUNDz",
            "system": "FUNDz",
            "lane": str(ledger_row.get("phase") or "client-outreach"),
            "queue_status": status,
            "client_key": ledger_row.get("client_key", ""),
            "client_name": ledger_row.get("client_name", ""),
            "source_status": ledger_row.get("next_touch_status", ""),
            "owner": owner,
            "due_date": generated_at[:10],
            "next_step": next_step,
            "proof_required": proof_required,
            "proof": "",
            "evidence": evidence,
            "priority_score": ledger_row.get("priority_score", ""),
            "flags": ledger_row.get("flags", ""),
            "browser_required": "yes" if status in {"Approved", "Failed", "Needs Brandon"} else "no",
            "do_not_send_because": do_not_send_reason_for_queue_status(status, report),
            "safe_fix_applied": "",
            "duplicate_of": "",
        }
        if name_key in recoveries:
            client_name = str(ledger_row.get("client_name") or "Client").strip() or "Client"
            row["queue_status"] = "Done"
            row["owner"] = "FUNDz"
            row["next_step"] = f"{client_name} app-access proof captured; do not broaden rollout without fresh action-time approval."
            row["proof_required"] = "DF app status proof captured; Mobile App SMS retry is optional and remains owner-gated."
            row["proof"] = recoveries[name_key]
            row["evidence"] = recoveries[name_key]
            row["browser_required"] = "no"
            row["do_not_send_because"] = "No broad rollout approval; Anthony proof only."
            row["safe_fix_applied"] = "app_access_proof_captured"
        suppression = first_lookup(
            [
                str(ledger_row.get("client_key") or ""),
                normalize_name(str(ledger_row.get("client_name") or "")),
            ],
            suppressions,
        )
        if suppression:
            row["queue_status"] = suppression.get("queue_status") or "Done"
            row["owner"] = suppression.get("owner") or row["owner"]
            row["next_step"] = suppression.get("next_step") or "Suppressed by Brandon; do not pursue unless reopened."
            row["proof_required"] = suppression.get("proof_required") or "Brandon suppression decision recorded."
            row["proof"] = suppression.get("proof") or suppression.get("reason", "")
            row["evidence"] = suppression.get("evidence") or relative_label(QUEUE_SUPPRESSIONS_CSV)
            row["browser_required"] = "no"
            row["do_not_send_because"] = suppression.get("do_not_send_because") or "Suppressed by Brandon."
            row["safe_fix_applied"] = "operator_suppression"
        rows.append(row)

    rows.extend(highlevel_reply_work_queue_rows(generated_at))
    rows.extend(system_blocker_queue_rows(report, generated_at))
    return sorted(rows, key=lambda item: (queue_status_order(str(item.get("queue_status"))), -safe_int(item.get("priority_score")), str(item.get("client_name")).lower()))


def highlevel_reply_status(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    classification = row.get("classification") if isinstance(row.get("classification"), dict) else {}
    labels = classification.get("labels") if isinstance(classification.get("labels"), list) else []
    message = str(row.get("message_preview") or "")
    proof_required = "HighLevel reply row plus Credit Tracker/DisputeFox/report proof before any client response."
    label_flags = ";".join(str(label) for label in labels)
    if classification.get("needs_brandon_reply"):
        return (
            "Needs Brandon",
            "Brandon",
            "Review sensitive inbound HighLevel reply before any client response.",
            proof_required,
            f"highlevel_inbox;client_reply;owner_review;{label_flags}".rstrip(";"),
        )
    if PROOF_NEEDED_INBOUND_RE.search(message):
        return (
            "Proof Needed",
            "FUNDz",
            "Verify current Credit Tracker/DisputeFox/report evidence, then draft a precise reply for Brandon approval if needed.",
            proof_required,
            f"highlevel_inbox;client_reply;proof_needed;{label_flags}".rstrip(";"),
        )
    return (
        "Needs Brandon",
        "Brandon",
        "Review the inbound HighLevel reply and approve the next response or mark no-action.",
        "HighLevel reply row and owner decision before client response.",
        f"highlevel_inbox;client_reply;review;{label_flags}".rstrip(";"),
    )


def load_highlevel_reply_decisions(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or HIGHLEVEL_REPLY_DECISIONS_CSV
    decisions: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        work_order_id = str(row.get("work_order_id") or "").strip()
        message_id = str(row.get("message_id") or "").strip()
        message_digest = str(row.get("message_digest") or "").strip().upper()
        keys = [work_order_id, message_id]
        if message_id:
            keys.append(f"FUNDZ-HL-{hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:12].upper()}")
        if message_digest:
            keys.append(message_digest if message_digest.startswith("FUNDZ-HL-") else f"FUNDZ-HL-{message_digest}")
        for key in keys:
            if key:
                decisions[key] = row
    return decisions


def append_flag(flags: str, flag: str) -> str:
    pieces = [piece for piece in str(flags or "").split(";") if piece]
    if flag not in pieces:
        pieces.append(flag)
    return ";".join(pieces)


def apply_highlevel_reply_decision(row: dict[str, Any], decision: dict[str, str]) -> dict[str, Any]:
    result = dict(row)
    decision_value = normalize_name(str(decision.get("decision") or ""))
    owner = str(decision.get("owner") or "Brandon").strip()
    proof = str(decision.get("proof") or decision.get("notes") or "HighLevel reply decision recorded.").strip()
    evidence = str(decision.get("evidence") or relative_label(HIGHLEVEL_REPLY_DECISIONS_CSV)).strip()
    proof_required = str(decision.get("proof_required") or "").strip()
    next_step = str(decision.get("next_step") or "").strip()
    do_not_send = str(decision.get("do_not_send_because") or "").strip()

    if decision_value in {"no action", "done no action", "done", "noaction"}:
        result.update(
            {
                "queue_status": "Done",
                "owner": owner,
                "next_step": next_step or "No client response needed. Monitor only and reopen if a new client-specific reply arrives.",
                "proof_required": proof_required or "Owner no-action decision recorded from HighLevel reply review.",
                "proof": proof,
                "evidence": evidence,
                "browser_required": "no",
                "do_not_send_because": do_not_send or "No-action decision recorded for this inbound message.",
                "flags": append_flag(str(result.get("flags") or ""), "decision_no_action"),
                "safe_fix_applied": "owner_decision_recorded",
            }
        )
    elif decision_value in {"manual review", "manual", "hold", "still hold"}:
        result.update(
            {
                "queue_status": "Hold",
                "owner": owner,
                "next_step": next_step or "Hold for manual owner review before any client-facing response.",
                "proof_required": proof_required or "Manual review decision and owner resolution required before any response.",
                "proof": proof,
                "evidence": evidence,
                "browser_required": "no",
                "do_not_send_because": do_not_send or "Manual review hold recorded for this inbound message.",
                "flags": append_flag(str(result.get("flags") or ""), "decision_manual_review"),
                "safe_fix_applied": "owner_decision_recorded",
            }
        )
    elif decision_value in {"reply", "approved reply", "approved response"}:
        result.update(
            {
                "queue_status": "Approved",
                "owner": owner or "Brandon",
                "next_step": next_step or "Send only the exact owner-approved reply after live HighLevel preflight.",
                "proof_required": proof_required or "Exact owner-approved reply text plus HighLevel send receipt.",
                "proof": proof,
                "evidence": evidence,
                "browser_required": "yes",
                "do_not_send_because": do_not_send,
                "flags": append_flag(str(result.get("flags") or ""), "decision_reply_approved"),
                "safe_fix_applied": "owner_decision_recorded",
            }
        )
    return result


def highlevel_reply_work_queue_rows(generated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    receipts = {
        str(receipt.get("message_id") or ""): receipt
        for receipt in read_jsonl(HIGHLEVEL_REPLY_RECEIPTS_JSONL)
        if receipt.get("sent")
    }
    decisions = load_highlevel_reply_decisions()
    for reply in read_jsonl(HIGHLEVEL_REPLY_QUEUE_JSONL):
        message = str(reply.get("message_preview") or "").strip()
        message_id = str(reply.get("message_id") or "").strip()
        if not message or not message_id or message_id in seen:
            continue
        seen.add(message_id)
        status, owner, next_step, proof_required, flags = highlevel_reply_status(reply)
        receipt = receipts.get(message_id)
        proof = ""
        evidence = relative_label(HIGHLEVEL_REPLY_QUEUE_JSONL)
        do_not_send = "Inbound reply must be verified and approved from the Work Queue before any client-facing response."
        digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:12].upper()
        work_order_id = f"FUNDZ-HL-{digest}"
        if receipt:
            status = "Sent"
            owner = "FUNDz"
            next_step = "Reply sent after evidence check; monitor the conversation for follow-up."
            proof_required = "HighLevel send receipt and evidence checked before reply."
            proof = relative_label(HIGHLEVEL_REPLY_RECEIPTS_JSONL)
            evidence = relative_label(HIGHLEVEL_REPLY_RECEIPTS_JSONL)
            flags = (flags + ";reply_sent").strip(";")
            do_not_send = ""
        client_name = str(reply.get("name") or "").strip()
        queue_row = {
            "work_order_id": work_order_id,
            "created_at": str(reply.get("time") or generated_at),
            "updated_at": generated_at,
            "actor": "FUNDz",
            "system": "HighLevel",
            "lane": "Client Reply",
            "queue_status": status,
            "client_key": normalize_name(client_name),
            "client_name": client_name,
            "source_status": "highlevel_inbound_reply",
            "owner": owner,
            "due_date": generated_at[:10],
            "next_step": next_step,
            "proof_required": proof_required,
            "proof": proof,
            "evidence": evidence,
            "priority_score": "95" if status == "Proof Needed" else "90",
            "flags": flags,
            "browser_required": "yes",
            "do_not_send_because": do_not_send,
            "safe_fix_applied": "",
            "duplicate_of": "",
        }
        if not receipt:
            decision = decisions.get(work_order_id) or decisions.get(message_id) or decisions.get(digest)
            if decision:
                queue_row = apply_highlevel_reply_decision(queue_row, decision)
        rows.append(queue_row)
    return rows


COMMUNICATION_CONTROL_BOARD_FIELDS = [
    "client_name",
    "client_key",
    "message_lane",
    "communication_status",
    "app_readiness",
    "mobile_app_sms_allowed",
    "email_allowed",
    "current_phase",
    "current_status",
    "stage",
    "next_import",
    "owner_review",
    "billing_or_problem_flag",
    "last_touch",
    "last_touch_status",
    "block_reason",
    "recommended_next_action",
    "proof_required",
    "evidence",
    "sequence_assignment",
    "sequence_assignment_evidence",
    "source_group",
    "source_decision",
    "priority_score",
]


def work_queue_lookup(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in report.get("work_queue", []):
        if str(row.get("lane") or "") == "system-gate":
            continue
        client_key = str(row.get("client_key") or "").strip()
        client_name = normalize_name(str(row.get("client_name") or ""))
        if client_key:
            lookup[client_key] = row
        if client_name:
            lookup[client_name] = row
    return lookup


def first_lookup(keys: list[str], lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for key in keys:
        if key and key in lookup:
            return lookup[key]
    return {}


def explicit_app_installed(row: dict[str, Any], reconciliation: dict[str, str] | None = None) -> bool:
    pieces = [str(value or "") for value in row.values()]
    if reconciliation:
        pieces.extend(str(value or "") for value in reconciliation.values())
    blob = " ".join(pieces).lower()
    return bool(("installed" in blob and "logged" in blob) or "installed/logged" in blob or "logged in" in blob)


def app_readiness_for_control_row(
    row: dict[str, Any],
    *,
    failed_clients: dict[str, str],
    recovered_clients: dict[str, str] | None = None,
    reconciliation: dict[str, str] | None = None,
) -> str:
    name_key = normalize_name(str(row.get("client_name") or ""))
    if recovered_clients and name_key in recovered_clients:
        return "Installed / Logged In"
    if name_key in failed_clients:
        return "Invitation only / App SMS failed"
    if explicit_app_installed(row, reconciliation):
        return "Installed / Logged In"
    notes = " ".join(str((reconciliation or {}).get(key, "")) for key in ("notes", "send_recommendation", "review_status")).lower()
    if "invitation" in notes:
        return "Invitation sent / not proven installed"
    return "Unknown - verify DF app status"


def control_message_lane(row: dict[str, Any], *, queue_status: str = "") -> str:
    flags = set(str(row.get("flags") or "").split(";"))
    phase = str(row.get("phase") or "")
    if queue_status in {"Failed", "Hold", "Needs Brandon", "Proof Needed"}:
        return "Problem / Owner Review"
    if "payment_attention" in flags:
        return "Problem / Owner Review"
    if phase == "onboarding" or {"setup_incomplete", "onboarding_incomplete"} & flags:
        return "Onboarding"
    if phase == "next-round-window" or phase == "active-dispute" or phase.startswith("round-"):
        return "Round Updates"
    return "Education / Credit Tips"


def control_status(queue_row: dict[str, Any], row: dict[str, Any], owner_decision: str, failed: bool) -> str:
    queue_status = str(queue_row.get("queue_status") or "")
    if queue_status == "Done":
        return "Done"
    if failed or queue_status == "Failed":
        return "Failed - fix first"
    if owner_decision == "hold" or queue_status == "Hold":
        return "Hold"
    if queue_status == "Needs Brandon":
        return "Needs Brandon"
    if queue_status == "Proof Needed":
        return "Proof Needed"
    if queue_status == "Blocked":
        return "Blocked"
    if queue_status == "Approved":
        return "Prepare only"
    if str(row.get("next_touch_status") or "") == "monitor":
        return "Monitor"
    return queue_status or "Needs review"


def control_problem_flags(row: dict[str, Any], failed: bool) -> str:
    flags = set(str(row.get("flags") or "").split(";"))
    problems: list[str] = []
    if failed:
        problems.append("app_sms_failed")
    for flag in ("payment_attention", "setup_incomplete", "onboarding_incomplete", "missing_next_import", "no_send_history_linked"):
        if flag in flags:
            problems.append(flag)
    if str(row.get("next_touch_status") or "") == "no-recent-contact-found":
        problems.append("no_recent_contact")
    return ";".join(problems)


def control_block_reasons(
    *,
    row: dict[str, Any],
    queue_row: dict[str, Any],
    owner_decision: str,
    failed: bool,
    app_readiness: str,
    sequence_assignment: dict[str, str] | None = None,
) -> str:
    reasons: list[str] = []
    flags = set(str(row.get("flags") or "").split(";"))
    queue_status = str(queue_row.get("queue_status") or "")
    if failed:
        reasons.append("Known App SMS failure")
    if owner_decision == "hold" or queue_status == "Hold":
        reasons.append("Owner hold")
    if queue_status in {"Blocked", "Failed", "Proof Needed", "Needs Brandon"}:
        do_not_send = str(queue_row.get("do_not_send_because") or "").strip()
        reasons.append(do_not_send or f"Queue status is {queue_status}")
    elif queue_status == "Done":
        do_not_send = str(queue_row.get("do_not_send_because") or "").strip()
        if do_not_send:
            reasons.append(do_not_send)
    if "payment_attention" in flags:
        reasons.append("Billing/payment attention")
    if "missing_next_import" in flags:
        reasons.append("Missing next import or round status")
    if {"setup_incomplete", "onboarding_incomplete"} & flags:
        reasons.append("Setup/onboarding incomplete")
    if str(row.get("next_touch_status") or "") == "no-recent-contact-found":
        reasons.append("No recent contact evidence")
        if sequence_assignment:
            reasons.append("Sequence assignment receipt exists, but no delivered message proof is linked")
    if app_readiness != "Installed / Logged In":
        reasons.append("Mobile App SMS requires DF Installed/Logged In proof")
    return "; ".join(dict.fromkeys(reason for reason in reasons if reason))


def control_next_action(
    *,
    status: str,
    row: dict[str, Any],
    queue_row: dict[str, Any],
    app_readiness: str,
    has_email_value: bool,
) -> str:
    if status == "Hold":
        return "Do not send until Brandon removes the hold."
    if status == "Failed - fix first":
        return "Confirm app invite/app status, wait for Installed/Logged In, and use email fallback only with fresh approval."
    if status == "Needs Brandon":
        return str(queue_row.get("next_step") or "Brandon decision needed before any client-facing message.")
    if status == "Proof Needed":
        return str(queue_row.get("next_step") or "Attach required proof before marking safe.")
    if status == "Done" and str(queue_row.get("do_not_send_because") or "").strip():
        return str(queue_row.get("next_step") or "Monitor only. Do not send unless Brandon explicitly reopens.")
    if app_readiness != "Installed / Logged In":
        if has_email_value:
            return "Verify DF app status before Mobile App SMS; prepare email/app-invite fallback for approval."
        return "Verify DF app status and contact route before outreach."
    if status == "Prepare only":
        return "Prepare the message and verify proof gates before live send."
    return str(row.get("recommended_next_action") or queue_row.get("next_step") or "Monitor and keep on cadence.")


def build_communication_control_board(
    report: dict[str, Any],
    *,
    owner_decisions: dict[str, dict[str, str]] | None = None,
    failed_clients: dict[str, str] | None = None,
    recovered_clients: dict[str, str] | None = None,
    rollout_reconciliation: dict[str, dict[str, str]] | None = None,
    sequence_assignments: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    owner_decisions = owner_decisions if owner_decisions is not None else load_owner_decisions()
    explicit_failed_clients = failed_clients is not None
    failed_clients = failed_clients if failed_clients is not None else failed_rollout_clients()
    if recovered_clients is None:
        recovered_clients = {} if explicit_failed_clients else app_recovery_proofs()
    rollout_reconciliation = rollout_reconciliation if rollout_reconciliation is not None else load_rollout_reconciliation()
    sequence_assignments = sequence_assignments if sequence_assignments is not None else report.get("sequence_assignments", {})
    queue_lookup = work_queue_lookup(report)
    rows: list[dict[str, Any]] = []

    for ledger_row in report.get("ledger", []):
        client_name = str(ledger_row.get("client_name") or "")
        name_key = normalize_name(client_name)
        client_key = str(ledger_row.get("client_key") or "")
        queue_row = first_lookup([client_key, name_key], queue_lookup)
        decision_row = owner_decisions.get(name_key, {})
        reconciliation_row = first_lookup([client_key, name_key], rollout_reconciliation)
        owner_decision = str(decision_row.get("owner_decision") or "").strip().lower()
        failed = name_key in failed_clients
        sequence_assignment = sequence_assignments.get(name_key, {})
        has_email_value = bool(ledger_row.get("has_email"))
        app_readiness = app_readiness_for_control_row(
            ledger_row,
            failed_clients=failed_clients,
            recovered_clients=recovered_clients,
            reconciliation=reconciliation_row,
        )
        status = control_status(queue_row, ledger_row, owner_decision, failed)
        lane = control_message_lane(ledger_row, queue_status=str(queue_row.get("queue_status") or ""))
        mobile_app_allowed = "yes" if status == "Prepare only" and app_readiness == "Installed / Logged In" else "no"
        if app_readiness == "Unknown - verify DF app status" and status in {"Prepare only", "Monitor"}:
            mobile_app_allowed = "check"
        email_allowed = "no"
        if str(queue_row.get("do_not_send_because") or "").strip():
            email_allowed = "no"
        elif has_email_value and status not in {"Hold", "Failed - fix first"}:
            email_allowed = "yes - approval/proof gated"
        elif has_email_value and status == "Failed - fix first":
            email_allowed = "check fallback with approval"
        owner_review = owner_decision or str(reconciliation_row.get("review_status") or "")
        if not owner_review and str(ledger_row.get("next_touch_status") or "") == "owner-review-before-message":
            owner_review = "needed"
        elif not owner_review:
            owner_review = "not required"

        rows.append(
            {
                "client_name": client_name,
                "client_key": client_key,
                "message_lane": lane,
                "communication_status": status,
                "app_readiness": app_readiness,
                "mobile_app_sms_allowed": mobile_app_allowed,
                "email_allowed": email_allowed,
                "current_phase": ledger_row.get("phase", ""),
                "current_status": ledger_row.get("status", ""),
                "stage": ledger_row.get("stage", ""),
                "next_import": ledger_row.get("next_import", ""),
                "owner_review": owner_review,
                "billing_or_problem_flag": control_problem_flags(ledger_row, failed),
                "last_touch": ledger_row.get("latest_touch", ""),
                "last_touch_status": ledger_row.get("next_touch_status", ""),
                "block_reason": control_block_reasons(
                    row=ledger_row,
                    queue_row=queue_row,
                    owner_decision=owner_decision,
                    failed=failed,
                    app_readiness=app_readiness,
                    sequence_assignment=sequence_assignment,
                ),
                "recommended_next_action": control_next_action(
                    status=status,
                    row=ledger_row,
                    queue_row=queue_row,
                    app_readiness=app_readiness,
                    has_email_value=has_email_value,
                ),
                "proof_required": queue_row.get("proof_required", "DF app status proof and latest ledger row."),
                "evidence": queue_row.get("evidence", relative_label(CONTACT_LEDGER_CSV)),
                "sequence_assignment": sequence_assignment.get("result", ""),
                "sequence_assignment_evidence": sequence_assignment.get("evidence", ""),
                "source_group": reconciliation_row.get("send_group", ""),
                "source_decision": reconciliation_row.get("send_recommendation", ""),
                "priority_score": ledger_row.get("priority_score", ""),
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            queue_status_order(str(item.get("communication_status")).replace(" - fix first", "")),
            -safe_int(item.get("priority_score")),
            str(item.get("client_name")).lower(),
        ),
    )


def do_not_send_reason_for_queue_status(status: str, report: dict[str, Any]) -> str:
    if status in {"Hold", "Failed", "Blocked", "Needs Brandon", "Proof Needed"}:
        return "Status is not approved for live outreach."
    if status == "Approved":
        blockers = report.get("blockers", [])
        if blockers:
            return "Global proof gates still have blockers; approval means prepare/preview only."
    return ""


def system_blocker_queue_rows(report: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, blocker in enumerate(report.get("blockers", []), start=1):
        lower = str(blocker).lower()
        status = "Blocked"
        owner = "Brandon" if "cloudflare" in lower or "highlevel" in lower else "FUNDz"
        proof = ""
        if "visual confirmation" in lower or "app/portal" in lower:
            status = "Proof Needed"
            proof = "App/portal screenshot or verified activity-history proof."
        rows.append(
            {
                "work_order_id": f"FUNDZ-SYSTEM-BLOCKER-{idx:02d}",
                "created_at": generated_at,
                "updated_at": generated_at,
                "actor": "Governor",
                "system": "FUNDz",
                "lane": "system-gate",
                "queue_status": status,
                "client_key": "",
                "client_name": "",
                "source_status": "blocker",
                "owner": owner,
                "due_date": generated_at[:10],
                "next_step": next_step_for_blocker(str(blocker)),
                "proof_required": proof or "Evidence that the blocker is resolved.",
                "proof": "",
                "evidence": str(blocker),
                "priority_score": 999 - idx,
                "flags": "system_blocker",
                "browser_required": "no",
                "do_not_send_because": "Broad outreach is blocked until this gate clears.",
                "safe_fix_applied": "",
                "duplicate_of": "",
            }
        )
    return rows


def next_step_for_blocker(blocker: str) -> str:
    lower = blocker.lower()
    if "highlevel" in lower:
        return "Use the HighLevel manual inbox workaround now; update token conversation/message read scope when login is available."
    if "cloudflare" in lower:
        return "Authorize Cloudflare Tunnel after a domain/zone is selectable and set the hostname."
    if "visual confirmation" in lower or "app/portal" in lower:
        return "Get app/portal visibility proof before broad app-first rollout."
    return "Assign owner, resolve blocker, and attach evidence."


def queue_status_order(status: str) -> int:
    order = {status: idx for idx, status in enumerate(("Failed", "Blocked", "Proof Needed", "Needs Brandon", "Hold", "Approved", "Sent", "Done"))}
    return order.get(status, 99)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def governor_safe_fix_queue(rows: list[dict[str, Any]], *, now: datetime | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply Governor's aggressive-safe queue hygiene fixes."""
    now = now or datetime.now()
    fixed: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], str] = {}

    for original in rows:
        row = dict(original)
        fixes: list[str] = []
        status = str(row.get("queue_status") or "")
        if status not in QUEUE_STATUSES:
            row["queue_status"] = "Needs Brandon"
            fixes.append("normalized_unknown_status")

        if not str(row.get("owner") or "").strip():
            row["owner"] = "Brandon"
            row["queue_status"] = "Needs Brandon"
            fixes.append("added_missing_owner")

        if not str(row.get("next_step") or "").strip():
            row["next_step"] = "Review this queue row and decide the next safe action."
            row["queue_status"] = "Needs Brandon"
            fixes.append("added_missing_next_step")

        if row.get("queue_status") in QUEUE_DONE_REQUIRES_PROOF and not str(row.get("proof") or "").strip():
            row["queue_status"] = "Proof Needed"
            fixes.append("required_missing_proof")

        if row.get("queue_status") == "Approved" and str(row.get("do_not_send_because") or "").strip():
            row["queue_status"] = "Blocked"
            fixes.append("paused_approved_row_with_gate")

        last_updated = parse_iso_datetime(row.get("updated_at"))
        if last_updated and now - last_updated.replace(tzinfo=None) > timedelta(hours=24) and row.get("queue_status") not in {"Done", "Hold"}:
            fixes.append("stale_over_24h")
            alerts.append(governor_alert(row, "stale-work", "Queue row has not been updated in over 24 hours."))

        dedupe_key = (
            normalize_name(str(row.get("client_key") or row.get("client_name") or "")),
            str(row.get("system") or ""),
            str(row.get("lane") or ""),
        )
        if dedupe_key[0] and dedupe_key in seen:
            row["duplicate_of"] = seen[dedupe_key]
            if row.get("queue_status") not in {"Done", "Hold"}:
                row["queue_status"] = "Blocked"
            fixes.append("linked_duplicate")
        elif dedupe_key[0]:
            seen[dedupe_key] = str(row.get("work_order_id") or "")

        if row.get("queue_status") in {"Failed", "Blocked", "Proof Needed", "Needs Brandon"}:
            alerts.append(governor_alert(row, str(row.get("queue_status")).lower().replace(" ", "-"), str(row.get("next_step") or "")))

        if fixes:
            row["safe_fix_applied"] = ";".join(fixes)
        fixed.append(row)

    return fixed, alerts


def governor_alert(row: dict[str, Any], reason: str, next_step: str) -> dict[str, Any]:
    return {
        "alert_id": f"GOV-{safe_int(abs(hash((row.get('work_order_id'), reason))) % 1000000):06d}",
        "reason": reason,
        "queue_status": row.get("queue_status", ""),
        "work_order_id": row.get("work_order_id", ""),
        "client_name": row.get("client_name", ""),
        "system": row.get("system", ""),
        "owner": row.get("owner", ""),
        "evidence": row.get("evidence", ""),
        "next_step": next_step,
    }


def build_daily_board(report: dict[str, Any]) -> list[dict[str, str]]:
    queue_rows = report.get("work_queue", [])
    counts = Counter(str(row.get("queue_status") or "Unknown") for row in queue_rows)
    top_problem = next((row for row in queue_rows if row.get("queue_status") in {"Failed", "Blocked", "Proof Needed", "Needs Brandon"}), {})
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    if kill_switch.get("enabled"):
        next_action = "Send kill switch is ON. Review send visibility before approving any client/lead message."
    elif top_problem:
        next_action = str(top_problem.get("next_step"))
    elif report.get("no_approval_work_queue"):
        next_work = report["no_approval_work_queue"][0]
        next_action = f"{next_work.get('work_item')}: {next_work.get('output')}"
    else:
        next_action = "Run command center, review the work queue, and clear the top blocker."
    proof_row = next((row for row in queue_rows if row.get("queue_status") == "Proof Needed"), top_problem)
    blocker = (report.get("blockers") or ["No current blocker recorded."])[0]
    if kill_switch.get("enabled"):
        blocker = f"Send kill switch ON: {kill_switch.get('reason') or 'live sends are paused'}"
    needs_brandon = counts.get("Needs Brandon", 0) + counts.get("Hold", 0)
    objective = (
        "Clean client records and maintenance queues before any live work."
        if report.get("maintenance_cleanup_summary")
        else "Clear the highest-risk outreach blocker before any browser/live work."
    )
    return [
        {"label": "Today’s Objective", "value": objective},
        {"label": "Next Action", "value": next_action},
        {"label": "Blocked", "value": str(blocker)},
        {"label": "Needs Brandon", "value": f"{needs_brandon} queue item(s) need Brandon/hold review."},
        {"label": "Proof Required", "value": str(proof_row.get("proof_required") or "Attach receipt/screenshot before marking done.")},
    ]


def parse_provider_body(result: dict[str, Any]) -> dict[str, Any]:
    raw = str(result.get("body") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def send_kill_switch_state(path: Path = SEND_KILL_SWITCH_JSON) -> dict[str, Any]:
    file_state = read_json(path)
    enabled = False
    reason = ""
    owner = "Brandon"
    source = "default_off"
    updated_at = ""
    if isinstance(file_state, dict):
        enabled = str(file_state.get("enabled") or "").strip().lower() in {"1", "true", "yes", "on"}
        reason = str(file_state.get("reason") or "").strip()
        owner = str(file_state.get("owner") or owner).strip() or owner
        updated_at = str(file_state.get("updated_at") or "").strip()
        source = relative_label(path)
    if env_bool("FUNDZ_SEND_KILL_SWITCH") or env_bool("FUNDZ_COMMAND_CENTER_KILL_SWITCH"):
        enabled = True
        reason = reason or "Environment kill switch is enabled."
        source = "environment"
    return {
        "enabled": enabled,
        "status": "KILL_SWITCH_ON" if enabled else "ready_but_gated",
        "reason": reason or ("Live sends blocked by command-center kill switch." if enabled else "Kill switch is off; approval gates still apply."),
        "owner": owner,
        "updated_at": updated_at,
        "source": source,
        "control_file": relative_label(path),
    }


def latest_expansion_packet() -> dict[str, Any]:
    data = read_json(EXPANSION_BATCH_PACKET)
    return data if isinstance(data, dict) else {}


def expansion_packet_message_lookup(packet: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    batch_id = str(packet.get("batch_id") or "")
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for item in packet.get("items", []) if isinstance(packet.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        lookup[(batch_id, normalize_name(str(item.get("client_name") or "")))] = item
    return lookup


def infer_channel_from_receipt(path: Path, data: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    result = result or {}
    if result.get("channel"):
        return str(result.get("channel"))
    if data.get("channel"):
        return str(data.get("channel"))
    name = path.name.lower()
    mode = str(data.get("mode") or "").lower()
    if "df-autofox-email" in name:
        return "DF Email"
    if "email" in name or "email" in mode:
        return "Email"
    if "portal-trigger" in name:
        return "HighLevel tag trigger"
    if "batch" in name:
        return str(data.get("channel") or "HighLevel batch")
    return str(data.get("mode") or "unknown")


def receipt_sent_rows(packet_lookup: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(RECEIPTS_DIR.glob("*-result.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        batch_id = str(data.get("batch_id") or "")
        created_at = str(data.get("created_at") or data.get("attempted_at") or "")
        if isinstance(data.get("results"), list):
            for result in data.get("results", []):
                if not isinstance(result, dict):
                    continue
                client_name = str(result.get("client_name") or data.get("client_name") or "")
                packet_item = packet_lookup.get((batch_id, normalize_name(client_name)), {})
                provider = result.get("result") if isinstance(result.get("result"), dict) else {}
                provider_body = parse_provider_body(provider)
                sent = bool(result.get("sent") or provider.get("sent"))
                rows.append(
                    {
                        "sent_at": created_at,
                        "client_or_lead": client_name,
                        "audience": "client_or_lead",
                        "system": "FUNDz",
                        "channel": infer_channel_from_receipt(path, data, result),
                        "campaign_or_batch": batch_id or str(data.get("mode") or ""),
                        "status": "sent" if sent else "failed_or_blocked",
                        "http_status": result.get("status") or provider.get("status") or "",
                        "subject": (packet_item.get("outbound_payload_preview") or {}).get("subject", ""),
                        "message_body_or_summary": packet_item.get("message", ""),
                        "proof": relative_label(path.with_name(path.name.replace("-result.json", "-receipt.md")))
                        if path.with_name(path.name.replace("-result.json", "-receipt.md")).exists()
                        else relative_label(path),
                        "source": relative_label(path),
                        "provider_message_id": provider_body.get("messageId") or provider_body.get("emailMessageId") or "",
                    }
                )
        elif data.get("sent") is not None:
            sent = bool(data.get("sent"))
            rows.append(
                {
                    "sent_at": str(data.get("attempted_at") or data.get("created_at") or ""),
                    "client_or_lead": str(data.get("client_name") or ""),
                    "audience": "client_or_lead",
                    "system": "FUNDz",
                    "channel": infer_channel_from_receipt(path, data),
                    "campaign_or_batch": str(data.get("approved_packet") or data.get("mode") or ""),
                    "status": "sent" if sent else "held_or_failed",
                    "http_status": str(data.get("provider_result") or ""),
                    "subject": str(data.get("subject") or ""),
                    "message_body_or_summary": str(data.get("provider_proof") or ""),
                    "proof": relative_label(path.with_name(path.name.replace("-result.json", "-receipt.md")))
                    if path.with_name(path.name.replace("-result.json", "-receipt.md")).exists()
                    else relative_label(path),
                    "source": relative_label(path),
                    "provider_message_id": "",
                }
            )
    return rows


def highlevel_reply_sent_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for receipt in read_jsonl(HIGHLEVEL_REPLY_RECEIPTS_JSONL):
        if not receipt.get("sent"):
            continue
        rows.append(
            {
                "sent_at": str(receipt.get("time") or ""),
                "client_or_lead": str(receipt.get("client") or ""),
                "audience": "client_or_lead",
                "system": "HighLevel",
                "channel": str(receipt.get("channel") or "HighLevel"),
                "campaign_or_batch": "inbound_reply",
                "status": "sent",
                "http_status": str(receipt.get("status") or ""),
                "subject": "",
                "message_body_or_summary": str(receipt.get("reply_summary") or ""),
                "proof": relative_label(HIGHLEVEL_REPLY_RECEIPTS_JSONL),
                "source": relative_label(HIGHLEVEL_REPLY_RECEIPTS_JSONL),
                "provider_message_id": hashlib.sha256(str(receipt.get("message_id") or "").encode("utf-8")).hexdigest()[:12]
                if receipt.get("message_id")
                else "",
            }
        )
    return rows


def owner_safe_recipient(value: Any) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return text
    local, _, domain = text.partition("@")
    domain_name, dot, suffix = domain.partition(".")
    return f"{local[:2]}***@{domain_name[:2]}***{dot}{suffix}" if domain else "[redacted-email]"


def autofox_audit_sent_rows(limit: int = 5000) -> list[dict[str, Any]]:
    candidates = sorted(
        (ROOT / "data" / "local" / "autofox-audits").glob("autofox-normalized-outbound-*.csv"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return []
    rows: list[dict[str, Any]] = []
    for row in read_csv_rows(candidates[0])[:limit]:
        status = str(row.get("status") or "").lower()
        if status not in {"sent", "failed"}:
            continue
        rows.append(
            {
                "sent_at": str(row.get("timestamp") or ""),
                "client_or_lead": owner_safe_recipient(row.get("recipient")),
                "audience": "client_or_lead",
                "system": "AutoFox/Credit Tracker audit",
                "channel": str(row.get("channel") or ""),
                "campaign_or_batch": str(row.get("campaign") or ""),
                "status": str(row.get("status") or ""),
                "http_status": "",
                "subject": "",
                "message_body_or_summary": str(row.get("body") or ""),
                "proof": relative_label(candidates[0]),
                "source": relative_label(candidates[0]),
                "provider_message_id": str(row.get("event_id") or ""),
            }
        )
    return rows


def build_send_ledger(packet: dict[str, Any]) -> list[dict[str, Any]]:
    packet_lookup = expansion_packet_message_lookup(packet)
    rows = receipt_sent_rows(packet_lookup)
    rows.extend(highlevel_reply_sent_rows())
    rows.extend(autofox_audit_sent_rows())
    rows.sort(key=lambda row: str(row.get("sent_at") or ""), reverse=True)
    return rows


def parse_owner_notice_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def owner_pre_send_notice_summary(packet: dict[str, Any]) -> dict[str, Any]:
    key = packet_notice_key(packet)
    wait_seconds = owner_pre_send_notice_seconds()
    sent_rows = [row for row in read_owner_pre_send_notices() if row.get("notice_key") == key and row.get("sent")]
    if not sent_rows:
        return {
            "notice_key": key,
            "status": "required_2_min_before_live_send",
            "wait_seconds": wait_seconds,
            "remaining_seconds": wait_seconds,
            "receipt": relative_label(OWNER_PRE_SEND_NOTICE_RECEIPTS),
        }
    latest = sent_rows[-1]
    sent_at = parse_owner_notice_time(latest.get("sent_at") or latest.get("created_at"))
    if not sent_at:
        return {
            "notice_key": key,
            "status": "sent_time_unknown",
            "wait_seconds": wait_seconds,
            "remaining_seconds": wait_seconds,
            "receipt": relative_label(OWNER_PRE_SEND_NOTICE_RECEIPTS),
        }
    now = datetime.now(sent_at.tzinfo) if sent_at.tzinfo else datetime.now()
    elapsed = max(int((now - sent_at).total_seconds()), 0)
    remaining = max(wait_seconds - elapsed, 0)
    return {
        "notice_key": key,
        "status": "ready" if remaining == 0 else "sent_waiting",
        "wait_seconds": wait_seconds,
        "remaining_seconds": remaining,
        "sent_at": sent_at.isoformat(timespec="seconds"),
        "receipt": relative_label(OWNER_PRE_SEND_NOTICE_RECEIPTS),
    }


def build_next_send_queue(packet: dict[str, Any], kill_switch: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    batch_id = str(packet.get("batch_id") or "")
    approval_required = bool(packet.get("approval_required", True))
    live_send_allowed = bool(packet.get("live_send_allowed"))
    notice_summary = owner_pre_send_notice_summary(packet)
    for item in packet.get("items", []) if isinstance(packet.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        blocked_reasons = list(item.get("do_not_send_because") or [])
        if item.get("blocked_reason"):
            blocked_reasons.append(str(item.get("blocked_reason")))
        if kill_switch.get("enabled"):
            blocked_reasons.append("Command-center kill switch is ON.")
        elif approval_required:
            blocked_reasons.append("Live send still requires Brandon approval at action time.")
        if notice_summary.get("status") != "ready":
            blocked_reasons.append("Owner text notice must be sent at least 2 minutes before live send.")
        send_allowed = bool(item.get("send_ready")) and not blocked_reasons and live_send_allowed
        rows.append(
            {
                "queue_rank": len(rows) + 1,
                "client_or_lead": str(item.get("client_name") or ""),
                "audience": "client",
                "channel": str(item.get("channel") or packet.get("channel") or ""),
                "subject": str((item.get("outbound_payload_preview") or {}).get("subject") or ""),
                "message_body": str(item.get("message") or ""),
                "campaign_or_batch": batch_id,
                "message_phase": str(item.get("message_phase") or ""),
                "status": str(item.get("status") or ""),
                "stage": str(item.get("stage_in_process") or ""),
                "send_ready": "yes" if item.get("send_ready") else "no",
                "kill_switch": str(kill_switch.get("status") or ""),
                "owner_notice_status": str(notice_summary.get("status") or ""),
                "owner_notice_remaining_seconds": str(notice_summary.get("remaining_seconds") or 0),
                "send_allowed_now": "yes" if send_allowed else "no",
                "blocked_reason": "; ".join(blocked_reasons),
                "evidence": relative_label(EXPANSION_BATCH_PACKET),
            }
        )
    return rows


SEND_LEDGER_FIELDS = [
    "sent_at",
    "client_or_lead",
    "audience",
    "system",
    "channel",
    "campaign_or_batch",
    "status",
    "http_status",
    "subject",
    "message_body_or_summary",
    "proof",
    "source",
    "provider_message_id",
]

NEXT_SEND_QUEUE_FIELDS = [
    "queue_rank",
    "client_or_lead",
    "audience",
    "channel",
    "subject",
    "message_body",
    "campaign_or_batch",
    "message_phase",
    "status",
    "stage",
    "send_ready",
    "kill_switch",
    "owner_notice_status",
    "owner_notice_remaining_seconds",
    "send_allowed_now",
    "blocked_reason",
    "evidence",
]


def normalize_name(name: str) -> str:
    text = re.sub(r"\s*\*\s*new\b", "", (name or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def client_phase(client: dict[str, Any]) -> str:
    flags = set(client.get("operational_flags", []))
    if "payment_attention" in flags:
        return "billing-review"
    if "setup_incomplete" in flags or "onboarding_incomplete" in flags:
        return "onboarding"
    if "due_for_next_round" in flags:
        return "next-round-window"
    round_number = client.get("dispute_round", {}).get("number")
    if round_number:
        return f"round-{round_number}"
    if "in_dispute" in flags:
        return "active-dispute"
    return "stable-review"


def cadence_for_client(client: dict[str, Any]) -> str:
    phase = client_phase(client)
    if phase in {"onboarding", "next-round-window"}:
        return "daily-business-day"
    if phase.startswith("round-") or phase == "active-dispute":
        return "every-other-business-day"
    return "twice-weekly"


def has_email(client: dict[str, Any]) -> bool:
    return bool(str(client.get("email") or "").strip())


def has_phone_history(client: dict[str, Any]) -> bool:
    history = client.get("send_history", {})
    recipients = [str(item or "") for item in history.get("recipients", [])]
    recent_sms = [str(item.get("sent_to") or "") for item in history.get("recent_sms", []) if isinstance(item, dict)]
    return any(re.search(r"\d{10,}", item) for item in recipients + recent_sms)


def latest_touch_label(client: dict[str, Any]) -> str:
    history = client.get("send_history", {})
    latest_email = history.get("latest_email") if isinstance(history.get("latest_email"), dict) else {}
    if latest_email and latest_email.get("sent_date"):
        return f"email: {latest_email.get('sent_date')}"
    recent_sms = history.get("recent_sms") if isinstance(history.get("recent_sms"), list) else []
    if recent_sms:
        return "sms: present in latest SMS history"
    return ""


def next_touch_status(client: dict[str, Any]) -> str:
    flags = set(client.get("operational_flags", []))
    if flags & OWNER_REVIEW_FLAGS:
        return "owner-review-before-message"
    if not latest_touch_label(client):
        return "no-recent-contact-found"
    if "due_for_next_round" in flags:
        return "prepare-owner-approved-next-round-touch"
    if "in_dispute" in flags:
        return "monitor-and-touch-on-cadence"
    return "monitor"


def priority_score(client: dict[str, Any]) -> int:
    flags = set(client.get("operational_flags", []))
    score = 0
    if "payment_attention" in flags:
        score += 95
    if "due_for_next_round" in flags:
        score += 80
    if "missing_next_import" in flags:
        score += 70
    if "setup_incomplete" in flags or "onboarding_incomplete" in flags:
        score += 60
    if "no_send_history_linked" in flags:
        score += 45
    if "in_dispute" in flags:
        score += 25
    next_days = client.get("next_import_days")
    if isinstance(next_days, int):
        if next_days <= 0:
            score += 25
        elif next_days <= 3:
            score += 15
    return score


def build_contact_ledger(clients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger = []
    for client in clients:
        if not client.get("is_active_client"):
            continue
        flags = client.get("operational_flags", [])
        ledger.append(
            {
                "client_key": client.get("client_key", ""),
                "client_name": client.get("client_name", ""),
                "phase": client_phase(client),
                "cadence": cadence_for_client(client),
                "status": client.get("status", ""),
                "stage": client.get("stage_in_process", ""),
                "next_import": client.get("next_import", ""),
                "latest_touch": latest_touch_label(client),
                "next_touch_status": next_touch_status(client),
                "priority_score": priority_score(client),
                "has_email": has_email(client),
                "has_phone_history": has_phone_history(client),
                "flags": ";".join(flags),
                "recommended_next_action": client.get("recommended_next_action", ""),
            }
        )
    return sorted(ledger, key=lambda row: (-int(row["priority_score"]), str(row["client_name"]).lower()))


def duplicate_contact_report(clients: list[dict[str, Any]]) -> dict[str, Any]:
    emails: dict[str, list[str]] = {}
    names: dict[str, list[str]] = {}
    for client in clients:
        name = str(client.get("client_name") or "")
        email = str(client.get("email") or "").strip().lower()
        key = normalize_name(name)
        if key:
            names.setdefault(key, []).append(name)
        if email:
            emails.setdefault(email, []).append(name)
    return {
        "duplicate_names": {key: vals for key, vals in names.items() if len(set(vals)) > 1},
        "duplicate_emails": {key: vals for key, vals in emails.items() if len(set(vals)) > 1},
    }


def highlevel_blocker() -> str:
    rows = read_jsonl(POLLER_LOG)
    for row in reversed(rows):
        if row.get("kind") == "poll_complete":
            if row.get("ok") and str(row.get("status")) == "200":
                return ""
            status = row.get("status")
            if status:
                return f"HighLevel inbox poller latest complete status: {status}."
        if row.get("kind") == "poll_failed":
            status = row.get("status")
            if status in {401, "401"}:
                return "HighLevel inbox poller is blocked by 401; token needs conversation/message read scope."
            if status in {403, "403"}:
                return "HighLevel inbox poller is blocked by 403; token/location access needs review."
            return f"HighLevel inbox poller latest failure status: {status}."
    return "HighLevel inbox scope is unproven until the poller returns 200."


def cloudflare_blocker() -> str:
    cert = Path.home() / ".cloudflared" / "cert.pem"
    hostname = os.getenv("FUNDZ_TUNNEL_HOSTNAME", "").strip()
    if cert.exists() and hostname:
        return ""
    if not cert.exists():
        return "Permanent Cloudflare tunnel is blocked by missing origin certificate."
    return "Permanent Cloudflare tunnel needs FUNDZ_TUNNEL_HOSTNAME."


def bridge_status() -> dict[str, Any]:
    rows = read_jsonl(BRIDGE_LOG, limit=200)
    kinds = Counter(str(row.get("kind") or "unknown") for row in rows)
    return {"recent_events": len(rows), "kinds": dict(kinds.most_common(8))}


def collect_autofox_audit() -> dict[str, Any]:
    normalized: list[dict[str, str]] = []
    sources = newest_candidate_files()
    for source in sources:
        for index, record in enumerate(load_autofox_records(source), start=1):
            row = normalize(record, source, index)
            if row:
                normalized.append(row)
    audit = audit_records(normalized)
    return {
        "records": len(normalized),
        "unique_recipients": len(audit["recipients"]),
        "failures": len(audit["failures"]),
        "duplicates": sum(len(group) for group in audit["duplicates"]),
        "risky": len(audit["risky"]),
        "after_hours": len(audit["after_hours"]),
        "top_campaigns": dict(audit["campaigns"].most_common(8)),
        "top_statuses": dict(audit["statuses"].most_common(8)),
    }


def receipt_summary() -> dict[str, Any]:
    receipts = sorted(RECEIPTS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    pilot_seen = {name: {"app_or_sms_sent": False, "email_sent": False, "reply_seen": False} for name in PILOT_NAMES}
    recent = []
    for path in receipts[:25]:
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        recent.append(str(path.relative_to(ROOT)))
        blob = json.dumps(data).lower()
        for name in PILOT_NAMES:
            if name in blob and '"sent": true' in blob:
                if '"channel": "email"' in blob or "email" in path.name.lower():
                    pilot_seen[name]["email_sent"] = True
                else:
                    pilot_seen[name]["app_or_sms_sent"] = True
    return {"recent_receipts": recent[:10], "pilot_clients": pilot_seen}


def iter_receipt_results() -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for path in sorted(RECEIPTS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime):
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        for result in data.get("results", []):
            if isinstance(result, dict):
                rows.append((path, data, result))
    return rows


def erika_app_message_visibility_proof_exists() -> bool:
    return any(
        (RECEIPTS_DIR / filename).exists()
        for filename in (
            "erika-app-message-history-sent-proof-20260506.png",
            "erika-app-message-history-sent-proof-20260506.md",
        )
    )


def build_pilot_status_report() -> dict[str, Any]:
    clients = {
        name: {
            "client_name": name.title(),
            "app_or_sms_sent": False,
            "email_sent": False,
            "email_failed_then_recovered": False,
            "provider_message_ids": [],
            "provider_conversation_ids": [],
            "reply_seen": False,
            "app_visibility_confirmed": False,
            "unresolved": [],
        }
        for name in sorted(PILOT_NAMES)
    }

    for _path, receipt, row in iter_receipt_results():
        normalized = normalize_name(str(row.get("client_name") or ""))
        if normalized not in clients:
            continue
        mode = str(receipt.get("mode") or "").lower()
        status = clients[normalized]
        sent = bool(row.get("sent"))
        if sent and "email" in mode:
            status["email_sent"] = True
        elif sent:
            status["app_or_sms_sent"] = True
        if row.get("failed") and "email" in mode:
            status["email_failed_then_recovered"] = True
            status["unresolved"].append("email initially failed")
        provider = row.get("result") if isinstance(row.get("result"), dict) else {}
        body = parse_provider_body(provider)
        for key, target in (("messageId", "provider_message_ids"), ("emailMessageId", "provider_message_ids"), ("conversationId", "provider_conversation_ids")):
            value = str(body.get(key) or "").strip()
            if value and value not in status[target]:
                status[target].append(value)
    for status in clients.values():
        if status["email_failed_then_recovered"] and status["email_sent"]:
            status["unresolved"] = [item for item in status["unresolved"] if item != "email initially failed"]
        if not status["app_or_sms_sent"]:
            status["unresolved"].append("app/SMS provider receipt missing")
        if not status["email_sent"]:
            status["unresolved"].append("email receipt missing")
        if not status["app_visibility_confirmed"]:
            status["unresolved"].append("Credit Tracker app/portal visibility not confirmed")
    return {
        "pilot_clients": list(clients.values()),
        "summary": {
            "clients": len(clients),
            "app_or_sms_sent": sum(1 for item in clients.values() if item["app_or_sms_sent"]),
            "email_sent": sum(1 for item in clients.values() if item["email_sent"]),
            "app_visibility_confirmed": sum(1 for item in clients.values() if item["app_visibility_confirmed"]),
            "replied": sum(1 for item in clients.values() if item["reply_seen"]),
            "unresolved": sum(1 for item in clients.values() if item["unresolved"]),
        },
    }


def memory_freshness(state: dict[str, Any]) -> dict[str, Any]:
    source_files = state.get("metadata", {}).get("source_files", {}) if isinstance(state.get("metadata"), dict) else {}
    files = []
    newest_mtime = 0.0
    for label in source_files.values():
        path = ROOT / str(label)
        if not path.exists():
            files.append({"path": label, "exists": False})
            continue
        mtime = path.stat().st_mtime
        newest_mtime = max(newest_mtime, mtime)
        files.append(
            {
                "path": label,
                "exists": True,
                "modified": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
            }
        )
    generated = str(state.get("metadata", {}).get("generated_at") or "")
    stale_reasons = []
    if not source_files:
        stale_reasons.append("no source files recorded")
    if STATE_JSON.exists() and newest_mtime and STATE_JSON.stat().st_mtime < newest_mtime:
        stale_reasons.append("stored state is older than at least one source export")
    return {
        "generated_at": generated,
        "source_files": files,
        "stale": bool(stale_reasons),
        "stale_reasons": stale_reasons,
    }


def compare_with_previous(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(previous, dict):
        return {"available": False, "summary_deltas": {}, "note": "no previous command-center JSON found"}
    deltas: dict[str, Any] = {}
    current_summary = current.get("summary", {})
    previous_summary = previous.get("summary", {})
    for key in ("active_clients", "owner_review_before_message", "no_recent_contact_found"):
        old = previous_summary.get(key)
        new = current_summary.get(key)
        if isinstance(old, int) and isinstance(new, int):
            deltas[key] = new - old
    old_actions = previous_summary.get("action_counts", {})
    new_actions = current_summary.get("action_counts", {})
    if isinstance(old_actions, dict) and isinstance(new_actions, dict):
        deltas["action_counts"] = {
            key: int(new_actions.get(key, 0)) - int(old_actions.get(key, 0))
            for key in sorted(set(old_actions) | set(new_actions))
        }
    return {"available": True, "summary_deltas": deltas}


def release_checklist(report: dict[str, Any]) -> list[dict[str, str]]:
    summary = report.get("summary", {})
    audit = report.get("autofox_audit", {})
    blockers = report.get("blockers", [])
    checks = [
        ("Human approval captured", "blocked", "Live sends still require Brandon's action-time approval."),
        ("Dry run disabled only for approved command", "blocked", "Keep CREDIT_TRACKER_DRY_RUN=true until the exact approved send command."),
        ("Inside approved send window", "manual", "Pilot/batch sends enforce weekday 9 AM - 9 PM unless explicitly overridden."),
        ("HighLevel inbox readable", "blocked" if any("HighLevel" in item for item in blockers) else "pass", "Needed for reply monitoring."),
        ("Cloudflare named tunnel stable", "blocked" if any("Cloudflare" in item for item in blockers) else "pass", "Needed for permanent webhook intake."),
        ("App visibility confirmed", "blocked" if any("app/portal visual confirmation" in item for item in blockers) else "pass", "Needed before broad app-first rollout."),
        ("Owner-review queue clear enough", "review" if summary.get("owner_review_before_message", 0) else "pass", "Owner-review clients should not enter broad sends."),
        ("AutoFox failures reviewed", "review" if audit.get("failures", 0) else "pass", "Review failures before resends or workflow expansion."),
        ("Duplicate send candidates reviewed", "review" if audit.get("duplicates", 0) else "pass", "Avoid accidental duplicate outreach."),
        ("After-hours records reviewed", "review" if audit.get("after_hours", 0) else "pass", "Keep outreach inside contact window."),
    ]
    return [{"check": check, "status": status, "note": note} for check, status, note in checks]


def backlog_coverage(report: dict[str, Any]) -> list[dict[str, str]]:
    blockers = "\n".join(report.get("blockers", []))
    coverage = {
        "Immediate Live-Pilot Work": ("partial", "Provider receipts are reported; app visibility/reply monitoring remain blocked on confirmation and HighLevel scope."),
        "HighLevel + Inbox Intelligence": ("partial", "Reply classification and local queue exist; live inbox read remains blocked by HighLevel 401 scope."),
        "Credit Tracker / App-First Messaging": ("partial", "App-first campaign and Mobile App SMS migration checklist exist; app/portal visibility is still unconfirmed."),
        "Semi-Autonomous Outreach Engine": ("partial", "Priority scores, phase templates, batch presets, and do-not-send reasons exist; live expansion remains approval-gated."),
        "AutoFox / DisputeFox Workflow Cleanup": ("partial", "Audit and migration checklist exist; remaining sequences need DF review and action-time approval."),
        "Cloudflare + Webhook Hardening": ("blocked", "Named tunnel remains blocked by missing Cloudflare origin certificate/domain zone."),
        "Supabase / Durable Memory": ("partial", "Schema/dashboard chunk sync exists; direct command-line sync needs a real database URL."),
        "ScoreFusion Billing Power-Ups": ("partial", "Dashboard, HighLevel import support, and billing-risk queue exist; billing workflows still need owner review."),
        "Command Center / Operator UX": ("done", "Daily command center, weekly summary, drilldowns, owner-review packet, pilot status, and release checklist exist."),
        "Safety, Tests, and Release Discipline": ("partial", "Live-send guards and 69 tests exist; CI coverage beyond memory-check still remains a future gap."),
    }
    if "Cloudflare" not in blockers:
        coverage["Cloudflare + Webhook Hardening"] = ("partial", "Cloudflare blocker not detected locally, but final public webhook verification is still required.")
    return [{"area": area, "status": coverage[area][0], "gap": coverage[area][1]} for area in BACKLOG_AREAS]


def no_approval_work_queue(report: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    maintenance_summary = report.get("maintenance_cleanup_summary")
    if isinstance(maintenance_summary, dict) and maintenance_summary:
        rows.append(
            {
                "priority": "1",
                "work_item": "Use maintenance cleanup board",
                "input": relative_label(MAINTENANCE_CLEANUP_MD),
                "output": str(
                    maintenance_summary.get("next_action")
                    or "Clean billing, archive, contact-route, and duplicate rows from one board; no client outreach."
                ),
            }
        )
    if build_owner_decision_queue(report):
        rows.append(
            {
                "priority": "1",
                "work_item": "Review owner decision queue",
                "input": relative_label(OWNER_DECISION_PACKET_MD),
                "output": "Choose approve draft, hold, billing review, import check, or onboarding follow-up per client.",
            }
        )
    active_no_recent = any(
        row.get("source_status") == "no-recent-contact-found" and row.get("queue_status") not in {"Hold", "Done"}
        for row in report.get("work_queue", [])
    )
    if active_no_recent:
        rows.append(
            {
                "priority": "1",
                "work_item": "Resolve no-recent-contact exception",
                "input": relative_label(NO_RECENT_CONTACT_INVESTIGATION_MD),
                "output": "Verify delivered-message proof or keep the row in owner review; do not treat assignments/dry runs as contact proof.",
            }
        )
    live_hold_rows = read_csv_rows(LIVE_HOLD_CLEANUP_CSV)
    if live_hold_rows:
        live_hold_decisions = Counter(str(row.get("cleanup_decision") or "") for row in live_hold_rows)
        active_live_hold_decisions = {
            "repair_bounced_email_route",
            "hold_live_billing_warning",
            "hold_manual_live_review",
        }
        active_live_hold_count = sum(live_hold_decisions.get(decision, 0) for decision in active_live_hold_decisions)
        if active_live_hold_count == 0:
            live_hold_output = ""
        elif live_hold_decisions.get("repair_bounced_email_route"):
            live_hold_output = (
                "Repair bounced email routes and keep live billing/archive holds excluded before any new rollout preview."
            )
        elif live_hold_decisions.get("exclude_bounced_email_route"):
            live_hold_output = (
                "Bounced route is excluded; keep live billing/archive holds out of outreach until fresh proof clears them."
            )
        else:
            live_hold_output = "Keep live billing/archive holds excluded before any new rollout preview."
        if live_hold_output:
            rows.append(
                {
                    "priority": "2",
                    "work_item": "Review bounce/live-hold cleanup",
                    "input": relative_label(LIVE_HOLD_CLEANUP_MD),
                    "output": live_hold_output,
                }
            )
    default_rows = [
        {
            "priority": "2",
            "work_item": "Review billing risk queue",
            "input": "data/local/scorefusion-billing-dashboard/billing-risk-review-packet.md",
            "output": "Review deduped high-risk billing clients before any billing-warning workflow change.",
        },
        {
            "priority": "3",
            "work_item": "Review AutoFox migration checklist",
            "input": relative_label(AUTOFOX_MIGRATION_MD),
            "output": "List remaining workflows needing Mobile App SMS proof.",
        },
    ]
    if isinstance(maintenance_summary, dict) and maintenance_summary:
        default_rows.append(
            {
                "priority": "4",
                "work_item": "Refresh maintenance cleanup board",
                "input": "scorefusion dashboard + maintenance cleanup board",
                "output": "Refresh local billing/archive/contact/duplicate classifications; do not prepare outreach.",
            }
        )
    else:
        default_rows.append(
            {
                "priority": "4",
                "work_item": "Prepare preview-only tiny pilot",
                "input": "--batch-preview --batch-preset tiny_pilot --resolve-contact",
                "output": "Create a one-client approval packet; do not live send.",
            }
        )
    default_rows.append(
        {
            "priority": "5",
            "work_item": "Refresh command center after new exports",
            "input": "make command-center",
            "output": "Updated coverage, blockers, and work queues.",
        }
    )
    rows.extend(default_rows)
    for idx, row in enumerate(rows, start=1):
        row["priority"] = str(idx)
    return rows


def missing_steps_recheck(report: dict[str, Any]) -> list[dict[str, str]]:
    blockers = "\n".join(report.get("blockers", []))
    pilot = report.get("pilot_status", {}).get("summary", {})
    ci_tests = ROOT / ".github" / "workflows" / "tests.yml"
    app_communication_erika_proof = RECEIPTS_DIR / "app-communication-erika-sent-proof-20260505.png"
    app_communication_paused_proof = RECEIPTS_DIR / "app-communication-regular-sms-paused-20260505.png"
    app_communication_done = app_communication_erika_proof.exists()
    app_visibility_done = erika_app_message_visibility_proof_exists()
    cloudflare_blocked = "Cloudflare" in blockers
    has_database_url = any(
        os.getenv(name, "").strip()
        for name in ("FUNDZ_MEMORY_DATABASE_URL", "SUPABASE_DB_URL", "DATABASE_URL", "NEON_DATABASE_URL")
    )
    checks = [
        {
            "area": "Credit Tracker app visibility proof",
            "status": "pass" if app_visibility_done or int(pilot.get("app_visibility_confirmed", 0) or 0) > 0 else "blocked",
            "evidence": (
                "Erika DF Messages / All Messages shows Workflow App Message rows marked Sent, with Installed / Logged In visible."
                if app_visibility_done
                else f"{pilot.get('app_visibility_confirmed', 0)} of {pilot.get('clients', 0)} pilot app/portal visibility confirmations recorded."
            ),
            "next_step": (
                "Use this proof only for the narrow Erika gate; before any new client-facing action, require one exact Installed / Logged In test client and campaign/action approval."
                if app_visibility_done
                else "Get visual app/portal confirmation for Erika and the five pilot clients before broad rollout."
            ),
        },
        {
            "area": "HighLevel inbox reading",
            "status": "blocked" if "HighLevel" in blockers else "pass",
            "evidence": next((item for item in report.get("blockers", []) if "HighLevel" in item), "No HighLevel blocker detected."),
            "next_step": "Use `make highlevel-inbox-workaround` for exported/copied inbox rows now; update the Private Integration scopes when login is available.",
        },
        {
            "area": "Permanent Cloudflare tunnel",
            "status": "blocked" if cloudflare_blocked else "pass",
            "evidence": next((item for item in report.get("blockers", []) if "Cloudflare" in item), "No Cloudflare blocker detected."),
            "next_step": (
                "Authorize Cloudflare Tunnel after a selectable domain/zone exists and set FUNDZ_TUNNEL_HOSTNAME."
                if cloudflare_blocked
                else "Repeat `make webhook-probe` after any bridge/tunnel restart or payload change; do not wire the webhook live without Brandon's approval."
            ),
        },
        {
            "area": "One-member app-communication campaign pilot",
            "status": "pass" if app_communication_done and app_visibility_done else ("review" if app_communication_done else "blocked"),
            "evidence": (
                "Erika Jordan assignment proof and DF App Message visibility proof both exist; DF showed Mobile App SMS and Email success, with the old regular SMS action failed/paused."
                if app_communication_done and app_visibility_done
                else "Erika Jordan assignment proof exists; DF showed Mobile App SMS and Email success, with the old regular SMS action failed/paused."
                if app_communication_done
                else "Campaign exists, but no one-member assignment receipt and app visibility proof are recorded in local reports."
            ),
            "next_step": (
                "Do not expand broadly; next live action is one explicitly approved Installed / Logged In test client only."
                if app_communication_done and app_visibility_done
                else "Get Erika/Brandon app or portal visibility confirmation before expanding the campaign."
                if app_communication_done
                else "Assign `FUNDz App Communication Notice - Email SMS App` to one known member only after action-time approval."
            ),
        },
        {
            "area": "Old AutoFox workflow cleanup",
            "status": "review",
            "evidence": (
                "Round 1-10 sent campaigns and Round 1-4 score updates have Mobile App SMS proof; "
                f"older app-communication regular SMS pause proof is {'present' if app_communication_paused_proof.exists() else 'not present'}."
            ),
            "next_step": "Verify Round 5-10 score-update coverage, then test one DF delayed credit-tip step before adding the 20-tip schedule.",
        },
        {
            "area": "HighLevel conversation/history reconciliation",
            "status": "blocked" if "HighLevel" in blockers else "review",
            "evidence": "Provider receipts exist, but conversation snapshots/reply monitoring still depend on readable conversations.",
            "next_step": "After inbox scope is fixed, snapshot pilot conversations and classify replies.",
        },
        {
            "area": "Supabase command-line sync",
            "status": "pass" if has_database_url else "blocked",
            "evidence": (
                "A real local Postgres database URL is configured for `make supabase-memory-sync`."
                if has_database_url
                else "No real Postgres URL is configured locally; dashboard SQL chunks remain the available sync path."
            ),
            "next_step": (
                "Run `make supabase-memory-sync`, then confirm the live row counts."
                if has_database_url
                else "Add a real Supabase/Postgres connection string to `.env.local` as `FUNDZ_MEMORY_DATABASE_URL` or `SUPABASE_DB_URL`, or run `make supabase-dashboard-sql`."
            ),
        },
        {
            "area": "Broad outreach rollout closeout",
            "status": "pass",
            "evidence": (
                "Marked complete as a parked/gated closeout: local previews and send visibility exist, "
                "and live broad outreach remains intentionally blocked unless Brandon gives exact action-time approval."
            ),
            "next_step": "Keep live broad outreach off; any future send must start from a fresh owner approval, notice gate, readiness proof, and receipt trail.",
        },
        {
            "area": "CI full test coverage",
            "status": "pass" if ci_tests.exists() else "blocked",
            "evidence": str(ci_tests.relative_to(ROOT)) if ci_tests.exists() else "No Python test workflow found.",
            "next_step": "Keep the Python Tests workflow required after the branch-protection rule is updated.",
        },
        {
            "area": "Branch protection requires full tests",
            "status": "review",
            "evidence": "Local workflow exists, but branch-protection required checks must be verified/updated in GitHub.",
            "next_step": "After the Python Tests workflow has run once, add its status check to the required checks on main.",
        },
    ]
    return checks


def scorefusion_snapshot() -> dict[str, Any]:
    try:
        dashboard = build_scorefusion_dashboard()
    except Exception as error:  # noqa: BLE001 - command center should survive incomplete billing exports.
        return {"ok": False, "error": str(error)}
    metrics = {str(row.get("metric")): row.get("value") for row in dashboard.get("dashboard", [])}
    risk = dashboard.get("billing_risk_summary", {})
    return {
        "ok": True,
        "enrolled": metrics.get("ScoreFusion Enrolled", 0),
        "owed_payments": metrics.get("Owed Payments", 0),
        "total_amount_due": metrics.get("Total Amount Due", "0.00"),
        "failed_at_risk": metrics.get("Failed / At Risk", 0),
        "exceptions": len(dashboard.get("exceptions", [])),
        "billing_risk_review_rows": metrics.get("Billing Risk Review Rows", len(dashboard.get("billing_risk_review_queue", []))),
        "billing_risk_unique_keys": risk.get("unique_keys", metrics.get("Billing Risk Unique Keys", 0)),
        "billing_risk_duplicate_keys": risk.get("duplicate_keys", metrics.get("Billing Risk Duplicate Keys", 0)),
        "billing_risk_rows_in_duplicate_keys": risk.get(
            "rows_in_duplicate_keys", metrics.get("Billing Risk Rows In Duplicate Keys", 0)
        ),
        "billing_review_bucket_summary": dashboard.get("billing_review_bucket_summary", {}),
        "risk_summary": risk,
        "top_risk_clients": dashboard.get("billing_risk_queue", [])[:10],
    }


def row_matches_preview_item(row: dict[str, Any], item: dict[str, Any]) -> bool:
    item_name = normalize_name(str(item.get("client_name") or ""))
    item_key = str(item.get("client_key") or "").strip().lower()
    row_name = normalize_name(str(row.get("client_name") or ""))
    row_key = str(row.get("client_key") or "").strip().lower()
    return bool((item_name and row_name == item_name) or (item_key and row_key == item_key))


def first_matching_row(rows: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    for row in rows:
        if row_matches_preview_item(row, item):
            return row
    return {}


def batch_result_for_id(batch_id: str) -> dict[str, Any]:
    if not batch_id:
        return {}
    result = read_json(RECEIPTS_DIR / f"{batch_id}-result.json")
    return result if isinstance(result, dict) else {}


def batch_receipt_for_id(batch_id: str) -> Path:
    return RECEIPTS_DIR / f"{batch_id}-receipt.md"


def build_preview_packet_decision(report: dict[str, Any]) -> dict[str, Any]:
    packet = read_json(EXPANSION_BATCH_PACKET)
    release_status = {item.get("check"): item.get("status") for item in report.get("release_checklist", [])}
    decision = {
        "generated_at": report.get("generated_at", ""),
        "packet": relative_label(EXPANSION_BATCH_PACKET),
        "report": relative_label(EXPANSION_BATCH_PREVIEW_MD),
        "decision": "hold",
        "reason": "No preview packet was available to review.",
        "reasons": [],
        "notes": [],
        "next_step": "Prepare a new preview-only packet before considering any live action.",
    }
    if not isinstance(packet, dict):
        decision["reasons"] = [decision["reason"]]
        return decision

    raw_items = packet.get("items", [])
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    malformed_item_count = len(raw_items) - len(items) if isinstance(raw_items, list) else 1
    is_capped_ready = packet.get("batch_preset") == "capped_ready_rollout"
    item = items[0] if len(items) == 1 else {}
    send_ready_count = sum(1 for preview_item in items if preview_item.get("send_ready"))
    preview_clients = [
        {
            "client_name": preview_item.get("client_name", ""),
            "client_key": preview_item.get("client_key", ""),
            "status": preview_item.get("status", ""),
            "stage": preview_item.get("stage_in_process", ""),
            "send_ready": bool(preview_item.get("send_ready")),
        }
        for preview_item in items
    ]
    decision.update(
        {
            "batch_id": packet.get("batch_id", ""),
            "mode": packet.get("mode", ""),
            "channel": packet.get("channel", ""),
            "batch_preset": packet.get("batch_preset", ""),
            "ready_only": bool(packet.get("ready_only")),
            "capped_size": safe_int(packet.get("capped_size")),
            "max_batch_size": safe_int(packet.get("max_batch_size"), 5),
            "skipped_candidates": len(packet.get("skipped_candidates", [])) if isinstance(packet.get("skipped_candidates"), list) else 0,
            "selected": len(items) if isinstance(items, list) else 0,
            "client_name": item.get("client_name", ""),
            "client_key": item.get("client_key", ""),
            "status": item.get("status", ""),
            "stage": item.get("stage_in_process", ""),
            "send_ready": bool(items) and send_ready_count == len(items),
            "send_ready_count": send_ready_count,
            "preview_clients": preview_clients,
            "live_send_allowed": bool(packet.get("live_send_allowed")),
        }
    )
    batch_result = batch_result_for_id(str(packet.get("batch_id") or ""))
    if batch_result:
        sent = safe_int(batch_result.get("sent"))
        blocked_or_failed = safe_int(batch_result.get("blocked_or_failed"))
        skipped = safe_int(batch_result.get("skipped"))
        decision.update(
            {
                "batch_result": relative_label(RECEIPTS_DIR / f"{packet.get('batch_id')}-result.json"),
                "batch_receipt": relative_label(batch_receipt_for_id(str(packet.get("batch_id") or ""))),
                "result_sent": sent,
                "result_blocked_or_failed": blocked_or_failed,
                "result_skipped": skipped,
                "approved_batch_send": bool(batch_result.get("approved_batch_send")),
            }
        )
        if sent and not blocked_or_failed:
            decision["decision"] = "sent_complete"
            decision["reason"] = "Approved preview was already sent successfully; do not resend this packet."
            decision["next_step"] = "Monitor for replies or provider issues. Prepare a new preview before any further outreach."
            decision["reasons"] = []
            decision["notes"] = ["Receipt exists for this batch; repeated live sends are blocked by the batch-attempt guard."]
            return decision
        if blocked_or_failed or skipped:
            decision["decision"] = "hold"
            decision["reason"] = "This batch already has a failed, blocked, or skipped result; prepare a new preview before retrying."
            decision["next_step"] = "Review the batch receipt/result, then generate a new one-client preview if another attempt is needed."
            decision["reasons"] = [decision["reason"]]
            decision["notes"] = ["Existing batch result found; do not reuse this packet."]
            return decision

    reasons: list[str] = []
    notes: list[str] = []
    if packet.get("mode") != "batch_preview":
        reasons.append("Packet is not a preview packet.")
    if packet.get("live_send_allowed") is not False:
        reasons.append("Packet does not explicitly block live send.")
    if malformed_item_count:
        reasons.append("Packet contains malformed preview item data.")

    review_items = items if is_capped_ready else ([item] if item else [])
    if is_capped_ready:
        max_batch_size = max(safe_int(packet.get("max_batch_size"), 5), 1)
        capped_size = max(safe_int(packet.get("capped_size"), max_batch_size), 1)
        if not packet.get("ready_only"):
            reasons.append("Capped rollout packet is not marked ready-only.")
        if not items:
            reasons.append("Capped rollout packet has no ready preview items.")
        if len(items) > max_batch_size:
            reasons.append(f"Capped rollout packet exceeds max batch size of {max_batch_size}.")
        if len(items) > capped_size:
            reasons.append(f"Capped rollout packet exceeds its capped size of {capped_size}.")
        not_ready = [preview_item for preview_item in items if not preview_item.get("send_ready")]
        if not_ready:
            reasons.append(f"{len(not_ready)} capped preview item(s) are not send-ready.")
        risky_items = [preview_item for preview_item in items if preview_item.get("risky_hits")]
        if risky_items:
            reasons.append(f"{len(risky_items)} capped preview item(s) have risky-language hits.")
    else:
        if len(items) != 1:
            reasons.append("Packet must contain exactly one preview item for this gate.")
        if not item:
            reasons.append("No single preview item could be reviewed.")
        elif not item.get("send_ready"):
            reasons.append(str(item.get("blocked_reason") or "Preview item is not send-ready."))
        if item.get("risky_hits"):
            reasons.append("Preview message has risky-language hits.")

    billing_rows = read_csv_rows(BILLING_RISK_REVIEW_CSV)
    billing_matches: list[dict[str, Any]] = []
    for preview_item in review_items:
        billing_match = first_matching_row(billing_rows, preview_item)
        if billing_match:
            billing_matches.append({"item": preview_item, "row": billing_match})
    if billing_matches:
        first_match = billing_matches[0]["row"]
        bucket = str(first_match.get("review_bucket") or "billing-risk review")
        if is_capped_ready:
            reasons.append(f"{len(billing_matches)} capped preview item(s) match billing-risk review queue.")
        else:
            reasons.append(f"Preview item matches billing-risk review queue: {bucket}.")
        decision["billing_review_bucket"] = bucket
        decision["billing_next_charge_date"] = first_match.get("next_charge_date", "")
        decision["billing_rollout_treatment"] = first_match.get("rollout_treatment", "")
        decision["billing_review_matches"] = [
            {
                "client_name": match["item"].get("client_name", ""),
                "review_bucket": match["row"].get("review_bucket", ""),
                "next_charge_date": match["row"].get("next_charge_date", ""),
            }
            for match in billing_matches
        ]

    control_rows = report.get("communication_control_board", [])
    if not isinstance(control_rows, list):
        control_rows = read_csv_rows(COMMUNICATION_CONTROL_BOARD_CSV)
    control_matches: list[dict[str, Any]] = []
    for preview_item in review_items:
        control_match = first_matching_row(control_rows, preview_item)
        if control_match:
            control_matches.append({"item": preview_item, "row": control_match})
    if control_matches:
        first_control = control_matches[0]["row"]
        decision["communication_status"] = first_control.get("communication_status", "")
        decision["message_lane"] = first_control.get("message_lane", "")
        if is_capped_ready:
            decision["control_board_matches"] = len(control_matches)
            notes.append(f"{len(control_matches)} capped preview item(s) had control-board rows reviewed.")
        else:
            notes.append(str(first_control.get("block_reason") or "Control board row found."))
        for match in control_matches:
            status = str(match["row"].get("communication_status") or "")
            if status.lower().startswith(("blocked", "failed", "hold")):
                reasons.append(f"Control board status is {status} for {match['item'].get('client_name', 'preview item')}.")

    if release_status.get("Human approval captured") == "blocked":
        notes.append("Live send still requires action-time approval.")
    if release_status.get("Dry run disabled only for approved command") == "blocked":
        notes.append("Dry-run must stay on unless the exact send command is approved.")

    if reasons:
        decision["decision"] = "hold"
        decision["reason"] = reasons[0]
        if is_capped_ready:
            decision["next_step"] = "Hold this capped preview packet. Generate a cleaner ready-only packet or remove the blocked item before approval."
        else:
            decision["next_step"] = "Hold this preview item. Pick a replacement with no billing-risk match, or get explicit owner override after billing review."
    else:
        if is_capped_ready:
            decision["decision"] = "approved_for_capped_batch_action"
            decision["reason"] = "Capped ready-only preview packet passed packet, message, risk, and control-board checks."
            decision["next_step"] = "Approve only this exact capped packet and listed clients; do not broaden or reuse without a new preview."
        else:
            decision["decision"] = "approved_for_one_exact_action"
            decision["reason"] = "Single preview item passed packet, message, risk, and control-board checks."
            decision["next_step"] = "Approve only this packet/client/channel/message combination; do not broaden or reuse without a new preview."
    decision["reasons"] = reasons
    decision["notes"] = list(dict.fromkeys(note for note in notes if note))
    return decision


def billing_rollout_decision(row: dict[str, Any]) -> str:
    bucket = str(row.get("review_bucket") or "")
    risk_level = str(row.get("risk_level") or "")
    if bucket == "urgent_due_now_or_past_due":
        return "hold"
    if bucket == "date_sensitive_next_7_days" and risk_level == "high":
        return "owner_override_needed"
    return "exclude_from_rollout"


def billing_rollout_triage_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in read_csv_rows(BILLING_RISK_REVIEW_CSV):
        bucket = str(row.get("review_bucket") or "")
        if bucket not in {"urgent_due_now_or_past_due", "date_sensitive_next_7_days"}:
            continue
        decision = billing_rollout_decision(row)
        if decision == "hold":
            next_step = "Hold normal rollout. Owner must review billing state before any client-facing update."
        elif decision == "owner_override_needed":
            next_step = "Exclude from normal rollout unless Brandon explicitly approves the exact client/message after billing review."
        else:
            next_step = "Exclude from rollout pool until billing/date-sensitive review is cleared."
        rows.append(
            {
                "client_name": str(row.get("client_name") or ""),
                "risk_level": str(row.get("risk_level") or ""),
                "review_bucket": bucket,
                "rollout_decision": decision,
                "next_charge_date": str(row.get("next_charge_date") or ""),
                "failure_types": str(row.get("failure_types") or ""),
                "amount_due": str(row.get("amount_due") or ""),
                "next_step": next_step,
            }
        )
    return rows


def billing_risk_name_keys() -> set[str]:
    keys: set[str] = set()
    for row in read_csv_rows(BILLING_RISK_REVIEW_CSV):
        name_key = normalize_name(str(row.get("client_name") or ""))
        email_key = str(row.get("email") or "").strip().lower()
        if name_key:
            keys.add(name_key)
        if email_key:
            keys.add(email_key)
    return keys


def control_board_lookup(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    rows = report.get("communication_control_board", [])
    if not isinstance(rows, list):
        rows = read_csv_rows(COMMUNICATION_CONTROL_BOARD_CSV)
    for row in rows:
        name_key = normalize_name(str(row.get("client_name") or ""))
        client_key = str(row.get("client_key") or "").strip().lower()
        if name_key:
            lookup[name_key] = row
        if client_key:
            lookup[client_key] = row
    return lookup


def current_preview_item() -> dict[str, Any]:
    packet = read_json(EXPANSION_BATCH_PACKET)
    if not isinstance(packet, dict):
        return {}
    items = packet.get("items", [])
    if len(items) != 1 or not isinstance(items[0], dict):
        return {}
    item = dict(items[0])
    item["batch_id"] = packet.get("batch_id", "")
    item["channel"] = packet.get("channel", "")
    result = batch_result_for_id(str(packet.get("batch_id") or ""))
    if result:
        item["batch_result_sent"] = safe_int(result.get("sent"))
        item["batch_result_blocked_or_failed"] = safe_int(result.get("blocked_or_failed"))
        item["batch_result_skipped"] = safe_int(result.get("skipped"))
    return item


def sent_batch_client_keys() -> set[str]:
    keys: set[str] = set()
    for path in RECEIPTS_DIR.glob("*-result.json"):
        result = read_json(path)
        if not isinstance(result, dict) or safe_int(result.get("sent")) <= 0:
            continue
        for row in result.get("results", []):
            if not isinstance(row, dict):
                continue
            provider_result = row.get("result") if isinstance(row.get("result"), dict) else {}
            if not (row.get("sent") or provider_result.get("sent")):
                continue
            name_key = normalize_name(str(row.get("client_name") or ""))
            client_key = str(row.get("client_key") or "").strip().lower()
            if name_key:
                keys.add(name_key)
            if client_key:
                keys.add(client_key)
    return keys


def clean_backup_preview_pool(report: dict[str, Any], queue: dict[str, Any], limit: int = 10) -> list[dict[str, str]]:
    billing_keys = billing_risk_name_keys()
    control_lookup = control_board_lookup(report)
    preview = current_preview_item()
    preview_key = str(preview.get("client_key") or "").strip().lower()
    sent_keys = sent_batch_client_keys()
    preview_is_send_ready = bool(preview.get("send_ready")) and not preview.get("blocked_reason") and not preview.get(
        "do_not_send_because"
    )
    preview_was_attempted = bool(
        safe_int(preview.get("batch_result_sent"))
        or safe_int(preview.get("batch_result_blocked_or_failed"))
        or safe_int(preview.get("batch_result_skipped"))
    )
    rows: list[dict[str, str]] = []
    for action in queue.get("actions", []):
        if action.get("action_type") != "draft_for_approval" or action.get("risky_hits"):
            continue
        name_key = normalize_name(str(action.get("client_name") or ""))
        client_key = str(action.get("client_key") or "").strip().lower()
        if name_key in billing_keys or client_key in billing_keys:
            continue
        if name_key in sent_keys or client_key in sent_keys:
            continue
        control = control_lookup.get(client_key) or control_lookup.get(name_key) or {}
        communication_status = str(control.get("communication_status") or "unknown")
        if communication_status.lower().startswith(("blocked", "failed", "hold")):
            continue
        is_current_preview = bool(preview_key and client_key == preview_key)
        if is_current_preview and not preview_is_send_ready:
            continue
        if is_current_preview and preview_was_attempted:
            continue
        resolution = preview.get("resolution", {}) if is_current_preview else {}
        rows.append(
            {
                "candidate_use": "active_approved_preview" if is_current_preview else "backup_preview_candidate",
                "client_name": str(action.get("client_name") or ""),
                "client_key": str(action.get("client_key") or ""),
                "action_type": str(action.get("action_type") or ""),
                "reason": str(action.get("reason") or ""),
                "message_phase": str(action.get("message_phase") or ""),
                "priority_score": str(action.get("priority_score") or ""),
                "communication_status": communication_status,
                "billing_risk_match": "no",
                "contact_resolution": "resolved" if is_current_preview and resolution.get("ok") else "not_checked_in_this_report",
                "preview_recommendation": (
                    "Use only the exact approved preview packet."
                    if is_current_preview
                    else "Backup only; generate a fresh one-client preview before any live action."
                ),
            }
        )
        if len(rows) >= limit:
            break
    return rows


NO_RECENT_CONTACT_INVESTIGATION_FIELDS = [
    "client_name",
    "client_key",
    "status",
    "delivered_message_proof",
    "send_history_linked",
    "sequence_assignment",
    "sequence_assignment_evidence",
    "dry_run_found",
    "dry_run_evidence",
    "recommended_resolution",
    "evidence_summary",
]


def no_recent_contact_investigations(
    report: dict[str, Any],
    *,
    dry_runs_by_contact: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    sequence_assignments = report.get("sequence_assignments", {})
    dry_runs_by_contact = dry_runs_by_contact if dry_runs_by_contact is not None else load_bridge_dry_runs_by_contact()
    rows: list[dict[str, str]] = []
    for ledger_row in report.get("ledger", []):
        if str(ledger_row.get("next_touch_status") or "") != "no-recent-contact-found":
            continue
        client_name = str(ledger_row.get("client_name") or "")
        name_key = normalize_name(client_name)
        assignment = sequence_assignments.get(name_key, {})
        contact_id = str(assignment.get("customer_id") or "").strip()
        dry_run = dry_runs_by_contact.get(contact_id, {}) if contact_id else {}
        evidence = [relative_label(CONTACT_LEDGER_CSV)]
        if assignment.get("evidence"):
            evidence.append(str(assignment.get("evidence")))
        if dry_run.get("evidence"):
            evidence.append(str(dry_run.get("evidence")))
        rows.append(
            {
                "client_name": client_name,
                "client_key": str(ledger_row.get("client_key") or ""),
                "status": "owner_review_required",
                "delivered_message_proof": "no",
                "send_history_linked": "no",
                "sequence_assignment": str(assignment.get("result") or "none"),
                "sequence_assignment_evidence": str(assignment.get("evidence") or ""),
                "dry_run_found": "yes" if dry_run else "no",
                "dry_run_evidence": str(dry_run.get("evidence") or ""),
                "recommended_resolution": (
                    "Keep Needs Brandon. Verify DF Messages/All Messages, HighLevel conversation history, "
                    "or get Brandon's explicit override before outreach."
                ),
                "evidence_summary": "; ".join(dict.fromkeys(evidence)),
            }
        )
    return rows


def build_command_center(limit: int = 10) -> dict[str, Any]:
    load_env_file()
    previous_report = read_json(COMMAND_CENTER_JSON)
    state = build_operational_state()
    queue = build_action_queue(state, limit=500)
    clients = [client for client in state.get("clients", []) if isinstance(client, dict)]
    ledger = build_contact_ledger(clients)
    action_counts = queue.get("summary", {}) if isinstance(queue.get("summary"), dict) else {}
    blockers = [item for item in [cloudflare_blocker(), highlevel_blocker()] if item]
    if not erika_app_message_visibility_proof_exists():
        blockers.append("Credit Tracker app/portal visual confirmation is still pending for the fresh Erika Mobile App SMS test.")

    owner_review = [row for row in ledger if row["next_touch_status"] == "owner-review-before-message"]
    no_recent = [row for row in ledger if row["next_touch_status"] == "no-recent-contact-found"]
    top_actions = ledger[:limit]
    next_batch = [
        action
        for action in queue.get("actions", [])
        if action.get("action_type") == "draft_for_approval" and not action.get("risky_hits")
    ][:5]
    expansion_packet = latest_expansion_packet()
    kill_switch = send_kill_switch_state()
    send_ledger = build_send_ledger(expansion_packet)
    next_send_queue = build_next_send_queue(expansion_packet, kill_switch)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "policy": "Local command center only. Live client sends still require explicit action-time approval.",
        "governor_policy": GOVERNOR_SAFE_FIX_POLICY,
        "summary": {
            "active_clients": state.get("summary", {}).get("active_clients", 0),
            "total_clients": state.get("summary", {}).get("clients", 0),
            "action_counts": action_counts,
            "owner_review_before_message": len(owner_review),
            "no_recent_contact_found": len(no_recent),
            "top_action_count": len(top_actions),
        },
        "blockers": blockers,
        "communication_coverage": {
            "active_clients": len(ledger),
            "with_email": sum(1 for row in ledger if row["has_email"]),
            "with_phone_history": sum(1 for row in ledger if row["has_phone_history"]),
            "no_recent_contact_found": len(no_recent),
            "owner_review_before_message": len(owner_review),
        },
        "top_actions": top_actions,
        "next_safe_batch_candidates": next_batch,
        "duplicate_contacts": duplicate_contact_report(clients),
        "autofox_audit": collect_autofox_audit(),
        "bridge": bridge_status(),
        "scorefusion": scorefusion_snapshot(),
        "receipts": receipt_summary(),
        "safety_gate": build_safety_gate_snapshot(),
        "send_kill_switch": kill_switch,
        "send_ledger": send_ledger,
        "next_send_queue": next_send_queue,
        "pilot_status": build_pilot_status_report(),
        "memory_freshness": memory_freshness(state),
        "sequence_assignments": load_sequence_assignment_receipts(),
        "ledger": ledger,
    }
    report["no_recent_contact_investigations"] = no_recent_contact_investigations(report)
    work_queue = build_work_queue(report)
    fixed_queue, governor_alerts = governor_safe_fix_queue(work_queue)
    report["work_queue"] = fixed_queue
    report["governor_alerts"] = governor_alerts
    report["communication_control_board"] = build_communication_control_board(report)
    report["billing_rollout_triage"] = billing_rollout_triage_rows()
    report["clean_backup_preview_pool"] = clean_backup_preview_pool(report, queue)
    report["what_changed_since_last_run"] = compare_with_previous(report, previous_report if isinstance(previous_report, dict) else None)
    report["release_checklist"] = release_checklist(report)
    report["preview_packet_decision"] = build_preview_packet_decision(report)
    report["backlog_coverage"] = backlog_coverage(report)
    maintenance_summary = read_json(MAINTENANCE_CLEANUP_SUMMARY_JSON)
    report["maintenance_cleanup_summary"] = maintenance_summary if isinstance(maintenance_summary, dict) else {}
    billing_focus_rows = build_billing_maintenance_focus_rows()
    report["billing_maintenance_focus"] = {
        "rows": len(billing_focus_rows),
        "path": relative_label(BILLING_MAINTENANCE_FOCUS_MD),
        "csv": relative_label(BILLING_MAINTENANCE_FOCUS_CSV),
    }
    report["archive_receipt_trail"] = build_archive_receipt_trail()
    report["send_gate_lock"] = {
        "path": relative_label(SEND_GATE_LOCK_MD),
        "preview_rows": len(next_send_queue),
        "allowed_now": sum(1 for row in next_send_queue if str(row.get("send_allowed_now") or "").lower() == "yes"),
        "owner_notice_required": sum(1 for row in next_send_queue if "required" in str(row.get("owner_notice_status") or "").lower()),
    }
    report["no_approval_work_queue"] = no_approval_work_queue(report)
    report["daily_board"] = build_daily_board(report)
    report["missing_steps_recheck"] = missing_steps_recheck(report)
    return report


def write_contact_ledger(rows: list[dict[str, Any]], path: Path = CONTACT_LEDGER_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "priority_score",
        "client_name",
        "phase",
        "cadence",
        "status",
        "stage",
        "next_import",
        "latest_touch",
        "next_touch_status",
        "has_email",
        "has_phone_history",
        "flags",
        "recommended_next_action",
        "client_key",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_dict_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


BILLING_MAINTENANCE_FOCUS_FIELDS = [
    "priority",
    "client_name",
    "decision",
    "risk_level",
    "next_charge_date",
    "system_activity_bucket",
    "system_next_import",
    "system_next_import_days",
    "system_status",
    "amount_due",
    "failure_types",
    "row_count",
    "duplicate_row_count",
    "next_step",
    "source",
]


def billing_focus_priority(row: dict[str, str]) -> int:
    decision = str(row.get("decision") or "")
    priority = {
        "active_urgent_billing_review": 1,
        "active_date_sensitive_billing_review": 2,
        "fix_missing_billing_date": 3,
        "duplicate_review_once": 4,
        "active_standard_billing_review": 5,
    }
    return priority.get(decision, 99)


def billing_focus_date(row: dict[str, str]) -> str:
    date = str(row.get("next_charge_date") or "").strip()
    return date if re.match(r"^\d{4}-\d{2}-\d{2}$", date) else "9999-12-31"


def build_billing_maintenance_focus_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    focus_decisions = {
        "active_urgent_billing_review",
        "active_date_sensitive_billing_review",
        "active_standard_billing_review",
        "fix_missing_billing_date",
        "duplicate_review_once",
    }

    source_path = ACTIVE_BILLING_ISSUES_CSV if ACTIVE_BILLING_ISSUES_CSV.exists() else BILLING_MAINTENANCE_REVIEW_CSV
    for row in read_csv_rows(source_path):
        decision = str(row.get("decision") or "")
        if decision not in focus_decisions:
            continue
        key = (normalize_name(str(row.get("client_name") or "")), decision)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "priority": str(billing_focus_priority(row)),
                "client_name": str(row.get("client_name") or ""),
                "decision": decision,
                "risk_level": str(row.get("risk_level") or ""),
                "next_charge_date": str(row.get("next_charge_date") or ""),
                "system_activity_bucket": str(row.get("system_activity_bucket") or ""),
                "system_next_import": str(row.get("system_next_import") or ""),
                "system_next_import_days": str(row.get("system_next_import_days") or ""),
                "system_status": str(row.get("system_status") or ""),
                "amount_due": str(row.get("amount_due") or ""),
                "failure_types": str(row.get("failure_types") or ""),
                "row_count": str(row.get("row_count") or ""),
                "duplicate_row_count": str(row.get("duplicate_row_count") or ""),
                "next_step": str(row.get("next_step") or ""),
                "source": relative_label(source_path),
            }
        )

    return sorted(rows, key=lambda item: (safe_int(item["priority"]), billing_focus_date(item), item["client_name"].lower()))


def write_billing_maintenance_focus(
    report: dict[str, Any],
    md_path: Path = BILLING_MAINTENANCE_FOCUS_MD,
    csv_path: Path = BILLING_MAINTENANCE_FOCUS_CSV,
) -> None:
    rows = build_billing_maintenance_focus_rows()
    write_dict_csv(csv_path, rows, BILLING_MAINTENANCE_FOCUS_FIELDS)

    maintenance = report.get("maintenance_cleanup_summary") if isinstance(report.get("maintenance_cleanup_summary"), dict) else {}
    decisions = maintenance.get("billing_decisions") if isinstance(maintenance.get("billing_decisions"), dict) else {}
    lines = [
        "# FUNDz Billing Maintenance Focus",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "This is maintenance only. Do not contact clients, start billing warnings, assign campaigns, or edit live billing records from this list.",
        "",
        "## Counts To Work",
        f"- Active billing issue clients: {maintenance.get('active_billing_issue_clients', len(rows))}",
        f"- Urgent billing review: {decisions.get('active_urgent_billing_review', 0)}",
        f"- Date-sensitive billing reviews: {decisions.get('active_date_sensitive_billing_review', 0)}",
        f"- Standard billing reviews: {decisions.get('active_standard_billing_review', 0)}",
        f"- Missing billing dates: {decisions.get('fix_missing_billing_date', 0)}",
        f"- Duplicate-review clients: {maintenance.get('duplicate_review_clients', decisions.get('duplicate_review_once', 0))}",
        f"- Excluded non-active/stale/not-found billing clients: {maintenance.get('non_active_billing_clients', 0)}",
        f"- Owner-updated billing clients moved out of issue side: {maintenance.get('owner_updated_billing_clients', 0)}",
        f"- Stale next-import clients excluded: {maintenance.get('stale_next_import_billing_clients', 0)}",
        f"- Not found in active system export: {maintenance.get('not_in_active_system_billing_clients', 0)}",
        f"- Active export missing next import: {maintenance.get('active_system_missing_next_import_clients', 0)}",
        f"- Non-active CSV: `{relative_label(NON_ACTIVE_BILLING_REVIEW_CSV)}`",
        f"- Focus CSV: `{relative_label(csv_path)}`",
        f"- Source board: `{relative_label(MAINTENANCE_CLEANUP_MD)}`",
        "",
        "## Maintenance Order",
        "1. Clear the urgent row first by recording payment-state proof or a clean hold reason.",
        "2. Work the date-sensitive rows in next-charge-date order.",
        "3. Fill missing billing dates before treating any row as low risk.",
        "4. Review duplicate clients once, then mark the duplicate evidence instead of creating extra work.",
        "5. Standard rows stay in review until the higher-risk buckets are clean.",
        "",
        "## First Rows",
    ]
    if not rows:
        lines.append("- No active billing maintenance rows found.")
    for row in rows[:25]:
        lines.append(
            f"- P{row.get('priority')} | {row.get('client_name')} | {row.get('decision')} | "
            f"next charge {row.get('next_charge_date') or 'missing'} | "
            f"system import {row.get('system_next_import') or 'unknown'} | "
            f"{row.get('failure_types') or 'review'} | {row.get('next_step')}"
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_archive_receipt_trail() -> dict[str, Any]:
    review_rows = read_csv_rows(STALE_IMPORT_ARCHIVE_REVIEW_CSV)
    exception_rows = read_csv_rows(STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV)
    live_receipt_path = latest_receipt_file("fundz-df-stale-import-live-archive-*.json")
    live_receipt_md = (
        live_receipt_path.with_name(live_receipt_path.stem + "-receipt.md")
        if live_receipt_path
        else None
    )
    live_receipt = read_json(live_receipt_path) if live_receipt_path else {}
    if not isinstance(live_receipt, dict):
        live_receipt = {}
    verification = live_receipt.get("authenticated_bucket_verification")
    if not isinstance(verification, dict):
        verification = {}
    decision_counts = Counter(str(row.get("archive_decision") or "unknown") for row in review_rows)
    return {
        "archive_candidates_total": safe_int(live_receipt.get("archive_candidates_total")) or len(review_rows),
        "review_rows": len(review_rows),
        "live_confirmed": decision_counts.get("already_archived_live_confirmed", 0) or safe_int(live_receipt.get("live_confirmed")),
        "exceptions": len(exception_rows),
        "bulk_targets_in_active_bucket": safe_int(verification.get("bulk_targets_in_active_bucket")),
        "bulk_targets_in_archived_bucket": safe_int(verification.get("bulk_targets_in_archived_bucket")),
        "review_path": relative_label(STALE_IMPORT_ARCHIVE_REVIEW_MD),
        "review_csv": relative_label(STALE_IMPORT_ARCHIVE_REVIEW_CSV),
        "exceptions_csv": relative_label(STALE_IMPORT_ARCHIVE_EXCLUSIONS_CSV),
        "live_receipt_json": relative_label(live_receipt_path) if live_receipt_path else "",
        "live_receipt_md": relative_label(live_receipt_md) if live_receipt_md and live_receipt_md.exists() else "",
        "exception_names": [str(row.get("client_name") or "") for row in exception_rows if row.get("client_name")],
    }


def write_archive_receipt_trail(
    report: dict[str, Any],
    path: Path = ARCHIVE_RECEIPT_TRAIL_MD,
) -> None:
    trail = report.get("archive_receipt_trail") if isinstance(report.get("archive_receipt_trail"), dict) else build_archive_receipt_trail()
    lines = [
        "# FUNDz Archive Receipt Trail",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "This is the audit surface for stale-import DF archive work. It proves archive state; it is not an outreach or live-send approval.",
        "",
        "## Receipt Summary",
        f"- Stale-import archive candidates: {trail.get('archive_candidates_total', 0)}",
        f"- Review rows: {trail.get('review_rows', 0)}",
        f"- Live DF archive confirmations recorded: {trail.get('live_confirmed', 0)}",
        f"- Owner exceptions recorded: {trail.get('exceptions', 0)}",
        f"- Bulk targets still in active bucket: {trail.get('bulk_targets_in_active_bucket', 0)}",
        f"- Bulk targets visible in archived bucket: {trail.get('bulk_targets_in_archived_bucket', 0)}",
        "",
        "## Audit Links",
        f"- Review packet: `{trail.get('review_path')}`",
        f"- Review CSV: `{trail.get('review_csv')}`",
        f"- Exceptions CSV: `{trail.get('exceptions_csv')}`",
        f"- Live receipt JSON: `{trail.get('live_receipt_json') or 'not found'}`",
        f"- Live receipt markdown: `{trail.get('live_receipt_md') or 'not found'}`",
        "",
        "## Exceptions",
    ]
    exception_names = trail.get("exception_names") if isinstance(trail.get("exception_names"), list) else []
    if not exception_names:
        lines.append("- No owner exceptions recorded.")
    for name in exception_names:
        lines.append(f"- {name}")
    lines.extend(
        [
            "",
            "## Audit Rule",
            "- A stale-import row is closed only when the review row, exception row, or authenticated DF receipt is visible here.",
            "- If a name is not in the receipt trail, do not assume it was archived.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_send_gate_lock(report: dict[str, Any], path: Path = SEND_GATE_LOCK_MD) -> None:
    safety = report.get("safety_gate") if isinstance(report.get("safety_gate"), dict) else {}
    next_queue = report.get("next_send_queue") if isinstance(report.get("next_send_queue"), list) else []
    allowed_now = sum(1 for row in next_queue if str(row.get("send_allowed_now") or "").lower() == "yes")
    notice_required = sum(
        1
        for row in next_queue
        if "required" in str(row.get("owner_notice_status") or "").lower()
        or safe_int(row.get("owner_notice_remaining_seconds")) > 0
    )
    lines = [
        "# FUNDz Send Gate Lock",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "Preview rows are allowed to exist. Live sends are not allowed unless Brandon intentionally uses owner approval and the two-minute notice gate.",
        "",
        "## Lock State",
        f"- Previewable next-send rows: {len(next_queue)}",
        f"- Send allowed now: {allowed_now}",
        f"- Owner notice required or cooling down: {notice_required}",
        f"- Approval required: {safety.get('approval_required', True)}",
        f"- Live send allowed: {safety.get('live_send_allowed', False)}",
        f"- Rollout selected: {safety.get('rollout_selected', 0)}",
        f"- Queue CSV: `{relative_label(NEXT_SEND_QUEUE_CSV)}`",
        "",
        "## Rows",
    ]
    if not next_queue:
        lines.append("- No next-send preview rows.")
    for row in next_queue:
        lines.append(
            f"- #{row.get('queue_rank', '')} | {row.get('client_or_lead', '')} | {row.get('channel', '')} | "
            f"allowed now {row.get('send_allowed_now', 'no')} | notice {row.get('owner_notice_status', '')} | "
            f"{row.get('blocked_reason', 'Approval gates still apply.')}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_drilldown_csvs(report: dict[str, Any]) -> None:
    ledger = report.get("ledger", [])
    owner_review = [row for row in ledger if row.get("next_touch_status") == "owner-review-before-message"]
    no_recent = [row for row in ledger if row.get("next_touch_status") == "no-recent-contact-found"]
    sequence_assignments = report.get("sequence_assignments", {})
    no_recent_enriched: list[dict[str, Any]] = []
    for row in no_recent:
        enriched = dict(row)
        sequence_assignment = sequence_assignments.get(normalize_name(str(row.get("client_name") or "")), {})
        enriched["sequence_assignment"] = sequence_assignment.get("result", "")
        enriched["sequence_assignment_evidence"] = sequence_assignment.get("evidence", "")
        no_recent_enriched.append(enriched)
    ledger_fields = [
        "priority_score",
        "client_name",
        "phase",
        "status",
        "stage",
        "next_import",
        "flags",
        "recommended_next_action",
        "client_key",
    ]
    write_dict_csv(OWNER_REVIEW_CSV, owner_review, ledger_fields)
    write_dict_csv(NO_RECENT_CONTACT_CSV, no_recent_enriched, ledger_fields + ["sequence_assignment", "sequence_assignment_evidence"])
    batch_fields = [
        "candidate_use",
        "client_name",
        "action_type",
        "reason",
        "message_phase",
        "priority_score",
        "client_key",
        "communication_status",
        "billing_risk_match",
        "contact_resolution",
        "preview_recommendation",
    ]
    write_dict_csv(SAFE_BATCH_CSV, report.get("clean_backup_preview_pool") or report.get("next_safe_batch_candidates", []), batch_fields)


def write_autofox_migration_checklist(report: dict[str, Any], path: Path = AUTOFOX_MIGRATION_MD) -> None:
    lines = [
        "# FUNDz AutoFox Mobile App SMS Migration Checklist",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Do not disable or delete old regular SMS actions without Brandon's action-time approval.",
        "",
        "## Already Updated / Verified",
        "- Client (step 02) - Client On-Boarding & Portal Login: Step 1 has Mobile App SMS.",
        "- Client (step 04) - Round 1 Sent & Campaign: Steps 1, 2, 3, and 4 have Mobile App SMS.",
        "- Client (step 06) - Round 2 Sent & Campaign: Steps 1, 2, and 3 have Mobile App SMS.",
        "- Client (step 08) - Round 3 Sent & Campaign: Steps 1 and 4 have Mobile App SMS.",
        "- Client (step 10) - Round 4 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 12) - Round 5 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 14) - Round 6 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 16) - Round 7 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 18) - Round 8 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 20) - Round 9 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 22) - Round 10 Sent & Campaign: Steps 1 and 3 have Mobile App SMS.",
        "- Client (step 05) - Round 1 Score Update: matching Mobile App SMS saved.",
        "- Client (step 07) - Round 2 Score Update: matching Mobile App SMS saved.",
        "- Client (step 09) - Round 3 Score Update: matching Mobile App SMS saved.",
        "- Client (step 11) - Round 4 Score Update: matching Mobile App SMS saved.",
        "- FUNDz App Communication Notice - Email SMS App: SMS, Mobile App SMS, and Email are saved in the instant step.",
        "- Client (step 04) - Round 1 Sent & Campaign: Credit Tip 01, 02, and 03 delayed steps have saved Mobile App SMS actions and internal note markers.",
        "",
        "## Still Needs Review",
        "- Next controlled credit-tip target: Credit Tip 04 only in `Client (step 04) - Round 1 Sent & Campaign` (`autofox_id=160038`). Create Step 9 as `Credit Tip 04 - Statement Dates (24 Days)` with Delay / Days / 24, add `Credit Tip 04 - Statement Dates Mobile App SMS`, add `FUNDz marker - Credit Tip 04 Step 9`, and save screenshot/receipt proof.",
        "- After Tip 04 is proven, Credit Tip 05 through Credit Tip 20 still need DF delayed Mobile App SMS actions saved one controlled step at a time.",
        "- Round 5 through Round 10 score-update campaigns need DF proof before relying on Mobile App SMS coverage.",
        "- Problem/Owner Review internal task actions need DF proof for billing issue, app SMS failed, no app login, no import, no response, duplicate messaging, stale round, and high-touch confusion.",
        "- Any onboarding, reminder, reactivation, billing-warning, cancellation, or custom AutoFox sequence outside the verified list above.",
        "- Any old running workflow where retro-added Mobile App SMS actions remain In-Progress.",
        "- Any campaign that still has regular SMS without a matching Mobile App SMS action.",
        "",
        "## Proof Required Per Campaign",
        "- Campaign name and AutoFox ID.",
        "- Step/action list showing Mobile App SMS saved.",
        "- Activity-history proof after one controlled assignment.",
        "- App/portal visibility confirmation before broad assignment.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_member_experience_system(
    report: dict[str, Any],
    path: Path = MEMBER_EXPERIENCE_MD,
    tips_csv_path: Path = MEMBER_EXPERIENCE_TIPS_CSV,
) -> None:
    lines = [
        "# FUNDz AutoFox Member Experience System",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "This is the working source of truth for the four-lane DisputeFox/AutoFox member experience. Use Mobile App SMS as the main member channel, keep email as the richer backup channel, and do not add or remove regular SMS without Brandon's action-time approval.",
        "",
        "## Lanes",
        "- Onboarding: app invitation, app not installed/logged in, missing ID, proof of address, SSN card, missing Credit Tracker import, and app habit training.",
        "- Round Updates: Round 1 through Round 10 sent campaigns, score updates, next-round preparation, no-action-needed updates, and short what-happens-next explanations.",
        "- Education / Credit Tips: two short Mobile App SMS tips per round, one 3 days after the round is sent and one 10 days after the round is sent.",
        "- Problem / Owner Review: billing issue, app SMS failed, no app login, no import, no response, possible duplicate messaging, stale round, and client confusion/high-touch review.",
        "",
        "## Channel Rules",
        "- Use Mobile App SMS for short member-facing app messages.",
        "- Use email for richer companion updates and future branded cards.",
        "- Do not assume Mobile App SMS supports images until a safe profile proves it.",
        "- Do not send normal progress or education messages to billing/problem clients until cleared.",
        "- Avoid promises of deletions, score increases, or guaranteed bureau results.",
        "",
        "## Core Onboarding Message",
        "```text",
        "Hi [FIRST-NAME], quick setup reminder from FUNDz. Please check your Credit Tracker app and complete any missing setup items so we can keep your file moving. If you need help, reply in the app.",
        "```",
        "",
        "## Owner Review Holding Message",
        "```text",
        "Hi [FIRST-NAME], your file may need a quick account review before we give the next full update. We are checking it so we do not give you the wrong information.",
        "```",
        "",
        "## Round Workflow Map",
        "| Round | Sent campaign | AutoFox ID | Mobile App SMS status | Score update ID |",
        "| --- | --- | --- | --- | --- |",
    ]
    for workflow in ROUND_WORKFLOWS:
        lines.append(
            f"| {workflow['round']} | {workflow['workflow']} | {workflow['autofox_id']} | {workflow['mobile_app_status']} | {workflow['score_update_id']} |"
        )
    lines.extend(
        [
            "",
            "## Credit Tip Implementation Status",
            "",
            "Implementation status: the DF delayed-step blocker is cleared for the controlled Round 1 template. Credit Tips 01, 02, and 03 are saved with Mobile App SMS actions and internal note markers in `Client (step 04) - Round 1 Sent & Campaign` (`autofox_id=160038`).",
            "",
            "Next controlled target: Credit Tip 04 only. Use the same pattern: one delayed step, one Mobile App SMS action, one internal DF note marker, screenshot proof, and no campaign assignment or manual client send.",
            "",
            "## Next Controlled Tip 04 Review Packet",
            "",
            "- Workflow: `Client (step 04) - Round 1 Sent & Campaign`",
            "- AutoFox ID: `160038`",
            "- New step to create: `Step 9 - Credit Tip 04 - Statement Dates (24 Days)`",
            "- Step timing: `Start = Delay`, `Interval Type = Days`, `Interval Value = 24`",
            "- Mobile App SMS action: `Credit Tip 04 - Statement Dates Mobile App SMS`",
            "- Internal note marker title: `FUNDz marker - Credit Tip 04 Step 9`",
            "- Operator preflight/checklist: `data/local/semi-autonomous/receipts/autofox-credit-tip-04-step9-operator-preflight-20260513.md`",
            "- Receipt target: `data/local/semi-autonomous/receipts/autofox-credit-tip-04-step9-mobile-sms-note-proof-20260513.md` plus screenshot",
            "",
            "Mobile App SMS body:",
            "",
            "```text",
            "Credit Tip 4:",
            "A card payment may not show in monitoring right away. Many cards report around the statement date.",
            "",
            "Quick action:",
            "Give balance updates time to report before worrying.",
            "```",
            "",
            "Internal note marker body:",
            "",
            "```text",
            "FUNDz status marker: Round 1 AutoFox Step 9 is Credit Tip 04 - Statement Dates, delayed 24 days, with Mobile App SMS saved. Source workflow: Client (step 04) - Round 1 Sent & Campaign / autofox_id=160038. No manual client send or campaign assignment was performed in this setup pass.",
            "```",
            "",
            "Review gates before live DF work:",
            "",
            "- Confirm Tips 01-03 are still visible with `Mobile App SMS` and `Note Created` rows.",
            "- Do not use `Update Data Fields` unless a clearly dedicated safe marker field is visible.",
            "- Do not assign the campaign, manually send a client message, remove regular SMS, or expand beyond Tip 04.",
            "- After saving, verify the Step 9 row shows both `Mobile App SMS` and `Note Created`, then capture receipt notes/screenshots before moving to Tip 05.",
            "",
            "## Credit Tip Schedule",
            "| Tip | Round | Delay | Action name | Topic |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for tip in CREDIT_TIPS:
        lines.append(f"| {tip['tip']} | {tip['round']} | {tip['delay_days']} days | {tip['action_name']} | {tip['topic']} |")
    lines.extend(
        [
            "",
            "## Credit Tip Copy",
            "",
        ]
    )
    for tip in CREDIT_TIPS:
        lines.extend(
            [
                f"### {tip['action_name']}",
                "",
                f"- Round: {tip['round']}",
                f"- Delay: {tip['delay_days']} days after round sent",
                "- Channel: Mobile App SMS",
                "",
                "```text",
                tip["message"],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Problem / Owner Review Actions",
            "| Condition | Internal action | Priority | Member message? |",
            "| --- | --- | --- | --- |",
        ]
    )
    for action in OWNER_REVIEW_ACTIONS:
        has_message = "yes" if action.get("member_message") else "no"
        lines.append(
            f"| {action['condition']} | {action['internal_action_name']} | {action['priority']} | {has_message} |"
        )
    lines.extend(
        [
            "",
            "## DF Implementation Checklist",
            "- Confirm every new action is Mobile App SMS, not regular SMS.",
            "- Confirm each message body saved correctly.",
            "- Confirm Credit Tip delays are 3 and 10 days after each round sent.",
            "- Confirm no duplicate message is created in the same step.",
            "- Assign one controlled test profile and check DF activity history.",
            "- Confirm the message appears in the app/portal when possible.",
            "- Save screenshots/proof for every updated campaign.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    write_dict_csv(
        tips_csv_path,
        CREDIT_TIPS,
        ["round", "tip", "delay_days", "topic", "action_name", "message"],
    )


def write_owner_review_action_catalog(
    report: dict[str, Any],
    path: Path = OWNER_REVIEW_ACTIONS_MD,
    csv_path: Path = OWNER_REVIEW_ACTIONS_CSV,
) -> None:
    lines = [
        "# FUNDz AutoFox Problem / Owner Review Actions",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Use these for the Problem / Owner Review lane. These are internal-review actions first; member-facing messages should only be added when they help prevent confusion and do not imply a result.",
        "",
        "## Rules",
        "- Do not send normal progress or education messages while one of these problem conditions is unresolved.",
        "- Prefer `Create Task` or another internal action before any member-facing message.",
        "- Use the holding message only when a member needs to know the next update is being checked.",
        "- Do not promise deletions, score changes, or bureau outcomes.",
        "",
    ]
    for action in OWNER_REVIEW_ACTIONS:
        lines.extend(
            [
                f"## {action['condition']}",
                f"- Internal action: {action['internal_action_name']}",
                f"- Action type: {action['action_type']}",
                f"- Priority: {action['priority']}",
                f"- Task note: {action['task_note']}",
            ]
        )
        if action.get("member_message"):
            lines.extend(["", "Member-facing message:", "```text", action["member_message"], "```"])
        else:
            lines.append("- Member-facing message: none by default.")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    write_dict_csv(
        csv_path,
        OWNER_REVIEW_ACTIONS,
        ["condition", "internal_action_name", "action_type", "priority", "task_note", "member_message"],
    )


def owner_review_bucket(row: dict[str, Any]) -> str:
    flags = set(str(row.get("flags") or "").split(";"))
    if "payment_attention" in flags:
        return "billing_attention"
    if "missing_next_import" in flags:
        return "missing_next_import"
    if "setup_incomplete" in flags or "onboarding_incomplete" in flags:
        return "onboarding_or_setup"
    if row.get("phase") == "next-round-window":
        return "next_round_review"
    return "owner_review"


def write_owner_review_packet(report: dict[str, Any], path: Path = OWNER_REVIEW_PACKET_MD) -> None:
    owner_rows = [row for row in report.get("ledger", []) if row.get("next_touch_status") == "owner-review-before-message"]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in owner_rows:
        buckets.setdefault(owner_review_bucket(row), []).append(row)

    labels = {
        "billing_attention": "Billing Attention",
        "missing_next_import": "Missing Next Import",
        "onboarding_or_setup": "Onboarding / Setup",
        "next_round_review": "Next Round Review",
        "owner_review": "Owner Review",
    }
    lines = [
        "# FUNDz Owner Review Packet",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Use this packet before approving broader outreach. These clients should not enter live sends until the listed issue is checked.",
        "",
        "## Summary",
        f"- Owner-review clients: {len(owner_rows)}",
    ]
    for key in ("billing_attention", "missing_next_import", "onboarding_or_setup", "next_round_review", "owner_review"):
        lines.append(f"- {labels[key]}: {len(buckets.get(key, []))}")

    for key in ("billing_attention", "missing_next_import", "onboarding_or_setup", "next_round_review", "owner_review"):
        rows = buckets.get(key, [])
        lines.extend(["", f"## {labels[key]}"])
        if not rows:
            lines.append("- None.")
            continue
        for row in rows[:25]:
            lines.append(
                f"- {row.get('client_name')} | score {row.get('priority_score')} | "
                f"{row.get('status') or 'unknown status'} | {row.get('recommended_next_action')}"
            )
        if len(rows) > 25:
            lines.append(f"- Plus {len(rows) - 25} more in `{relative_label(OWNER_REVIEW_CSV)}`.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def owner_decision_for_row(row: dict[str, Any]) -> dict[str, str]:
    bucket = owner_review_bucket(row)
    flags = set(str(row.get("flags") or "").split(";"))
    recommended = str(row.get("recommended_next_action") or "").strip()
    if bucket == "billing_attention":
        decision = "billing_review_before_outreach"
        approval_options = "hold messaging; approve billing-risk draft; mark billing cleared"
        safest_next = "Review ScoreFusion/HighLevel billing status before any broad touch."
    elif bucket == "missing_next_import":
        decision = "confirm_next_import_or_round_status"
        approval_options = "confirm import date; approve next-round draft; hold until file review"
        safest_next = "Check the latest import/round status, then approve only a status-specific draft."
    elif bucket == "onboarding_or_setup":
        decision = "finish_onboarding_or_setup"
        approval_options = "approve onboarding nudge; hold for owner call; mark setup complete"
        safest_next = "Use a setup/onboarding message only after confirming the missing item."
    elif "no_send_history_linked" in flags:
        decision = "resolve_contact_history"
        approval_options = "lookup contact; approve preview only; hold"
        safest_next = "Resolve contact history before live outreach."
    elif bucket == "next_round_review":
        decision = "approve_next_round_touch"
        approval_options = "approve draft; request edits; hold"
        safest_next = "Approve a next-round-specific Credit Tracker/app plus email draft."
    else:
        decision = "owner_review"
        approval_options = "approve draft; request edits; hold"
        safest_next = recommended or "Review client file before messaging."
    return {
        "priority_score": str(row.get("priority_score", "")),
        "client_name": str(row.get("client_name", "")),
        "decision_needed": decision,
        "review_bucket": bucket,
        "safest_next_action": safest_next,
        "approval_options": approval_options,
        "status": str(row.get("status", "")),
        "stage": str(row.get("stage", "")),
        "next_import": str(row.get("next_import", "")),
        "flags": str(row.get("flags", "")),
        "recommended_next_action": recommended,
        "client_key": str(row.get("client_key", "")),
    }


def build_owner_decision_queue(
    report: dict[str, Any],
    *,
    owner_decisions: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    owner_decisions = owner_decisions if owner_decisions is not None else load_owner_decisions()
    rows = []
    for row in report.get("ledger", []):
        if row.get("next_touch_status") != "owner-review-before-message":
            continue
        client_name = normalize_name(str(row.get("client_name") or ""))
        existing_decision = str((owner_decisions.get(client_name) or {}).get("owner_decision") or "").strip().lower()
        if existing_decision in {"approved", "hold"}:
            continue
        rows.append(owner_decision_for_row(row))
    return sorted(rows, key=lambda row: (-int(row.get("priority_score") or 0), row.get("client_name", "").lower()))


def write_owner_decision_outputs(report: dict[str, Any]) -> None:
    rows = build_owner_decision_queue(report)
    fields = [
        "priority_score",
        "client_name",
        "decision_needed",
        "review_bucket",
        "safest_next_action",
        "approval_options",
        "status",
        "stage",
        "next_import",
        "flags",
        "recommended_next_action",
        "client_key",
    ]
    write_dict_csv(OWNER_DECISION_QUEUE_CSV, rows, fields)

    counts = Counter(row["decision_needed"] for row in rows)
    lines = [
        "# FUNDz Owner Decision Packet",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Use this before any approval-gated outreach. It converts the owner-review queue into concrete decision choices.",
        "",
        "## Decision Counts",
    ]
    if not rows:
        lines.append("- No owner decisions pending.")
    else:
        for key, count in counts.most_common():
            lines.append(f"- {key}: {count}")

    lines.extend(["", "## Top Decisions"])
    for row in rows[:40]:
        lines.append(
            f"- {row['client_name']} | {row['decision_needed']} | score {row['priority_score']} | "
            f"{row['safest_next_action']} Options: {row['approval_options']}."
        )
    if len(rows) > 40:
        lines.append(f"- Plus {len(rows) - 40} more in `{relative_label(OWNER_DECISION_QUEUE_CSV)}`.")

    OWNER_DECISION_PACKET_MD.parent.mkdir(parents=True, exist_ok=True)
    OWNER_DECISION_PACKET_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def today_decision_for_status(status: str) -> str:
    if status == "Hold":
        return "still_hold_until_required_proof"
    if status == "Needs Brandon":
        return "owner_decision_needed"
    if status == "Blocked":
        return "blocked_until_fix_verified"
    if status == "Proof Needed":
        return "attach_proof_before_done"
    return "review"


def build_today_decision_queue(report: dict[str, Any]) -> list[dict[str, str]]:
    statuses = {"Hold", "Needs Brandon", "Blocked", "Proof Needed"}
    rows: list[dict[str, str]] = []
    for row in report.get("work_queue", []):
        status = str(row.get("queue_status") or "")
        if status not in statuses:
            continue
        rows.append(
            {
                "queue_status": status,
                "decision": today_decision_for_status(status),
                "owner": str(row.get("owner") or "Brandon"),
                "lane": str(row.get("lane") or ""),
                "client_name": str(row.get("client_name") or ""),
                "next_step": str(row.get("next_step") or ""),
                "proof_required": str(row.get("proof_required") or ""),
                "evidence": str(row.get("evidence") or ""),
                "priority_score": str(row.get("priority_score") or ""),
                "work_order_id": str(row.get("work_order_id") or ""),
            }
        )
    status_order = {"Blocked": 0, "Proof Needed": 1, "Needs Brandon": 2, "Hold": 3}
    return sorted(
        rows,
        key=lambda item: (
            status_order.get(item["queue_status"], 9),
            -safe_int(item.get("priority_score")),
            item.get("client_name", "").lower(),
        ),
    )


def write_today_operating_board(report: dict[str, Any], path: Path = TODAY_OPERATING_BOARD_MD) -> None:
    safety = report.get("safety_gate") if isinstance(report.get("safety_gate"), dict) else {}
    maintenance = report.get("maintenance_cleanup_summary") if isinstance(report.get("maintenance_cleanup_summary"), dict) else {}
    decisions = build_today_decision_queue(report)
    next_queue = report.get("next_send_queue", [])
    approval_required = "yes" if safety.get("approval_required") else "no"
    live_send_allowed = "yes" if safety.get("live_send_allowed") else "no"
    selected = safety.get("rollout_selected", 0)
    maintenance_decisions = maintenance.get("billing_decisions") if isinstance(maintenance.get("billing_decisions"), dict) else {}
    active_urgent = maintenance_decisions.get("active_urgent_billing_review", 0)
    duplicate_review = maintenance.get("duplicate_review_clients", 0)
    bounced_routes = maintenance.get("bounced_contact_routes", 0)

    lines = [
        "# FUNDz Today Operating Board",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Objective: operate the queue from one surface today. Do not keep re-proving the same safety state unless this board goes stale or a live action is requested.",
        "",
        "## Safety Gate Tile",
        f"- State: {safety.get('state', 'Local reporting only')}",
        f"- Last check: {safety.get('generated_at', 'not recorded')}",
        f"- Steps: {safety.get('successful_steps', 0)}/{safety.get('total_steps', 0)}; maintenance: {safety.get('maintenance_steps', '0/0')}",
        f"- Approval required: {approval_required}",
        f"- Live send allowed: {live_send_allowed}",
        f"- Rollout selected: {selected}",
        f"- Runtime quiet: {'yes' if safety.get('runtime_quiet') else 'no'}",
        f"- Status file: `{safety.get('status_path', relative_label(AUTONOMY_STATUS_MD))}`",
        f"- Meaning: {safety.get('note', 'Client sends remain off; use this as local reporting only.')}",
        "",
        "## Today’s Top 3",
        f"1. Clear or label the {len(decisions)} hold/attention item(s): keep hold, attach proof, assign an owner, or record the exact next step.",
        f"2. Work maintenance without reopening outreach: urgent billing reviews {active_urgent}, bounced routes {bounced_routes}, duplicate-review clients {duplicate_review}.",
        "3. For LOGIC/Governor changes, require the live-visible smoke test or Sheet approval in the first instruction before calling anything done.",
        "",
        "## Waiting On Brandon",
    ]
    if not decisions:
        lines.append("- No Brandon hold/attention items are pending in the local work queue.")
    for row in decisions[:20]:
        lines.append(
            f"- {row['client_name'] or row['work_order_id']} | {row['queue_status']} | {row['decision']} | "
            f"{row['next_step']} Proof: {row['proof_required']} Evidence: `{row['evidence']}`"
        )

    lines.extend(
        [
            "",
            "## Waiting On Lucy / Jay",
            "- Daily closeout must come through `/workorder` with status, summary, next step, owner, due date, and proof. If proof is missing, do not mark done.",
            "- Use LOGIC for dispute questions only after the Slack-visible behavior is proven in the live surface they will use.",
            "",
            "## Blocked By Auth / Approval",
            "- Google Sheet updates: if a Drive batch approval is pending, approve or cancel it before asking Codex to recreate the same rows.",
            "- Slack browser tests: auth/code prompts are blockers; do not call a LOGIC change finished until the visible Slack smoke test passes.",
            "- Command Center runtime: allowed dashboard/reporting runtime may be awake; live-send runtime is still blocked unless the safety tile says otherwise.",
            "",
            "## Done With Proof",
            f"- Command Center generated: `{relative_label(COMMAND_CENTER_MD)}`",
            f"- Maintenance status: `{safety.get('maintenance_status_path', relative_label(MAINTENANCE_AUTOPILOT_STATUS_MD))}`",
            f"- Billing maintenance focus: `{relative_label(BILLING_MAINTENANCE_FOCUS_MD)}`",
            f"- Archive receipt trail: `{relative_label(ARCHIVE_RECEIPT_TRAIL_MD)}`",
            f"- Send gate lock: `{relative_label(SEND_GATE_LOCK_MD)}`",
            f"- Next-send queue rows: {len(next_queue)}; allowed now: {sum(1 for row in next_queue if row.get('send_allowed_now') == 'yes')}",
            f"- Today decision queue CSV: `{relative_label(TODAY_DECISION_QUEUE_CSV)}`",
            "",
            "## Work-Order Prompt Format",
            "- System: FUNDZ, LOGIC, Governor, GHL Agent, or My Day to Day.",
            "- Exact goal: one sentence with the finish line.",
            "- Proof required: screenshot, receipt path, live smoke test, Sheet row, or test output.",
            "- Do not touch: live sends, CRM edits, Slack sends, billing changes, or anything else outside the lane.",
            "- Report to: Today Board, Work Orders sheet, Slack, local file, or final answer.",
            "- Acceptance: what must be visible before the task is called done.",
        ]
    )

    findings = safety.get("safety_findings") if isinstance(safety.get("safety_findings"), list) else []
    lines.extend(["", "## Safety Findings To Avoid Re-Checking"])
    if findings:
        for finding in findings:
            lines.append(f"- {finding}")
    else:
        lines.append("- None in the last available autonomy status.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    write_dict_csv(
        TODAY_DECISION_QUEUE_CSV,
        decisions,
        [
            "queue_status",
            "decision",
            "owner",
            "lane",
            "client_name",
            "next_step",
            "proof_required",
            "evidence",
            "priority_score",
            "work_order_id",
        ],
    )


def write_gap_closure_plan(report: dict[str, Any], path: Path = GAP_CLOSURE_MD) -> None:
    lines = [
        "# FUNDz Gap Closure Plan",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "This file separates completed local capability from blocked external/live work.",
        "",
        "## Backlog Coverage",
    ]
    for row in report.get("backlog_coverage", []):
        lines.append(f"- {row.get('status')}: {row.get('area')} - {row.get('gap')}")

    lines.extend(["", "## No-Approval Work Queue"])
    for row in report.get("no_approval_work_queue", []):
        lines.append(f"- P{row.get('priority')} {row.get('work_item')}: input `{row.get('input')}`; output {row.get('output')}")

    lines.extend(["", "## External / Approval Blockers"])
    for blocker in report.get("blockers", []):
        lines.append(f"- {blocker}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_missing_steps_recheck(report: dict[str, Any], path: Path = MISSING_STEPS_RECHECK_MD) -> None:
    rows = report.get("missing_steps_recheck", [])
    counts = Counter(str(row.get("status") or "unknown") for row in rows)
    lines = [
        "# FUNDz Missing Steps Recheck",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "This is the current gap list after local rechecks. It separates built local capability from blocked live proof.",
        "",
        "## Summary",
    ]
    for status, count in counts.most_common():
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Checks"])
    for row in rows:
        lines.extend(
            [
                f"### {row.get('area')}",
                f"- Status: {row.get('status')}",
                f"- Evidence: {row.get('evidence')}",
                f"- Next step: {row.get('next_step')}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_billing_rollout_triage(
    report: dict[str, Any],
    md_path: Path = BILLING_ROLLOUT_TRIAGE_MD,
    csv_path: Path = BILLING_ROLLOUT_TRIAGE_CSV,
) -> None:
    rows = report.get("billing_rollout_triage", [])
    counts = Counter(str(row.get("rollout_decision") or "unknown") for row in rows)
    fields = [
        "client_name",
        "risk_level",
        "review_bucket",
        "rollout_decision",
        "next_charge_date",
        "failure_types",
        "amount_due",
        "next_step",
    ]
    write_dict_csv(csv_path, rows, fields)
    lines = [
        "# FUNDz Billing Rollout Triage",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "Use this before normal rollout work. These rows are not clean rollout candidates.",
        "",
        "## Summary",
        f"- Rows triaged: {len(rows)}",
        f"- Hold: {counts.get('hold', 0)}",
        f"- Owner override needed: {counts.get('owner_override_needed', 0)}",
        f"- Exclude from rollout: {counts.get('exclude_from_rollout', 0)}",
        "",
        "## Operating Rule",
        "- Billing-risk rows do not enter normal next-round rollout.",
        "- Date-sensitive rows require billing review or explicit owner override before client-facing outreach.",
        "- This triage does not approve billing-warning messages.",
        "",
        "## Rows",
        "| Decision | Risk | Bucket | Next charge | Amount | Failure types | Next step |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "rollout_decision",
                    "risk_level",
                    "review_bucket",
                    "next_charge_date",
                    "amount_due",
                    "failure_types",
                    "next_step",
                )
            )
            + " |"
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_clean_backup_preview_pool(
    report: dict[str, Any],
    md_path: Path = CLEAN_BACKUP_PREVIEW_MD,
    csv_path: Path = CLEAN_BACKUP_PREVIEW_CSV,
) -> None:
    rows = report.get("clean_backup_preview_pool", [])
    fields = [
        "candidate_use",
        "client_name",
        "client_key",
        "action_type",
        "reason",
        "message_phase",
        "priority_score",
        "communication_status",
        "billing_risk_match",
        "contact_resolution",
        "preview_recommendation",
    ]
    write_dict_csv(csv_path, rows, fields)
    counts = Counter(str(row.get("candidate_use") or "unknown") for row in rows)
    lines = [
        "# FUNDz Clean Preview Backup Candidates",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "These are no-billing-risk rollout candidates. Backups still require a fresh one-client preview before live action.",
        "",
        "## Summary",
        f"- Total clean candidates listed: {len(rows)}",
        f"- Active approved preview: {counts.get('active_approved_preview', 0)}",
        f"- Backup preview candidates: {counts.get('backup_preview_candidate', 0)}",
        "",
        "## Candidates",
        "| Use | Client | Status | Phase | Contact | Recommendation |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "candidate_use",
                    "client_name",
                    "communication_status",
                    "message_phase",
                    "contact_resolution",
                    "preview_recommendation",
                )
            )
            + " |"
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


WORK_QUEUE_FIELDS = [
    "work_order_id",
    "created_at",
    "updated_at",
    "actor",
    "system",
    "lane",
    "queue_status",
    "client_key",
    "client_name",
    "source_status",
    "owner",
    "due_date",
    "next_step",
    "proof_required",
    "proof",
    "evidence",
    "priority_score",
    "flags",
    "browser_required",
    "do_not_send_because",
    "safe_fix_applied",
    "duplicate_of",
]


def write_work_queue_outputs(report: dict[str, Any]) -> None:
    rows = report.get("work_queue", [])
    write_dict_csv(WORK_QUEUE_CSV, rows, WORK_QUEUE_FIELDS)
    # Same shape, separate name: this is the import surface for the shared Google Sheet Work Queue tab.
    write_dict_csv(WORK_QUEUE_SHEET_IMPORT_CSV, rows, WORK_QUEUE_FIELDS)
    write_dict_csv(
        GOVERNOR_ALERTS_CSV,
        report.get("governor_alerts", []),
        ["alert_id", "reason", "queue_status", "work_order_id", "client_name", "system", "owner", "evidence", "next_step"],
    )


def write_send_kill_switch_status(report: dict[str, Any], path: Path = SEND_KILL_SWITCH_MD) -> None:
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    SEND_KILL_SWITCH_JSON.parent.mkdir(parents=True, exist_ok=True)
    if not SEND_KILL_SWITCH_JSON.exists():
        SEND_KILL_SWITCH_JSON.write_text(
            json.dumps(
                {
                    "enabled": False,
                    "reason": "Default off; approval gates still apply.",
                    "owner": "Brandon",
                    "updated_at": report.get("generated_at"),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    lines = [
        "# FUNDz Send Kill Switch",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        f"- Status: {kill_switch.get('status', 'unknown')}",
        f"- Enabled: {kill_switch.get('enabled', False)}",
        f"- Reason: {kill_switch.get('reason', '')}",
        f"- Owner: {kill_switch.get('owner', 'Brandon')}",
        f"- Source: {kill_switch.get('source', '')}",
        f"- Control file: {kill_switch.get('control_file', relative_label(SEND_KILL_SWITCH_JSON))}",
        "",
        "## What It Blocks",
        "- Live client sends",
        "- Live lead sends",
        "- Live HighLevel replies",
        "- DF/AutoFox campaign assignment sends",
        "- Webhook-driven client responses",
        "",
        "## What Still Runs",
        "- Local command-center reporting",
        "- Send ledger rebuilds",
        "- Next-send preview queue rebuilds",
        "- Dry-run/no-live-send autonomous operator checks",
        "",
        "## Toggle",
        f"Create or edit `{relative_label(SEND_KILL_SWITCH_JSON)}` with:",
        "",
        "```json",
        '{ "enabled": true, "reason": "Owner pause", "owner": "Brandon" }',
        "```",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_send_visibility(report: dict[str, Any], path: Path = SEND_VISIBILITY_MD) -> None:
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    ledger = report.get("send_ledger", [])
    next_queue = report.get("next_send_queue", [])
    sent_counts = Counter(str(row.get("channel") or "Unknown") for row in ledger if str(row.get("status") or "").lower() == "sent")
    queue_counts = Counter(str(row.get("send_allowed_now") or "no") for row in next_queue)
    lines = [
        "# A FUND Solution Send Visibility Board",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Kill Switch",
        f"- Status: {kill_switch.get('status', 'unknown')}",
        f"- Enabled: {kill_switch.get('enabled', False)}",
        f"- Reason: {kill_switch.get('reason', '')}",
        f"- Control: {relative_label(SEND_KILL_SWITCH_MD)}",
        "",
        "## Sent Ledger",
        f"- Rows: {len(ledger)}",
        f"- CSV: {relative_label(SEND_LEDGER_CSV)}",
    ]
    if sent_counts:
        for channel, count in sent_counts.most_common():
            lines.append(f"- Sent via {channel}: {count}")
    else:
        lines.append("- No sent rows found in local receipts/audits.")
    lines.extend(
        [
            "",
            "### Recent Sent / Attempted Rows",
            "| Sent at | Client/Lead | System | Channel | Status | Message / summary | Proof |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in ledger[:30]:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "sent_at",
                    "client_or_lead",
                    "system",
                    "channel",
                    "status",
                    "message_body_or_summary",
                    "proof",
                )
            )
            + " |"
        )
    if len(ledger) > 30:
        lines.append(f"- Plus {len(ledger) - 30} more rows in `{relative_label(SEND_LEDGER_CSV)}`.")

    lines.extend(
        [
            "",
            "## Next Send Queue Preview",
            f"- Rows: {len(next_queue)}",
            f"- CSV: {relative_label(NEXT_SEND_QUEUE_CSV)}",
            f"- Allowed now: {queue_counts.get('yes', 0)}",
            f"- Blocked/gated now: {queue_counts.get('no', 0)}",
            f"- Owner text notice: {next_queue[0].get('owner_notice_status') if next_queue else 'not_applicable'}",
            "",
            "| Rank | Client/Lead | Channel | Subject | Owner notice | Send allowed now | Blocked reason | Message body |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in next_queue[:25]:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "queue_rank",
                    "client_or_lead",
                    "channel",
                    "subject",
                    "owner_notice_status",
                    "send_allowed_now",
                    "blocked_reason",
                    "message_body",
                )
            )
            + " |"
        )
    if not next_queue:
        lines.append("| - | None | - | - | not_applicable | no | No current expansion packet found. | - |")
    if len(next_queue) > 25:
        lines.append(f"- Plus {len(next_queue) - 25} more queued rows in `{relative_label(NEXT_SEND_QUEUE_CSV)}`.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_daily_board(report: dict[str, Any], path: Path = DAILY_BOARD_MD) -> None:
    board = report.get("daily_board", [])
    lines = [
        "# A FUND Solution Daily Board",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
    ]
    for item in board:
        lines.append(f"{item.get('label')}: {item.get('value')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_governor_safe_fixes(report: dict[str, Any], path: Path = GOVERNOR_SAFE_FIXES_MD) -> None:
    counts = Counter(str(row.get("queue_status") or "Unknown") for row in report.get("work_queue", []))
    safe_fixes = [row for row in report.get("work_queue", []) if row.get("safe_fix_applied")]
    lines = [
        "# FUNDz Governor Safe-Fix Report",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Policy",
        GOVERNOR_SAFE_FIX_POLICY,
        "",
        "## Queue Status Counts",
    ]
    for status in QUEUE_STATUSES:
        lines.append(f"- {status}: {counts.get(status, 0)}")
    lines.extend(["", "## Safe Fixes Applied"])
    if not safe_fixes:
        lines.append("- None.")
    for row in safe_fixes[:50]:
        lines.append(
            f"- {row.get('work_order_id')} | {row.get('queue_status')} | "
            f"{row.get('client_name') or row.get('lane')} | {row.get('safe_fix_applied')}"
        )
    lines.extend(["", "## Alerts"])
    alerts = report.get("governor_alerts", [])
    if not alerts:
        lines.append("- None.")
    for alert in alerts[:50]:
        label = alert.get("client_name") or alert.get("work_order_id")
        lines.append(f"- {alert.get('reason')} | {label} | {alert.get('next_step')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ").strip()


def write_communication_control_board(
    report: dict[str, Any],
    path: Path = COMMUNICATION_CONTROL_BOARD_MD,
    csv_path: Path = COMMUNICATION_CONTROL_BOARD_CSV,
) -> None:
    rows = report.get("communication_control_board") or build_communication_control_board(report)
    write_dict_csv(csv_path, rows, COMMUNICATION_CONTROL_BOARD_FIELDS)
    status_counts = Counter(str(row.get("communication_status") or "Unknown") for row in rows)
    lane_counts = Counter(str(row.get("message_lane") or "Unknown") for row in rows)
    problem_counts = Counter()
    for row in rows:
        for flag in str(row.get("billing_or_problem_flag") or "").split(";"):
            if flag:
                problem_counts[flag] += 1

    lines = [
        "# FUNDz Client Communication Control Board",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Objective: give Brandon, FUNDz, and Governor one conservative board that shows who can be prepared, who is blocked, and why before any member message goes out.",
        "",
        "## Operating Rules",
        "- Mobile App SMS is not treated as safe unless DF shows the client is Installed / Logged In.",
        "- Email is a fallback/companion route, but live sends still need the queue proof gate and Brandon's action-time approval.",
        "- Holds, failed App SMS rows, billing/problem flags, no recent contact, and missing proof stay out of normal progress or education messages.",
        "- Regular SMS remains outside this board unless Brandon separately approves it.",
        "",
        "## Status Counts",
    ]
    if not rows:
        lines.append("- No active client rows found.")
    for status, count in status_counts.most_common():
        lines.append(f"- {status}: {count}")

    lines.extend(["", "## Lane Counts"])
    for lane, count in lane_counts.most_common():
        lines.append(f"- {lane}: {count}")

    lines.extend(["", "## Top Problem Flags"])
    if not problem_counts:
        lines.append("- None.")
    for flag, count in problem_counts.most_common(10):
        lines.append(f"- {flag}: {count}")

    lines.extend(
        [
            "",
            "## Highest-Priority Rows",
            "| Status | Lane | Client | App readiness | Mobile App SMS | Email | Block reason | Next action |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows[:75]:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row.get(field))
                for field in (
                    "communication_status",
                    "message_lane",
                    "client_name",
                    "app_readiness",
                    "mobile_app_sms_allowed",
                    "email_allowed",
                    "block_reason",
                    "recommended_next_action",
                )
            )
            + " |"
        )
    if len(rows) > 75:
        lines.append(f"- Plus {len(rows) - 75} more rows in `{relative_label(csv_path)}`.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_markdown(report: dict[str, Any], path: Path = COMMAND_CENTER_MD) -> None:
    lines = [
        "# A FUND Solution Command Center",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Summary",
    ]
    summary = report.get("summary", {})
    lines.extend(
        [
            f"- Active clients: {summary.get('active_clients', 0)}",
            f"- Owner review before messaging: {summary.get('owner_review_before_message', 0)}",
            f"- No recent contact found: {summary.get('no_recent_contact_found', 0)}",
            f"- Action queue: {summary.get('action_counts', {})}",
            f"- Work Queue CSV: {relative_label(WORK_QUEUE_CSV)}",
            f"- Google Sheet import CSV: {relative_label(WORK_QUEUE_SHEET_IMPORT_CSV)}",
            f"- Today operating board: {relative_label(TODAY_OPERATING_BOARD_MD)}",
            f"- Today decision queue: {relative_label(TODAY_DECISION_QUEUE_CSV)}",
            f"- Daily board: {relative_label(DAILY_BOARD_MD)}",
            f"- Client communication control board: {relative_label(COMMUNICATION_CONTROL_BOARD_MD)}",
            f"- Send visibility board: {relative_label(SEND_VISIBILITY_MD)}",
            f"- Next send queue CSV: {relative_label(NEXT_SEND_QUEUE_CSV)}",
            f"- Send kill switch: {relative_label(SEND_KILL_SWITCH_MD)}",
            f"- Send gate lock: {relative_label(SEND_GATE_LOCK_MD)}",
            f"- Billing maintenance focus: {relative_label(BILLING_MAINTENANCE_FOCUS_MD)}",
            f"- Archive receipt trail: {relative_label(ARCHIVE_RECEIPT_TRAIL_MD)}",
            f"- Billing rollout triage: {relative_label(BILLING_ROLLOUT_TRIAGE_MD)}",
            f"- Clean backup preview candidates: {relative_label(CLEAN_BACKUP_PREVIEW_MD)}",
            f"- Governor safe-fix report: {relative_label(GOVERNOR_SAFE_FIXES_MD)}",
            "",
            "## Operating Map",
            "- A FUND Solution has one Command Center. FUNDz is a source workspace/workflow feeding local evidence, billing, archive, and message-readiness outputs.",
            f"- Open first: {relative_label(TODAY_OPERATING_BOARD_MD)} for the current lane.",
            f"- Do the work: {relative_label(WORK_QUEUE_CSV)} for owner, next step, due date, proof, and evidence.",
            f"- Billing decisions: {relative_label(BILLING_MAINTENANCE_FOCUS_MD)} and `data/local/maintenance-cleanup/fundz-lucy-billing-workqueue.md`.",
            f"- Message receipts and gates: {relative_label(SEND_VISIBILITY_MD)}. It shows what happened and what is gated; it does not approve sends.",
            f"- Preview-only messages: {relative_label(NEXT_SEND_QUEUE_CSV)}. These rows are not permission to send.",
            "",
            "## Daily Board",
        ]
    )
    for item in report.get("daily_board", []):
        lines.append(f"- {item.get('label')}: {item.get('value')}")
    safety = report.get("safety_gate") if isinstance(report.get("safety_gate"), dict) else {}
    lines.extend(
        [
            "",
            "## Safety Gate Tile",
            f"- State: {safety.get('state', 'Local reporting only')}",
            f"- Last check: {safety.get('generated_at', 'not recorded')}",
            f"- Steps: {safety.get('successful_steps', 0)}/{safety.get('total_steps', 0)}; maintenance: {safety.get('maintenance_steps', '0/0')}",
            f"- Approval required: {safety.get('approval_required', True)}",
            f"- Live send allowed: {safety.get('live_send_allowed', False)}",
            f"- Rollout selected: {safety.get('rollout_selected', 0)}",
            f"- Runtime quiet: {safety.get('runtime_quiet', False)}",
            f"- Allowed reporting runtime: {safety.get('allowed_reporting_runtime', False)}",
            f"- Unexpected runtime processes: {len(safety.get('unexpected_runtime_processes', [])) if isinstance(safety.get('unexpected_runtime_processes'), list) else 0}",
            f"- Meaning: {safety.get('note', 'Client sends remain off; use this as local reporting only.')}",
        ]
    )
    kill_switch = report.get("send_kill_switch") if isinstance(report.get("send_kill_switch"), dict) else {}
    next_queue = report.get("next_send_queue", [])
    lines.extend(
        [
            "",
            "## Send Visibility",
            f"- Kill switch: {kill_switch.get('status', 'unknown')}",
            f"- Sent ledger rows: {len(report.get('send_ledger', []))}",
            f"- Next send queue rows: {len(next_queue)}",
            f"- Next-send allowed now: {sum(1 for row in next_queue if row.get('send_allowed_now') == 'yes')}",
            f"- Next-send gated now: {sum(1 for row in next_queue if row.get('send_allowed_now') != 'yes')}",
            f"- Owner text notice: {next_queue[0].get('owner_notice_status') if next_queue else 'not_applicable'}",
            f"- Owner view: {relative_label(SEND_VISIBILITY_MD)}",
            f"- Gate lock: {relative_label(SEND_GATE_LOCK_MD)}",
        ]
    )
    maintenance = report.get("maintenance_cleanup_summary") if isinstance(report.get("maintenance_cleanup_summary"), dict) else {}
    billing_decisions = maintenance.get("billing_decisions") if isinstance(maintenance.get("billing_decisions"), dict) else {}
    archive_trail = report.get("archive_receipt_trail") if isinstance(report.get("archive_receipt_trail"), dict) else {}
    lines.extend(
        [
            "",
            "## Billing Maintenance",
            f"- Urgent billing review: {billing_decisions.get('active_urgent_billing_review', 0)}",
            f"- Date-sensitive billing reviews: {billing_decisions.get('active_date_sensitive_billing_review', 0)}",
            f"- Standard billing reviews: {billing_decisions.get('active_standard_billing_review', 0)}",
            f"- Missing billing dates: {billing_decisions.get('fix_missing_billing_date', 0)}",
            f"- Duplicate-review clients: {maintenance.get('duplicate_review_clients', billing_decisions.get('duplicate_review_once', 0))}",
            f"- Owner-updated billing clients moved out: {maintenance.get('owner_updated_billing_clients', 0)}",
            f"- Focus board: {relative_label(BILLING_MAINTENANCE_FOCUS_MD)}",
            "",
            "## Archive Receipt Trail",
            f"- Live DF archive confirmations recorded: {archive_trail.get('live_confirmed', 0)}",
            f"- Owner exceptions recorded: {archive_trail.get('exceptions', 0)}",
            f"- Active bucket remaining: {archive_trail.get('bulk_targets_in_active_bucket', 0)}",
            f"- Audit board: {relative_label(ARCHIVE_RECEIPT_TRAIL_MD)}",
        ]
    )
    queue_counts = Counter(str(row.get("queue_status") or "Unknown") for row in report.get("work_queue", []))
    lines.extend(
        [
            "",
            "## Work Queue Status",
        ]
    )
    for status in QUEUE_STATUSES:
        lines.append(f"- {status}: {queue_counts.get(status, 0)}")
    approved_count = queue_counts.get("Approved", 0)
    done_count = queue_counts.get("Done", 0)
    sent_count = queue_counts.get("Sent", 0)
    needs_brandon_count = queue_counts.get("Needs Brandon", 0)
    blocked_count = queue_counts.get("Blocked", 0)
    failed_count = queue_counts.get("Failed", 0)
    proof_needed_count = queue_counts.get("Proof Needed", 0)
    lines.extend(
        [
            "",
            "## Queue Truth",
            f"- Done/Sent: {done_count + sent_count} receipt-backed outcome(s).",
            f"- Approved: {approved_count} prepared-but-gated row(s); these are not complete until proof or an action receipt exists.",
            f"- Needs Brandon: {needs_brandon_count} decision/hold row(s); do not send or mark done from these rows.",
            f"- Blocked/Failed/Proof Needed: {blocked_count + failed_count + proof_needed_count} row(s) requiring blocker or proof cleanup before closeout.",
        ]
    )
    control_counts = Counter(str(row.get("communication_status") or "Unknown") for row in report.get("communication_control_board", []))
    lines.extend(["", "## Client Communication Control Board"])
    if control_counts:
        for status, count in control_counts.most_common():
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- No control-board rows available.")
    lines.extend(
        [
            "",
            "## Governor Alerts",
        ]
    )
    alerts = report.get("governor_alerts", [])
    if not alerts:
        lines.append("- None.")
    for alert in alerts[:10]:
        lines.append(f"- {alert.get('reason')} | {alert.get('client_name') or alert.get('work_order_id')} | {alert.get('next_step')}")
    lines.extend(
        [
            "",
            "## Blockers",
        ]
    )
    for blocker in report.get("blockers", []):
        lines.append(f"- {blocker}")

    coverage = report.get("communication_coverage", {})
    lines.extend(
        [
            "",
            "## Communication Coverage",
            f"- Active clients in ledger: {coverage.get('active_clients', 0)}",
            f"- With email: {coverage.get('with_email', 0)}",
            f"- With phone/SMS history: {coverage.get('with_phone_history', 0)}",
            f"- Ledger CSV: {relative_label(CONTACT_LEDGER_CSV)}",
            "",
            "## Today's Top Actions",
        ]
    )
    for row in report.get("top_actions", [])[:10]:
        lines.append(
            f"- {row.get('priority_score')} | {row.get('client_name')} | "
            f"{row.get('next_touch_status')} | {row.get('recommended_next_action')}"
        )

    lines.extend(["", "## Next Safe Batch Candidates"])
    for action in report.get("next_safe_batch_candidates", []):
        lines.append(f"- {action.get('client_name')} | {action.get('reason')}")
    if not report.get("next_safe_batch_candidates"):
        lines.append("- None ready from the current action queue.")

    audit = report.get("autofox_audit", {})
    scorefusion = report.get("scorefusion", {})
    pilot = report.get("pilot_status", {}).get("summary", {})
    lines.extend(
        [
            "",
            "## AutoFox Snapshot",
            f"- Outbound records: {audit.get('records', 0)}",
            f"- Failures: {audit.get('failures', 0)}",
            f"- Possible duplicates: {audit.get('duplicates', 0)}",
            f"- After-hours records: {audit.get('after_hours', 0)}",
            "",
            "## ScoreFusion Billing Snapshot",
            f"- Enrolled: {scorefusion.get('enrolled', 0)}",
            f"- Owed payments: {scorefusion.get('owed_payments', 0)}",
            f"- Total amount due: {scorefusion.get('total_amount_due', '0.00')}",
            f"- Failed / at risk: {scorefusion.get('failed_at_risk', 0)}",
            f"- Exceptions: {scorefusion.get('exceptions', 0)}",
            f"- Billing risk review rows: {scorefusion.get('billing_risk_review_rows', 0)}",
            f"- Billing risk unique keys: {scorefusion.get('billing_risk_unique_keys', 0)}",
            f"- Billing risk duplicate keys: {scorefusion.get('billing_risk_duplicate_keys', 0)}",
            f"- Billing risk rows in duplicate keys: {scorefusion.get('billing_risk_rows_in_duplicate_keys', 0)}",
            "",
            "## Pilot Status",
            f"- Pilot clients: {pilot.get('clients', 0)}",
            f"- App/SMS provider receipts: {pilot.get('app_or_sms_sent', 0)}",
            f"- Email receipts: {pilot.get('email_sent', 0)}",
            f"- App visibility confirmed: {pilot.get('app_visibility_confirmed', 0)}",
            f"- Replies seen: {pilot.get('replied', 0)}",
            f"- Unresolved clients: {pilot.get('unresolved', 0)}",
            "",
            "## Receipts",
        ]
    )
    for receipt in report.get("receipts", {}).get("recent_receipts", []):
        lines.append(f"- {receipt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pilot_report(report: dict[str, Any], path: Path = PILOT_REPORT_MD) -> None:
    pilot = report.get("pilot_status", {})
    summary = pilot.get("summary", {})
    lines = [
        "# FUNDz Pilot Status",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Summary",
        f"- Pilot clients: {summary.get('clients', 0)}",
        f"- App/SMS provider receipts: {summary.get('app_or_sms_sent', 0)}",
        f"- Email receipts: {summary.get('email_sent', 0)}",
        f"- App visibility confirmed: {summary.get('app_visibility_confirmed', 0)}",
        f"- Replies seen: {summary.get('replied', 0)}",
        f"- Unresolved clients: {summary.get('unresolved', 0)}",
        "",
        "## Clients",
    ]
    for client in pilot.get("pilot_clients", []):
        unresolved = client.get("unresolved") or ["none"]
        lines.extend(
            [
                f"- {client.get('client_name')}: app/SMS receipt={client.get('app_or_sms_sent')}, "
                f"email receipt={client.get('email_sent')}, app visible={client.get('app_visibility_confirmed')}, "
                f"reply seen={client.get('reply_seen')}, unresolved={'; '.join(unresolved)}",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_weekly_summary(report: dict[str, Any], path: Path = WEEKLY_SUMMARY_MD) -> None:
    summary = report.get("summary", {})
    coverage = report.get("communication_coverage", {})
    audit = report.get("autofox_audit", {})
    changed = report.get("what_changed_since_last_run", {})
    queue_counts = Counter(str(row.get("queue_status") or "Unknown") for row in report.get("work_queue", []))
    lines = [
        "# FUNDz Weekly Owner Summary",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Executive Readout",
        f"- Active clients: {summary.get('active_clients', 0)}",
        f"- Owner-review before messaging: {summary.get('owner_review_before_message', 0)}",
        f"- No recent contact found: {summary.get('no_recent_contact_found', 0)}",
        f"- With email: {coverage.get('with_email', 0)}",
        f"- With phone/SMS history: {coverage.get('with_phone_history', 0)}",
        f"- AutoFox failures / duplicates / after-hours: {audit.get('failures', 0)} / {audit.get('duplicates', 0)} / {audit.get('after_hours', 0)}",
        f"- Queue sent / failed / blocked / needs Brandon / proof missing: "
        f"{queue_counts.get('Sent', 0)} / {queue_counts.get('Failed', 0)} / {queue_counts.get('Blocked', 0)} / "
        f"{queue_counts.get('Needs Brandon', 0)} / {queue_counts.get('Proof Needed', 0)}",
        "",
        "## What Changed Since Last Run",
        f"- {changed.get('summary_deltas', {}) if changed.get('available') else changed.get('note', 'No prior report.')}",
        "",
        "## Top Work",
    ]
    for row in report.get("top_actions", [])[:10]:
        lines.append(f"- {row.get('client_name')}: {row.get('next_touch_status')} - {row.get('recommended_next_action')}")
    lines.extend(["", "## Blockers"])
    for blocker in report.get("blockers", []):
        lines.append(f"- {blocker}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_release_checklist(report: dict[str, Any], path: Path = RELEASE_CHECKLIST_MD) -> None:
    lines = [
        "# FUNDz Pre-Send Release Checklist",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "Use before any live broad outreach. Items marked `blocked` must be resolved or explicitly approved before sending.",
        "",
        "## Checks",
    ]
    for item in report.get("release_checklist", []):
        lines.append(f"- {item.get('status')}: {item.get('check')} - {item.get('note')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_no_recent_contact_investigation(
    report: dict[str, Any],
    path: Path = NO_RECENT_CONTACT_INVESTIGATION_MD,
    csv_path: Path = NO_RECENT_CONTACT_INVESTIGATION_CSV,
) -> None:
    rows = report.get("no_recent_contact_investigations", [])
    write_dict_csv(csv_path, rows, NO_RECENT_CONTACT_INVESTIGATION_FIELDS)
    lines = [
        "# FUNDz No-Recent-Contact Investigation",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "This separates real delivered-message proof from weaker evidence such as dry runs or sequence assignment receipts.",
        "",
        "## Summary",
        f"- Rows reviewed: {len(rows)}",
        f"- Owner review required: {sum(1 for row in rows if row.get('status') == 'owner_review_required')}",
        f"- Delivered-message proof found: {sum(1 for row in rows if row.get('delivered_message_proof') == 'yes')}",
        "",
        "## Rows",
    ]
    if not rows:
        lines.append("- No no-recent-contact rows.")
    for row in rows:
        lines.extend(
            [
                f"### {row.get('client_name')}",
                f"- Status: {row.get('status')}",
                f"- Delivered-message proof: {row.get('delivered_message_proof')}",
                f"- Sequence assignment: {row.get('sequence_assignment') or 'none'}",
                f"- Dry run found: {row.get('dry_run_found')}",
                f"- Recommended resolution: {row.get('recommended_resolution')}",
                f"- Evidence: {row.get('evidence_summary')}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_business_review_controlled_rollout(report: dict[str, Any], path: Path = BUSINESS_REVIEW_ROLLOUT_MD) -> None:
    scorefusion = report.get("scorefusion", {})
    release_items = report.get("release_checklist", [])
    release_status = {item.get("check"): item.get("status") for item in release_items}
    blocked_checks = [item for item in release_items if item.get("status") == "blocked"]
    review_checks = [item for item in release_items if item.get("status") == "review"]
    bucket_summary = scorefusion.get("billing_review_bucket_summary", {})
    next_work = report.get("no_approval_work_queue", [])
    pilot = report.get("pilot_status", {}).get("summary", {})
    autofox = report.get("autofox_audit", {})
    preview_decision = report.get("preview_packet_decision", {})
    triage_counts = Counter(str(row.get("rollout_decision") or "unknown") for row in report.get("billing_rollout_triage", []))
    clean_pool_counts = Counter(str(row.get("candidate_use") or "unknown") for row in report.get("clean_backup_preview_pool", []))
    preview_packet = ROOT / "data" / "local" / "semi-autonomous" / "expansion-batch-packet.json"
    preview_report = ROOT / "data" / "local" / "semi-autonomous" / "expansion-batch-preview.md"
    preview_data = read_json(preview_packet)
    preview_items = preview_data.get("items", []) if isinstance(preview_data, dict) else []
    preview_ready = sum(1 for item in preview_items if item.get("send_ready"))

    lines = [
        "# FUNDz Business Review + Controlled Rollout",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "## Decision",
        "- Proceed with business review and preview-only rollout prep.",
        "- Do not run broad live outreach, billing-warning automation changes, or campaign assignment from this review.",
        "- Live rollout remains blocked until there is one named client/key, exact channel, exact message or campaign, and action-time approval.",
        "",
        "## Business Review",
        f"- ScoreFusion enrolled: {scorefusion.get('enrolled', 0)}",
        f"- Owed payments: {scorefusion.get('owed_payments', 0)}",
        f"- Total amount due: {scorefusion.get('total_amount_due', '0.00')}",
        f"- Unique billing-risk review keys: {scorefusion.get('billing_risk_unique_keys', 0)}",
        f"- Duplicate billing-risk keys: {scorefusion.get('billing_risk_duplicate_keys', 0)}",
        f"- Rows inside duplicate keys: {scorefusion.get('billing_risk_rows_in_duplicate_keys', 0)}",
        "",
        "## Billing Review Buckets",
    ]
    if bucket_summary:
        for bucket, count in bucket_summary.items():
            lines.append(f"- {bucket}: {count}")
    else:
        lines.append("- No bucket summary available.")

    lines.extend(
        [
            "",
            "## Controlled Rollout State",
            f"- Human approval captured: {release_status.get('Human approval captured', 'unknown')}",
            f"- Dry-run guard: {release_status.get('Dry run disabled only for approved command', 'unknown')}",
            f"- App visibility: {release_status.get('App visibility confirmed', 'unknown')}",
            f"- Owner-review queue gate: {release_status.get('Owner-review queue clear enough', 'unknown')}",
            f"- AutoFox failures reviewed: {release_status.get('AutoFox failures reviewed', 'unknown')}",
            f"- Pilot clients tracked: {pilot.get('clients', 0)}",
            f"- App visibility confirmations: {pilot.get('app_visibility_confirmed', 0)}",
            f"- AutoFox failures / duplicates / after-hours: {autofox.get('failures', 0)} / {autofox.get('duplicates', 0)} / {autofox.get('after_hours', 0)}",
            f"- Latest preview decision: {preview_decision.get('decision', 'not reviewed')}",
            f"- Billing rollout triage: {sum(triage_counts.values())} rows; hold {triage_counts.get('hold', 0)}, owner override {triage_counts.get('owner_override_needed', 0)}, exclude {triage_counts.get('exclude_from_rollout', 0)}",
            f"- Clean preview pool: {sum(clean_pool_counts.values())} candidates; active approved {clean_pool_counts.get('active_approved_preview', 0)}, backups {clean_pool_counts.get('backup_preview_candidate', 0)}",
            "",
            "## What Is Allowed Now",
            "- Review deduped billing-risk rows once per unique key.",
            "- Produce or refresh a preview-only tiny pilot packet.",
            "- Confirm app visibility and AutoFox proof without assigning broad campaigns.",
            "",
            "## What Is Not Allowed Yet",
            "- Live sends.",
            "- Broad campaign assignment.",
            "- Billing-warning workflow changes.",
            "- Double-contacting duplicate billing failure rows.",
            "",
            "## Current Gates",
        ]
    )
    if blocked_checks:
        for item in blocked_checks:
            lines.append(f"- blocked: {item.get('check')} - {item.get('note')}")
    if review_checks:
        for item in review_checks:
            lines.append(f"- review: {item.get('check')} - {item.get('note')}")
    if not blocked_checks and not review_checks:
        lines.append("- No blocked/review gates recorded.")

    lines.extend(
        [
            "",
            "## Next Actions",
        ]
    )
    for row in next_work[:5]:
        lines.append(f"- {row.get('priority')}. {row.get('work_item')}: {row.get('output')}")
    if not next_work:
        lines.append("- Refresh command center and review the top work queue row.")

    lines.extend(
        [
            "",
            "## Preview Packet",
            f"- Packet: {relative_label(preview_packet)}",
            f"- Report: {relative_label(preview_report)}",
            f"- Latest batch ID: {preview_data.get('batch_id', 'none') if isinstance(preview_data, dict) else 'none'}",
            f"- Mode: {preview_data.get('mode', 'none') if isinstance(preview_data, dict) else 'none'}",
            f"- Selected / ready: {len(preview_items)} / {preview_ready}",
            f"- Live send allowed: {preview_data.get('live_send_allowed', False) if isinstance(preview_data, dict) else False}",
            f"- Result sent / failed / skipped: {preview_decision.get('result_sent', 0)} / {preview_decision.get('result_blocked_or_failed', 0)} / {preview_decision.get('result_skipped', 0)}",
            f"- Status: {preview_decision.get('reason', 'preview artifact only; it does not approve or send messages.')}",
            "",
            "## Operating Rule",
            "- When billing risk is nonzero, review the deduped billing-risk packet before changing any billing-warning workflow.",
            "- When rollout is requested, generate preview first, then require named approval before any live action.",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_preview_packet_decision(report: dict[str, Any], path: Path = PREVIEW_PACKET_DECISION_MD) -> None:
    decision = report.get("preview_packet_decision", {})
    is_capped_ready = decision.get("batch_preset") == "capped_ready_rollout"
    lines = [
        "# FUNDz Preview Packet Decision",
        "",
        f"Generated: {decision.get('generated_at') or report.get('generated_at', '')}",
        "",
        "## Decision",
        f"- Decision: {decision.get('decision', 'hold')}",
        f"- Reason: {decision.get('reason', 'No decision reason recorded.')}",
        f"- Next step: {decision.get('next_step', 'Hold until reviewed.')}",
        "",
        "## Exact Preview Scope",
        f"- Batch ID: {decision.get('batch_id', '')}",
        f"- Mode: {decision.get('mode', '')}",
        f"- Channel: {decision.get('channel', '')}",
        f"- Batch preset: {decision.get('batch_preset', '')}",
        f"- Ready-only: {decision.get('ready_only', False)}",
        f"- Selected: {decision.get('selected', 0)}",
        f"- Send-ready: {decision.get('send_ready_count', 0)}",
        f"- Skipped before packet: {decision.get('skipped_candidates', 0)}",
        f"- Max batch size: {decision.get('max_batch_size', 0)}",
        f"- Live send allowed: {decision.get('live_send_allowed', False)}",
    ]
    if not is_capped_ready:
        lines.extend(
            [
                f"- Client: {decision.get('client_name', '')}",
                f"- Client key: {decision.get('client_key', '')}",
                f"- Status: {decision.get('status', '')}",
                f"- Stage: {decision.get('stage', '')}",
            ]
        )
    preview_clients = decision.get("preview_clients", [])
    if is_capped_ready and isinstance(preview_clients, list) and preview_clients:
        lines.extend(["", "## Preview Clients"])
        for preview_item in preview_clients:
            if not isinstance(preview_item, dict):
                continue
            lines.append(
                f"- {preview_item.get('client_name', '')} | "
                f"{preview_item.get('status', '')} | "
                f"{preview_item.get('stage', '')} | "
                f"send-ready={preview_item.get('send_ready', False)}"
            )
    lines.extend(["", "## Review Findings"])
    reasons = decision.get("reasons", [])
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- No blocking findings.")
    billing_matches = decision.get("billing_review_matches", [])
    if billing_matches:
        lines.extend(["", "## Billing Matches"])
        for match in billing_matches:
            if not isinstance(match, dict):
                continue
            lines.append(
                f"- {match.get('client_name', '')} | "
                f"{match.get('review_bucket', '')} | "
                f"{match.get('next_charge_date', '')}"
            )
    if decision.get("billing_review_bucket"):
        lines.extend(
            [
                "",
                "## Billing Gate",
                f"- Bucket: {decision.get('billing_review_bucket', '')}",
                f"- Next charge date: {decision.get('billing_next_charge_date', '')}",
                f"- Treatment: {decision.get('billing_rollout_treatment', '')}",
            ]
        )
    if decision.get("batch_result"):
        lines.extend(
            [
                "",
                "## Batch Result",
                f"- Result file: {decision.get('batch_result', '')}",
                f"- Receipt: {decision.get('batch_receipt', '')}",
                f"- Sent: {decision.get('result_sent', 0)}",
                f"- Failed/blocked: {decision.get('result_blocked_or_failed', 0)}",
                f"- Skipped: {decision.get('result_skipped', 0)}",
                f"- Approved live send: {decision.get('approved_batch_send', False)}",
            ]
        )
    notes = decision.get("notes", [])
    if notes:
        lines.extend(["", "## Notes"])
        for note in notes:
            lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## Rule",
            "- This decision applies only to this capped preview packet and listed ready items."
            if is_capped_ready
            else "- This decision applies only to this preview packet and one exact item.",
            "- A held preview does not authorize live send, broad rollout, or replacement sends.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_command_center(report: dict[str, Any]) -> dict[str, str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COMMAND_CENTER_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_contact_ledger(report.get("ledger", []), CONTACT_LEDGER_CSV)
    write_work_queue_outputs(report)
    write_daily_board(report, DAILY_BOARD_MD)
    write_today_operating_board(report, TODAY_OPERATING_BOARD_MD)
    write_governor_safe_fixes(report, GOVERNOR_SAFE_FIXES_MD)
    write_communication_control_board(report, COMMUNICATION_CONTROL_BOARD_MD, COMMUNICATION_CONTROL_BOARD_CSV)
    write_send_kill_switch_status(report, SEND_KILL_SWITCH_MD)
    write_send_visibility(report, SEND_VISIBILITY_MD)
    write_dict_csv(SEND_LEDGER_CSV, report.get("send_ledger", []), SEND_LEDGER_FIELDS)
    write_dict_csv(NEXT_SEND_QUEUE_CSV, report.get("next_send_queue", []), NEXT_SEND_QUEUE_FIELDS)
    write_billing_maintenance_focus(report, BILLING_MAINTENANCE_FOCUS_MD, BILLING_MAINTENANCE_FOCUS_CSV)
    write_archive_receipt_trail(report, ARCHIVE_RECEIPT_TRAIL_MD)
    write_send_gate_lock(report, SEND_GATE_LOCK_MD)
    write_markdown(report, COMMAND_CENTER_MD)
    write_pilot_report(report, PILOT_REPORT_MD)
    write_weekly_summary(report, WEEKLY_SUMMARY_MD)
    write_release_checklist(report, RELEASE_CHECKLIST_MD)
    write_drilldown_csvs(report)
    write_autofox_migration_checklist(report, AUTOFOX_MIGRATION_MD)
    write_member_experience_system(report, MEMBER_EXPERIENCE_MD, MEMBER_EXPERIENCE_TIPS_CSV)
    write_owner_review_action_catalog(report, OWNER_REVIEW_ACTIONS_MD, OWNER_REVIEW_ACTIONS_CSV)
    write_owner_review_packet(report, OWNER_REVIEW_PACKET_MD)
    write_owner_decision_outputs(report)
    write_no_recent_contact_investigation(report, NO_RECENT_CONTACT_INVESTIGATION_MD, NO_RECENT_CONTACT_INVESTIGATION_CSV)
    write_gap_closure_plan(report, GAP_CLOSURE_MD)
    write_missing_steps_recheck(report, MISSING_STEPS_RECHECK_MD)
    write_billing_rollout_triage(report, BILLING_ROLLOUT_TRIAGE_MD, BILLING_ROLLOUT_TRIAGE_CSV)
    write_clean_backup_preview_pool(report, CLEAN_BACKUP_PREVIEW_MD, CLEAN_BACKUP_PREVIEW_CSV)
    write_business_review_controlled_rollout(report, BUSINESS_REVIEW_ROLLOUT_MD)
    write_preview_packet_decision(report, PREVIEW_PACKET_DECISION_MD)
    write_dict_csv(NO_APPROVAL_WORK_CSV, report.get("no_approval_work_queue", []), ["priority", "work_item", "input", "output"])
    state = build_operational_state()
    write_json(STATE_JSON, state)
    write_summary_csv(SUMMARY_CSV, state.get("clients", []))
    return {
        "json": relative_label(COMMAND_CENTER_JSON),
        "markdown": relative_label(COMMAND_CENTER_MD),
        "today_operating_board": relative_label(TODAY_OPERATING_BOARD_MD),
        "today_decision_queue": relative_label(TODAY_DECISION_QUEUE_CSV),
        "daily_board": relative_label(DAILY_BOARD_MD),
        "work_queue": relative_label(WORK_QUEUE_CSV),
        "work_queue_sheet_import": relative_label(WORK_QUEUE_SHEET_IMPORT_CSV),
        "governor_safe_fixes": relative_label(GOVERNOR_SAFE_FIXES_MD),
        "governor_alerts": relative_label(GOVERNOR_ALERTS_CSV),
        "communication_control_board": relative_label(COMMUNICATION_CONTROL_BOARD_MD),
        "communication_control_board_csv": relative_label(COMMUNICATION_CONTROL_BOARD_CSV),
        "send_visibility": relative_label(SEND_VISIBILITY_MD),
        "send_ledger_csv": relative_label(SEND_LEDGER_CSV),
        "next_send_queue_csv": relative_label(NEXT_SEND_QUEUE_CSV),
        "send_kill_switch": relative_label(SEND_KILL_SWITCH_MD),
        "ledger": relative_label(CONTACT_LEDGER_CSV),
        "pilot": relative_label(PILOT_REPORT_MD),
        "weekly": relative_label(WEEKLY_SUMMARY_MD),
        "release_checklist": relative_label(RELEASE_CHECKLIST_MD),
        "owner_review": relative_label(OWNER_REVIEW_CSV),
        "no_recent_contact": relative_label(NO_RECENT_CONTACT_CSV),
        "safe_batch": relative_label(SAFE_BATCH_CSV),
        "autofox_migration": relative_label(AUTOFOX_MIGRATION_MD),
        "member_experience": relative_label(MEMBER_EXPERIENCE_MD),
        "member_experience_tips": relative_label(MEMBER_EXPERIENCE_TIPS_CSV),
        "owner_review_actions": relative_label(OWNER_REVIEW_ACTIONS_MD),
        "owner_review_actions_csv": relative_label(OWNER_REVIEW_ACTIONS_CSV),
        "owner_review_packet": relative_label(OWNER_REVIEW_PACKET_MD),
        "owner_decision_queue": relative_label(OWNER_DECISION_QUEUE_CSV),
        "owner_decision_packet": relative_label(OWNER_DECISION_PACKET_MD),
        "no_recent_contact_investigation": relative_label(NO_RECENT_CONTACT_INVESTIGATION_MD),
        "no_recent_contact_investigation_csv": relative_label(NO_RECENT_CONTACT_INVESTIGATION_CSV),
        "gap_closure": relative_label(GAP_CLOSURE_MD),
        "missing_steps_recheck": relative_label(MISSING_STEPS_RECHECK_MD),
        "billing_rollout_triage": relative_label(BILLING_ROLLOUT_TRIAGE_MD),
        "billing_rollout_triage_csv": relative_label(BILLING_ROLLOUT_TRIAGE_CSV),
        "billing_maintenance_focus": relative_label(BILLING_MAINTENANCE_FOCUS_MD),
        "billing_maintenance_focus_csv": relative_label(BILLING_MAINTENANCE_FOCUS_CSV),
        "archive_receipt_trail": relative_label(ARCHIVE_RECEIPT_TRAIL_MD),
        "send_gate_lock": relative_label(SEND_GATE_LOCK_MD),
        "clean_backup_preview": relative_label(CLEAN_BACKUP_PREVIEW_MD),
        "clean_backup_preview_csv": relative_label(CLEAN_BACKUP_PREVIEW_CSV),
        "business_review_rollout": relative_label(BUSINESS_REVIEW_ROLLOUT_MD),
        "preview_packet_decision": relative_label(PREVIEW_PACKET_DECISION_MD),
        "no_approval_work": relative_label(NO_APPROVAL_WORK_CSV),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="Number of top actions to show.")
    parser.add_argument("--json", action="store_true", help="Print full report JSON instead of a short summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_command_center(limit=args.limit)
    paths = write_command_center(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print("A FUND Solution Command Center built from the FUNDz workspace.")
    print(f"- Markdown: {paths['markdown']}")
    print(f"- JSON: {paths['json']}")
    print(f"- Today operating board: {paths['today_operating_board']}")
    print(f"- Today decision queue: {paths['today_decision_queue']}")
    print(f"- Daily board: {paths['daily_board']}")
    print(f"- Work queue: {paths['work_queue']}")
    print(f"- Google Sheet import: {paths['work_queue_sheet_import']}")
    print(f"- Governor safe-fix report: {paths['governor_safe_fixes']}")
    print(f"- Governor alerts: {paths['governor_alerts']}")
    print(f"- Communication control board: {paths['communication_control_board']}")
    print(f"- Communication control board CSV: {paths['communication_control_board_csv']}")
    print(f"- Send visibility board: {paths['send_visibility']}")
    print(f"- Send ledger CSV: {paths['send_ledger_csv']}")
    print(f"- Next send queue CSV: {paths['next_send_queue_csv']}")
    print(f"- Send kill switch: {paths['send_kill_switch']}")
    print(f"- Contact ledger: {paths['ledger']}")
    print(f"- Pilot status: {paths['pilot']}")
    print(f"- Weekly summary: {paths['weekly']}")
    print(f"- Release checklist: {paths['release_checklist']}")
    print(f"- Owner-review queue: {paths['owner_review']}")
    print(f"- No-recent-contact exceptions: {paths['no_recent_contact']}")
    print(f"- Safe batch candidates: {paths['safe_batch']}")
    print(f"- AutoFox migration checklist: {paths['autofox_migration']}")
    print(f"- Member experience system: {paths['member_experience']}")
    print(f"- Credit tip CSV: {paths['member_experience_tips']}")
    print(f"- Owner-review actions: {paths['owner_review_actions']}")
    print(f"- Owner-review actions CSV: {paths['owner_review_actions_csv']}")
    print(f"- Owner-review packet: {paths['owner_review_packet']}")
    print(f"- Owner decision queue: {paths['owner_decision_queue']}")
    print(f"- Owner decision packet: {paths['owner_decision_packet']}")
    print(f"- No-recent-contact investigation: {paths['no_recent_contact_investigation']}")
    print(f"- No-recent-contact investigation CSV: {paths['no_recent_contact_investigation_csv']}")
    print(f"- Gap closure plan: {paths['gap_closure']}")
    print(f"- Missing steps recheck: {paths['missing_steps_recheck']}")
    print(f"- Billing rollout triage: {paths['billing_rollout_triage']}")
    print(f"- Billing rollout triage CSV: {paths['billing_rollout_triage_csv']}")
    print(f"- Billing maintenance focus: {paths['billing_maintenance_focus']}")
    print(f"- Billing maintenance focus CSV: {paths['billing_maintenance_focus_csv']}")
    print(f"- Archive receipt trail: {paths['archive_receipt_trail']}")
    print(f"- Send gate lock: {paths['send_gate_lock']}")
    print(f"- Clean backup preview candidates: {paths['clean_backup_preview']}")
    print(f"- Clean backup preview candidates CSV: {paths['clean_backup_preview_csv']}")
    print(f"- Business review + controlled rollout: {paths['business_review_rollout']}")
    print(f"- Preview packet decision: {paths['preview_packet_decision']}")
    print(f"- No-approval work queue: {paths['no_approval_work']}")
    print(f"- Top actions: {len(report.get('top_actions', []))}")


if __name__ == "__main__":
    main()
