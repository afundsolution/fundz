# FUNDz Broad Autonomous Rollout Gate

Generated: 2026-05-13T10:28:14-0500

## Decision
- Broad autonomous mode is not enabled.
- This surface defines the proof ladder required before any future expansion.

## Scope And Cap
- State: blocked_not_enabled
- Broad mode enabled: False
- Scope: Customer-service app/portal replies only. Excludes billing, cancellation, complaint, document request, app-access, score, dispute-update, campaign assignment, DF/AutoFox edits, billing edits, and broad outreach sends.
- Current cap: 0 broad autonomous replies.
- Next controlled cap: 1 named client, 1 app/portal inbound, 1 exact approved reply, 1 receipt.

## Recommended First Candidate
- Candidate: Erika Jordan
- Reason: Cleanest local real-client evidence: app installed/logged in and prior admin-side App Message visibility proof. Must be refreshed read-only before contact.
- This is a local proof recommendation only; it does not authorize contact or send.

## Exclusions
- Henry Fisher Sr. - archived/payment-failed warning in May 13 read-only preflight.
- James Hawkins - archived and app only Invitation Sent in May 13 read-only preflight.
- Anthony Williams - installed/logged in but prior proof does not approve retry or rollout.
- Any billing, cancellation, complaint, document, app-access, score, or dispute-update row.
- Any DND, opt-out, no-recent-contact exception, billing-risk, duplicate-risk, or owner-review client.

## Approval Required Before First Live Reply
- Named client.
- Exact inbound app/portal source to watch.
- Exact reply copy or approved reply category.
- Exact action window.
- Explicit cap of 1 reply.

## Runtime Wake Proof
- Run `make inactive` first if any unexpected runtime is awake.
- Wake only the named bridge/tunnel/poller path needed for the approved test.
- Verify local and public health during the wake.
- Run `make webhook-probe` if webhook path is used.
- Confirm command-center kill switch is off only for the approved window.
- Confirm `CREDIT_TRACKER_DRY_RUN=false` only for the approved window.
- Confirm `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED=true` or `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED=true`, not both unless both paths are intentionally in scope.

## First-Client Proof Requirements
- Named client and owner approval for that exact client before live action.
- Fresh app/portal inbound proof from API, webhook, or manual import with message type/source/channel preserved.
- Exact reply copy approved before send.
- Dry-run intentionally disabled only for the approved action window.
- Command-center kill switch confirmed off before the send and available for rollback.
- No sensitive/proof-dependent labels: billing, cancellation, complaint, document request, app access, score concern, or dispute update.
- Successful HighLevel/app reply receipt written to `data/local/highlevel-inbox-poller/reply-receipts.jsonl`.
- Client-side or admin-side visibility proof captured after the reply.
- Post-send review shows zero duplicate sends, failed sends, or unexpected runtime findings.

## Expansion Rules
- Do not expand from Brandon owner-side proof alone; first third-party client proof is still required.
- After one clean third-party proof, the next cap is 3 named clients, owner-approved one by one, with receipts for each.
- After three clean third-party receipts, the next cap is 5 named clients in one business-day window; no overnight or after-hours expansion.
- Any sensitive label, failed receipt, duplicate, complaint, billing/payment issue, app-access confusion, score/dispute question, or runtime finding stops expansion.
- Broad autonomous mode remains disabled until Brandon explicitly approves broad mode after reviewing the capped receipts and rollback proof.

## Rollback / Park Command
- Run `make inactive` to park local live runtimes.
- Turn on `data/local/command-center/fundz-send-kill-switch.json` if any live-send risk appears.
- Unset `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED` and `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED` after the approved action window.
- Regenerate `make command-center` and confirm the Safety Gate shows live sends disabled and rollout selected 0.

## Still Blocks Broad Mode
- No explicit Brandon approval exists for broad autonomous third-party replies.
- No clean third-party first-client customer-service reply receipt has been captured from this gate.
- Proof-dependent reply classes still require owner or verified-context review.
- Live bridge, webhook, and poller runtimes are parked by default.
- Rollback proof must stay visible before any capped expansion.

## Related Surfaces
- Command Center: data/local/command-center/fundz-command-center.md
- Send visibility: data/local/command-center/fundz-send-visibility-command-center.md
- Send kill switch: data/local/command-center/fundz-send-kill-switch.md
- App/portal proof: data/local/highlevel-inbox-poller/app-portal-event-proof.jsonl
- Reply receipts: data/local/highlevel-inbox-poller/reply-receipts.jsonl
