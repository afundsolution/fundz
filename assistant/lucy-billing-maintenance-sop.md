# A FUND Solution Billing Maintenance SOP for Lucy

Purpose: give Lucy ownership of recurring A FUND Solution billing maintenance using FUNDz-generated evidence, so Brandon does not have to manually sort every billing issue.

This SOP is internal operations only. It does not approve client contact, payment reminders, billing edits, DisputeFox edits, AutoFox edits, HighLevel sends, or campaign assignments.

## Source Queue

Lucy works from:

- `data/local/maintenance-cleanup/fundz-lucy-billing-workqueue.md`
- `data/local/maintenance-cleanup/fundz-lucy-billing-workqueue.csv`
- `data/local/command-center/fundz-billing-maintenance-focus.md`

The queue is generated from active billing issues only. FUNDz is the source workflow that produces the local evidence; A FUND Solution is the business and the Command Center owner. Rows already marked paid, paid and active, archived, stale, missing from active export, or DF-error-pending-fix stay out of Lucy's active billing work unless a fresh system refresh brings them back.

## Lucy's Job

For each client in the queue, Lucy decides one of:

- `paid_active`: client paid and service is active.
- `archived_or_not_active`: client should stay out of active billing work.
- `vendor_or_system_error`: DF, ScoreFusion, or another provider needs a fix or answer.
- `still_billing_issue`: proof says the billing issue is still real.
- `needs_brandon`: the decision requires owner approval, live edit, client contact, or conflicting proof needs judgment.

## Required Proof

Lucy needs a proof note or screenshot/location for every decision:

- Payment or service-active proof.
- Archived/not-active proof.
- Vendor/system-error proof and who was contacted.
- Still-failed billing proof.
- Reason Brandon needs to decide.

Do not paste private credentials, full SSNs, full card/account numbers, raw report details, or private message bodies into the queue.

## Escalate To Brandon

Escalate only when:

- A client-facing message or payment reminder is needed.
- A live billing, DF, ScoreFusion, AutoFox, or HighLevel edit is needed.
- Proof conflicts.
- Money judgment is unclear.
- A repeated vendor/system issue is blocking multiple clients.

Escalation format:

```text
Needs Brandon:
Client:
Lucy decision:
Proof:
Blocker:
Recommended next step:
```

## Closeout

At closeout, Lucy reports:

- How many billing clients reviewed.
- Which clients were moved to paid/active, archived/not-active, vendor/system error, still billing issue, or needs Brandon.
- What proof was attached.
- Which rows remain for tomorrow.
