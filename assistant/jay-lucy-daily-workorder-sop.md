# Jay and Lucy Daily Workorder SOP

Purpose: make Jay and Lucy's daily work visible before clock-out so Governor, LOGIC, FUNDz, and Brandon can see what moved, what is blocked, who owns the next action, and what proof exists.

This SOP is for internal operations only. It does not approve client messages, campaign assignments, HighLevel replies, DisputeFox edits, AutoFox edits, billing changes, or credit strategy changes.

## Operating Surfaces

- Slack reminder channel: `#3clock-out-end-of-day-report`.
- Daily command: `/workorder`.
- Shared tracker: `LOGIC + FUNDz Work Orders`.
- Main tracker tab: `Work Orders`.
- Command Center: `A FUND Solution Command Center`.
- Public SOP route in Governor: `/daily-workorder`.

## Daily Timeline

1. Morning setup: Governor creates or confirms daily work-order rows for Jay, Lucy, FUNDz, GHL Agent, and LOGIC.
2. During the day: Jay and Lucy do the work in their normal systems and keep quick notes on clients, blockers, and proof.
3. Before clock-out: Jay and Lucy run `/workorder` in Slack.
4. Same day closeout: Each person submits the form with status, summary, details, next step, owner, due date, and evidence.
5. Governor review: Governor checks the submitted rows for missing owner, next step, due date, evidence, stale work, blockers, and anything that needs Brandon.

## Jay SOP - Disputer

Jay reports dispute production and anything blocking the next dispute action.

Required closeout:

- Clients processed today: client name or safe client ID, plus the dispute action completed.
- Dispute progress: letters prepared, rounds moved, accounts reviewed, bureau response reviewed, documents checked, or dispute packet updated.
- Blockers: missing report, missing CMS access, missing document, invalid login, payment/billing issue, client not ready, unclear next round, or system issue.
- Next action: the exact next move, who owns it, and when it is due.
- Evidence: safe proof location, screenshot filename, source link, sheet row, export name, or note location.

Jay should not mark a row complete unless the next action is clear or the work is truly finished with proof attached.

## Lucy SOP - Supervisor

Lucy reports supervisor review, readiness checks, follow-up quality, and team support needs.

Required closeout:

- Clients reviewed today: clients checked, moved forward, corrected, held, or escalated.
- Supervisor checks: due clients, new clients, next-round readiness, billing or negative-day issues, AutoFox/GHL/FUNDz messages, proof gaps, and team follow-up quality.
- A FUND Solution billing maintenance queue: work `data/local/maintenance-cleanup/fundz-lucy-billing-workqueue.md` when it has rows, starting with P1/P2 clients. Use `assistant/lucy-billing-maintenance-sop.md` for decision options and proof rules.
- Issues needing action: client issue, owner, due date, and what needs to be fixed.
- Team support needed: what Jay, LOGIC, FUNDz, Governor, or Brandon needs to do next.
- Evidence: safe proof location, screenshot filename, source link, sheet row, export name, or note location.

Lucy should flag repeated process issues clearly, especially anything that can delay client progress, payment collection, or leadership decisions.

## Required Workorder Fields

Every submitted row needs:

- `status`: `in_progress`, `blocked`, `waiting`, `completed`, or `needs_review`.
- `summary`: one plain-language line describing what happened.
- `details`: the work performed, clients affected, blocker context, and proof notes.
- `next_step`: the exact next action.
- `owner`: the person or system responsible for the next action.
- `due_date`: the next expected action date.
- `evidence`: screenshot, sheet row, export, receipt, source link, or local path.

## Status Rules

- Use `completed` only when the work is done and evidence exists.
- Use `in_progress` when the work started but still needs another step.
- Use `blocked` when progress cannot continue without a missing dependency.
- Use `waiting` when the next action depends on a client, vendor, system, or another teammate.
- Use `needs_review` when Brandon, Lucy, Governor, or LOGIC needs to inspect before the item moves.

## Privacy Rules

Do not include:

- Full SSNs.
- Full account numbers.
- Passwords or login codes.
- API keys, tokens, or private credentials.
- Full raw report data.
- Private personal-phone message bodies.
- Sensitive client details that are not needed for the next action.

Use client names, safe client IDs, last four digits only when needed, and proof locations instead of raw private data.

## Escalate To Brandon

Escalate when:

- A client-facing message needs approval.
- A campaign assignment or AutoFox/DisputeFox edit is needed.
- A billing or payment status needs a decision.
- A dispute strategy decision is unclear.
- A client is blocked by missing access, missing payment, no report, no documents, or a repeated system failure.
- Evidence is missing for a claimed completed item.
- The issue affects money, client trust, deliverability, or same-day deadlines.

Escalation format:

```text
Needs Brandon:
Client/System:
Status:
What happened:
Evidence:
Decision needed:
Recommended next step:
```

## Five-Minute Closeout Script

Jay:

```text
Today I processed [clients/actions]. The biggest item moved forward was [summary]. Blockers are [blockers or none]. Next step is [action] owned by [owner] due [date]. Evidence is [proof location].
```

Lucy:

```text
Today I reviewed [clients/areas]. Readiness issues are [issues or none]. Team support needed is [support or none]. Next step is [action] owned by [owner] due [date]. Evidence is [proof location].
```

## Done Standard

A Jay or Lucy workorder is done when Governor can answer these questions without guessing:

- What work happened today?
- Which client or system is affected?
- Is the item complete, blocked, waiting, or needing review?
- Who owns the next action?
- When is it due?
- Where is the proof?
- Does Brandon need to decide anything?

If any answer is missing, the row stays `in_progress`, `blocked`, `waiting`, or `needs_review` instead of `completed`.
