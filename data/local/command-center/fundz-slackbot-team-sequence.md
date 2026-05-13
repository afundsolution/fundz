# FUNDz Slackbot Team Sequence

Generated: 2026-05-13T11:12:53-05:00

## Mission

Use Slackbot and Slack AI as the internal team memory, recap, search, reminder, and canvas layer.

Slackbot is the team librarian and coordinator. FUNDz/LOGIC are the operators that decide meaning, proof, next action, and closeout.

## Current Queue Truth

- Work Queue rows: 225
- Blocking or decision rows: 53
- Status counts: Approved=125, Blocked=16, Done=46, Needs Brandon=37, Sent=1

## Channels To Create

### #afs-daily-board

- Owner: Brandon
- Purpose: One plain-language morning board for what matters now across FUNDz, LOGIC, Lucy, and Jay.
- Slack AI use: Recap yesterday, summarize today's thread, and turn the board into a short owner brief.
- Boundary: FUNDz/LOGIC decide meaning, proof status, and next action; Slackbot only organizes the board.
- Sources: data/local/command-center/fundz-daily-board.md;data/local/command-center/fundz-today-operating-board.md

### #fundz-ops

- Owner: FUNDz
- Purpose: Internal FUNDz operations, safe local autonomy status, customer-service readiness, and blocked work.
- Slack AI use: Find blockers, summarize proof threads, explain technical status in plain language.
- Boundary: No live bridge, poller, webhook, client reply, campaign, DF/AutoFox edit, or billing edit from Slackbot.
- Sources: data/local/command-center/fundz-command-center.md;data/local/command-center/fundz-send-visibility-command-center.md;data/local/command-center/fundz-send-gate-lock.md

### #logic-disputes

- Owner: LOGIC
- Purpose: Dispute operations, letter context, bureau response questions, and old-letter lookup requests.
- Slack AI use: Search Slack for old context and prepare source packets for LOGIC.
- Boundary: LOGIC interprets dispute meaning and review gates; Slackbot does not approve letters or strategy.
- Sources: LOGIC Slackbot tag-team protocol; Slack message/file sources

### #lucy-billing

- Owner: Lucy
- Purpose: Billing maintenance, payment proof, archive proof, and owner billing decisions.
- Slack AI use: Turn billing rows into a checklist and remind Lucy which proof is still missing.
- Boundary: No payment called collected without receipt-level proof; no billing edits from Slackbot.
- Sources: data/local/maintenance-cleanup/fundz-lucy-billing-workqueue.md

### #jay-workorders

- Owner: Jay
- Purpose: End-of-day workorder closeout and carried-forward tasks.
- Slack AI use: Validate owner, due date, status, evidence, next step, and blocker language before closeout.
- Boundary: A summary is not proof; workorders close only with evidence or explicit blocker outcome.
- Sources: assistant/jay-lucy-daily-workorder-sop.md

### #owner-review

- Owner: Brandon
- Purpose: Only the decisions Brandon must make: approvals, blockers, proof gaps, and send gates.
- Slack AI use: Summarize open decisions and locate proof links before asking Brandon.
- Boundary: Approved is a gated queue state, not done; no sends or live changes without action-time approval.
- Sources: data/local/command-center/fundz-owner-review-packet.md;data/local/command-center/fundz-governor-alerts.csv

## Daily Sequence

### Morning

- Owner: Brandon or operator on duty
- Action: Post or refresh the daily board in #afs-daily-board, then let Slack AI recap it.
- Output: What matters now, blockers, Needs Brandon, safe local work, and proof gaps.

### Midday

- Owner: FUNDz
- Action: Use Slackbot search/summaries to locate missing proof and stale decisions.
- Output: Short context packets for FUNDz, LOGIC, Lucy, or Jay.

### End of day

- Owner: Jay/Lucy
- Action: Submit /workorder and run the Slackbot workorder check prompt before closeout.
- Output: Every item has status, owner, next step, evidence, and blocker language when needed.

### Before closeout

- Owner: FUNDz/LOGIC
- Action: Confirm Slack summaries match proof files before marking anything Done or Sent.
- Output: Receipt-backed closeout or clear carry-forward blocker.

## Rollout Steps

- Create the six internal channels manually in Slack.
- Pin this sequence packet and the relevant source files/canvases in each channel.
- Turn on recaps for #afs-daily-board, #fundz-ops, #logic-disputes, #lucy-billing, and #owner-review.
- Use the shared Slackbot context-packet prompt for searches and summaries.
- Use FUNDz/LOGIC prompts for decisions, proof status, and next actions.
- After one week, compare workorder completion, open blockers, and proof gaps before expanding workflows.

## Live Slack Setup

- Canvas: https://afundsolution.slack.com/docs/T0335UDK8AG/F0B3LU8H6TC
- Kickoff message: https://afundsolution.slack.com/archives/C0AUEF81TKM/p1778688658173279
- Kickoff channel: #logic-briefing
- Channel creation status: manual_admin_required
- Connector limit: The available Slack connector can create canvases and post messages, but it cannot create channels.

## Copy-Ready Prompts

### Slackbot Context Packet

```text
Search Slack for context the operations team can use. Summarize facts only.

Topic/client:
Date range:
Channels or people to check:
Files/canvases to include:

Return:
1. What you found
2. Message/file links
3. What is missing or uncertain
4. Exact question for FUNDz or LOGIC
5. Reminder/follow-up Slackbot should track

Do not approve sends, change client strategy, edit billing, or treat summaries as proof.
```

### Fundz Decision Prompt

```text
Use this Slackbot context packet and tell us the next FUNDz operations step.

Client/member:
Context summary:
Message/file links:
Missing facts:
Question:

Return:
1. What this means
2. Next action
3. Owner
4. Proof needed before closeout
5. Whether this needs Lucy, Jay, LOGIC, or Brandon approval
```

### Daily Board Prompt

```text
Summarize today's A FUND Solution board in plain language for the team.

Use only posted source files or channel messages. Return:
1. What matters now
2. Blocked
3. Needs Brandon
4. Safe local work
5. Proof needed before anything is called done
```

### Workorder Check Prompt

```text
Check this /workorder before closeout. Flag missing status, owner, due date, next step, evidence, privacy issues, and any item marked done without proof. Do not rewrite client-facing copy.
```

## Safety Rules

- Slackbot is internal-only for this rollout.
- Slackbot can summarize, search, explain, remind, draft internal canvases, and organize proof links.
- Slackbot cannot send client messages, approve dispute strategy, edit DF/AutoFox, change billing, wire webhooks, wake live pollers, or mark Approved rows as Done.
- Approved means prepared but gated until receipt-backed proof or explicit blocker outcome exists.
- Any live client-facing step still needs Brandon's exact action-time approval and the existing FUNDz send gates.
- No full SSNs, full DOBs, full account numbers, passwords, secrets, or private personal data should be placed in shared Slack channels.

## Source Files

- data/local/command-center/fundz-daily-board.md
- data/local/command-center/fundz-today-operating-board.md
- data/local/command-center/fundz-command-center.md
- data/local/command-center/fundz-owner-review-packet.md
- data/local/command-center/fundz-governor-alerts.csv
- data/local/command-center/fundz-send-visibility-command-center.md
- data/local/command-center/fundz-send-gate-lock.md
- assistant/jay-lucy-daily-workorder-sop.md
- data/local/maintenance-cleanup/fundz-lucy-billing-workqueue.md
