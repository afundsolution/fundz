# FUNDz Controlled Live Reply Gate Closeout

Date: 2026-05-13
Scope: HighLevel inbox customer-service replies

## Result

The broad autonomous customer-service reply path remains blocked by design.

The controlled live reply path is now code-ready for one approved, non-sensitive app/portal reply at a time.

## Required Gates

- `CREDIT_TRACKER_DRY_RUN=false`
- `FUNDZ_HIGHLEVEL_POLLER_LIVE=true`
- `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED=true`
- Command Center kill switch off
- Business-hours window, unless `FUNDZ_ALLOW_AFTER_HOURS_SENDS=true` is set for an approved exception
- Inbound app/portal proof signal from message type, channel, source, or equivalent app/portal evidence
- No sensitive/proof-dependent labels: billing, cancellation, complaint, document request, app access, score concern, or dispute update
- Reply receipt logging to `data/local/highlevel-inbox-poller/reply-receipts.jsonl`

## What Changed

- `scripts/fundz_highlevel_inbox_poller.py` now applies a controlled live reply gate before calling `send_reply`.
- `scripts/fundz_credit_tracker_bridge.py` now checks the Command Center kill switch before live outbound replies and requires `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED=true` before webhook-driven live replies.
- Plain SMS is held even if live flags are on.
- App/portal proof is required before a live customer-service reply can pass the gate.
- Command Center kill switch, dry-run, business-hours, and controlled-approval flags are enforced.
- Sensitive/proof-dependent replies continue to hold for owner review or verified context.
- `data/local/command-center/fundz-command-center.md` now shows a Customer-Service Live Reply Gate section.

## Verification

- `python3 -m unittest tests.test_fundz_highlevel_inbox_poller -q`: passed 30 tests.
- `python3 -m unittest tests.test_fundz_command_center -q`: passed 58 tests.
- `python3 -m unittest tests.test_fundz_highlevel_inbox_poller tests.test_fundz_command_center tests.test_fundz_autonomy tests.test_fundz_autonomous_operator -q`: passed 111 tests.
- `python3 -m py_compile scripts/fundz_highlevel_inbox_poller.py`: passed.
- `make command-center`: passed.
- `sh scripts/check-memory.sh`: passed.
- `make test`: passed 246 tests.

## Safety Boundary

No live reply was sent.
No live HighLevel poller was started.
No bridge, webhook, tunnel, DF/AutoFox edit, billing edit, campaign assignment, or client-send runtime was enabled.
