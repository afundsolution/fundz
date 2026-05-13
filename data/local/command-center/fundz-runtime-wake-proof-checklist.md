# FUNDz Runtime Wake Proof Checklist

Generated: 2026-05-13 10:28:34 CDT
Status: BLOCKED_REVIEW_RUNTIME

This is a no-wake proof surface. It does not start the bridge, tunnel, poller, webhook, or any send path.

## Current Runtime
- Active screens: fundz-command-center
- Live bridge/tunnel/poller screens: none
- Allowed reporting screens: fundz-command-center
- Live process markers: 0

## Gate State
- Kill switch: off_approval_gates_still_required
- `CREDIT_TRACKER_DRY_RUN`: False
- `FUNDZ_HIGHLEVEL_POLLER_LIVE`: False
- `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED`: False
- `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED`: False

## Blockers
- CREDIT_TRACKER_DRY_RUN is false outside this no-wake checklist run.

## Warnings
- Command-center kill switch is off. That is only acceptable inside an approved action window.

## Proof Files
- app_portal_proof: `data/local/highlevel-inbox-poller/app-portal-event-proof.jsonl` (exists, 1657 bytes)
- reply_receipts: `data/local/highlevel-inbox-poller/reply-receipts.jsonl` (exists, 983 bytes)
- bridge_log: `logs/credit-tracker-bridge.jsonl` (exists, 243229 bytes)

## Approval Packet Required
- Named client and exact inbound app/portal source.
- Exact reply copy or exact approved reply category.
- Exact action window and route: HighLevel poller or Credit Tracker webhook.
- Cap of one reply unless Brandon approves a different cap in writing.
- Receipt owner and rollback owner named before wake.

## Pre-Wake Local Steps
- Run `make inactive` if any live bridge/tunnel/poller runtime is awake.
- Run `make runtime-wake-checklist` and confirm status is READY_FOR_APPROVED_WAKE_PROOF or READY_FOR_APPROVED_WAKE_PROOF_REPORTING_AWAKE.
- Confirm app/portal inbound proof exists or is the exact inbound being tested.
- Confirm the command-center kill switch is on while waiting, then turn it off only for the approved action window.

## Wake Proof Steps After Brandon Approval
- Wake only the approved route: `scripts/fundz_highlevel_poller_start.sh` for poller or bridge plus `scripts/fundz_named_tunnel_setup.sh` for webhook.
- Verify local bridge health if webhook route is used: `curl -fsS http://127.0.0.1:8787/health`.
- Verify public webhook health if tunnel route is used: `curl -fsS https://fundz.afundsolution.com/health`.
- Run `make webhook-probe` only for webhook route; it is test-only and must not send.
- Run HighLevel preview before live poller reply: `CREDIT_TRACKER_DRY_RUN=true FUNDZ_HIGHLEVEL_POLLER_LIVE=false scripts/fundz_highlevel_inbox_poller.py --once --limit 5`.
- Confirm exactly one approval flag is true for the approved route and `CREDIT_TRACKER_DRY_RUN=false` only inside the window.
- After the approved reply, confirm receipt in `data/local/highlevel-inbox-poller/reply-receipts.jsonl` or `logs/credit-tracker-bridge.jsonl`.
- Run `make inactive`, restore dry-run, restore approval flags to false, and regenerate `make runtime-wake-checklist` plus `make command-center`.

## This Checklist Does Not Authorize
- No live reply.
- No client/lead send.
- No webhook wiring.
- No HighLevel, billing, DF, AutoFox, campaign, or archive edit.
