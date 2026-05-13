# FUNDz Broad Autonomous Customer-Service Supervisor Packet

Generated: 2026-05-13 10:24 CDT

Scope: local supervisor preparation for true broad autonomous customer service. This packet does not approve or perform live replies.

## Supervisor Decision

FUNDz is controlled-live ready for one named, owner-approved, non-sensitive app/portal reply at a time.

FUNDz is not broad-autonomous ready. Broad third-party autonomous customer service remains blocked until the live proof run below is completed with receipts and Brandon approves expansion from the controlled proof result.

## Completed Locally Now

- Current memory and Command Center truth were reviewed.
- Existing controlled-live code gates were confirmed in the handoff/status packet:
  - HighLevel live replies require dry-run off, `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED=true`, kill switch off, app/portal proof signal, business-hours or explicit override, no sensitive/proof-dependent labels, and receipt logging.
  - Webhook live replies require `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED=true` and still check the command-center kill switch.
  - Plain SMS and proof-dependent topics stay held.
- Broad mode is documented as blocked.
- The safe local readiness package is now consolidated here:
  - rollout approval packet
  - scope and cap
  - runtime wake checklist
  - first-client proof runbook
  - one-reply receipt gate
  - expansion rules

## Action-Time Approval Required

No one may wake live reply runtime, send a reply, wire a webhook, start the live HighLevel poller, assign a campaign, edit DF/AutoFox, or enable broad mode without Brandon's exact action-time approval.

Approval must name:

- exact target client or owner-side test profile
- exact source path: HighLevel app/portal row, DF All Messages row, Credit Tracker app/portal event, or webhook payload
- exact channel: app/portal reply path only, not plain SMS
- exact reply copy or approved response template
- exact cap
- exact action window
- whether after-hours override is allowed
- receipt target
- rollback/park command

## Rollout Approval Packet

Minimum approval language:

```text
Approve one controlled-live FUNDz customer-service app/portal reply only.
Target: [client/profile]
Source proof: [app/portal event receipt path]
Channel: [HighLevel app/portal or webhook app/portal path]
Reply copy: [exact approved text]
Cap: 1 reply
Window: [date/time]
After-hours override: no unless explicitly stated
Receipt required: yes
After reply: park runtime and update proof packet
```

Approval does not authorize:

- broad autonomous replies
- plain SMS replies
- billing, cancellation, complaint, document, app-access, score, or dispute-update replies without verified context and owner review
- DF/AutoFox edits
- campaign assignment
- billing edits
- webhook wiring beyond the named test
- future replies after the single approved receipt

## Scope And Cap

### Controlled-Live Cap

- Cap: 1 reply.
- Audience: one named profile only.
- Channel: app/portal proof path only.
- Reply type: non-sensitive support acknowledgement or simple routing response.
- Runtime: wake only the named path needed for the proof run.
- Stop condition: stop after one receipt, one hold, one mismatch, or any safety finding.

### Broad Autonomous Cap

Broad cap remains 0.

Before a broad cap can be proposed, FUNDz needs:

- at least one clean third-party client app/portal inbound proof captured by API/webhook/manual-import evidence
- at least one owner-approved reply receipt for that third-party path
- source mapping that does not depend on browser-only screenshots
- current live health proof after approved wake
- verified kill switch and send gate behavior
- fresh Work Queue / Client Communication Control Board review
- exclusion rules applied to billing-risk, owner-review, no-recent-contact, DND/opt-out, archived/inactive, bounced/failed, and sensitive-topic rows
- Brandon's approval of a capped expansion count

## Runtime Wake Checklist

Do this only after Brandon approves the exact action-time run.

1. Confirm workspace: `/Users/turbo/Desktop/Go High Level Agent/FUNDz`.
2. Review:
   - `FUNDZ_SLEEP_MODE.md`
   - `memory/HANDOFF.md`
   - `memory/CURRENT_STATUS.md`
   - `memory/NEXT_STEPS.md`
   - `data/local/command-center/fundz-command-center.md`
   - `data/local/command-center/fundz-send-gate-lock.md`
   - `data/local/command-center/fundz-send-kill-switch.md`
3. Run safe local refresh if data changed:
   - `make autonomous` or `make command-center`
4. Verify the kill switch state is intentional.
5. Verify receipt files are writable:
   - `data/local/highlevel-inbox-poller/app-portal-event-proof.jsonl`
   - `data/local/highlevel-inbox-poller/reply-receipts.jsonl`
6. Verify source proof exists before reply:
   - app/portal event proof row with message type/source/channel/timeline
   - no plain SMS-only evidence
7. Wake only the named runtime path.
8. Recheck health:
   - local health
   - public health if bridge/tunnel is part of the approved run
   - `make webhook-probe` for webhook path, test-only
9. Set live flags only for the approved window:
   - HighLevel controlled path: `CREDIT_TRACKER_DRY_RUN=false`, `FUNDZ_HIGHLEVEL_POLLER_LIVE=true`, `FUNDZ_HIGHLEVEL_CONTROLLED_REPLY_APPROVED=true`
   - Webhook controlled path: `FUNDZ_WEBHOOK_CONTROLLED_REPLY_APPROVED=true`
   - after-hours flag only if Brandon explicitly approved it
10. Run exactly one approved reply or hold.
11. Capture receipt.
12. Park runtime again.
13. Update proof artifacts and memory.

## First-Client Proof Runbook

Preferred candidate order:

1. Owner-side proof route only if testing plumbing again.
2. Erika Jordan only if a third-party app/portal test is required, after fresh read-only DF app status and exact action-time approval.
3. Anthony Williams only as a conditional backup; existing Installed / Logged In proof does not approve retry or rollout.

Do not use Henry Fisher Sr. for the next clean-campaign/app proof. May 13 live DF preflight showed archived/payment-failed risk.

Before reply:

- Confirm profile matches the approved target.
- Confirm app/portal source evidence is current and captured into `app-portal-event-proof.*`.
- Confirm the event is not plain SMS.
- Confirm topic is not billing, cancellation, complaint, document, app access, score concern, or dispute update unless owner provided verified context and exact approved response.
- Confirm DND/opt-out/billing/archived/inactive/client mismatch checks do not block the reply.
- Confirm reply copy is exact and contains no placeholders, private overexposure, funding/preapproval claims, or guaranteed-outcome language.

During reply:

- Send only once.
- Do not continue to a second profile.
- Do not change campaigns, DF records, billing, or AutoFox.

After reply:

- Confirm provider status.
- Confirm client-visible app/portal visibility when feasible.
- Write receipt to `reply-receipts.jsonl`.
- Write a readable proof note under `data/local/command-center/` or `data/local/semi-autonomous/receipts/`.
- Regenerate Command Center.
- Park runtime.

## One-Reply Receipt Gate

A controlled-live proof run is not complete until all receipt points exist:

- pre-reply app/portal proof row in `data/local/highlevel-inbox-poller/app-portal-event-proof.jsonl`
- approved target/client and exact copy recorded
- live flag set used only for the approved run
- provider/send response captured
- `data/local/highlevel-inbox-poller/reply-receipts.jsonl` appended with successful receipt, or hold receipt if not sent
- readable Markdown proof note created
- post-run runtime parked
- Command Center refreshed
- memory handoff/status/next steps updated

If any receipt is missing, call the run `blocked` or `held`, not complete.

## Expansion Rules

Expansion can only be proposed after a clean one-reply proof.

### Step 1: Controlled Proof

- 1 named app/portal reply.
- Stop and review.

### Step 2: Tiny Human-Reviewed Batch

Allowed only after Step 1 passes and Brandon approves a new cap.

- Suggested cap: 3 replies maximum.
- Each row must have app/portal proof, non-sensitive label, exact approved copy, and receipt.
- Stop on first safety issue or first missing receipt.

### Step 3: Capped Supervised Batch

Allowed only after Step 2 passes.

- Suggested cap: 5 to 10 replies maximum.
- Must exclude billing risk, owner-review, no-recent-contact, DND/opt-out, archived/inactive, failed/bounced, duplicate-risk, and sensitive-topic rows.
- Must keep live monitoring open and receipts current.

### Step 4: Broad Autonomous Mode

Not approved.

Broad autonomous mode requires a separate Brandon approval and a fresh supervisor packet proving:

- repeatable app/portal source mapping
- tested kill switch
- live health
- receipt durability
- safe-topic classifier behavior
- owner-visible dashboard state
- rollback/park proof
- scoped cap and escalation rules

## Proof Artifacts To Update

Update these after the next approved controlled-live proof:

- `data/local/command-center/fundz-broad-autonomous-customer-service-supervisor-packet-2026-05-13.md`
- `data/local/command-center/fundz-customer-service-readiness-2026-05-13.md`
- `data/local/command-center/fundz-production-verification-2026-05-13.md`
- `data/local/command-center/fundz-command-center.md`
- `data/local/command-center/fundz-send-gate-lock.md`
- `data/local/command-center/fundz-send-kill-switch.md`
- `data/local/highlevel-inbox-poller/app-portal-event-proof.jsonl`
- `data/local/highlevel-inbox-poller/app-portal-event-proof.md`
- `data/local/highlevel-inbox-poller/reply-receipts.jsonl`
- `memory/HANDOFF.md`
- `memory/CURRENT_STATUS.md`
- `memory/NEXT_STEPS.md`
- `memory/CHANGELOG.md`

## Current Final State

Can complete locally now: supervisor packet, gates, scope, cap, runbook, receipt gate, expansion rules, and proof-artifact list.

Requires action-time live approval: any live reply, live poller, bridge/webhook wake, client-facing response, app/portal third-party proof run, broad cap, campaign assignment, DF/AutoFox edit, billing edit, or webhook wiring.

Recommended next move: get Brandon approval for exactly one controlled third-party app/portal proof run, then execute the one-reply receipt gate and park runtime immediately after proof capture.
