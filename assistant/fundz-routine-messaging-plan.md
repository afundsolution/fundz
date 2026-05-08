# FUNDz Routine Messaging Plan

## Goal

FUNDz Reach should keep every active member contacted on a predictable rhythm so members feel actively supported while FUNDz is working their file. The cadence should be frequent, but still useful, truthful, and safe: no duplicate blasts, no messages around billing/onboarding blockers, and no promises about deletions, score increases, approvals, or guaranteed outcomes.

Credit Tracker/app and email should be sent together for approved routine outreach so members have two chances to receive the update. Credit Tracker remains the primary record because it is cheaper and keeps message history visible for members. Email is the companion channel and should carry the same core update.

Important implementation note: HighLevel conversation sends with type `SMS`/`Email` do not necessarily create a visible Credit Tracker app/portal post. Portal/app visibility requires the AutoFox/Credit Tracker workflow described in `assistant/autofox-credit-tracker-portal-setup.md`.

## Current Baseline

Latest local state reviewed on May 4, 2026:

- Active members in local FUNDz state: 180.
- Due for next round: 102.
- In dispute: 68.
- Unknown active status: 10.
- Draft-ready for owner approval: 66.
- Monitor only: 35.
- Needs owner review before messaging: 79.
- Active members without email in local state: 0.
- Active members with no linked SMS history: 2.
- Active members with no linked email history: 149.

Latest AutoFox outbound audit:

- Outbound records reviewed: 5,451.
- Unique recipients found: 559.
- Failed/error outbound records: 250.
- Possible duplicate sends: 75.
- Risky-language records: 0.
- Outside business-hour records: 14.

The audit shows AutoFox is already sending volume, but the failure, duplicate, and after-hours rows must be reviewed before broad FUNDz expansion.

## Operating Policy

FUNDz should not message everyone the same way. Every active member should be assigned to one of four lanes:

- `send_ready`: active, valid contact method, no billing/onboarding blocker, not recently contacted with the same update.
- `monitor`: active dispute is moving normally; no new update needed yet.
- `owner_review`: billing issue, incomplete onboarding, missing next import, unclear active status, DND, failed prior send, duplicate risk, or missing contact mapping.
- `blocked`: unsafe message language, unresolved contact ID, missing required channel data, or client has opted out.

No live batch should send from `owner_review` or `blocked`.

## Message Rhythm

Use a high-touch contact clock per active member. The default target is every other business day, with lighter daily micro-touches during sensitive windows. Same-day Credit Tracker/app plus email counts as one touch, not two separate touches.

- Default active-member rhythm: every other business day.
- First 14 days after enrollment: daily business-day onboarding/check-in touches until setup is complete.
- Days 15-45: every other business day while expectations are being set.
- Day 46 and later: every other business day when there is a meaningful status, tracker, portal, document, import, or education touch; otherwise at least twice weekly.
- Due-for-next-round window: daily business-day touches from 3 days before expected readiness through the day the next round is prepared or sent.
- Active dispute with no new movement: every other business day, alternating between tracker monitoring, education, and availability check-ins.
- Waiting on member action: daily business-day reminders until completed, paused, or escalated.
- Billing/onboarding/problem accounts: do not send normal routine updates; route to owner review or use the approved billing/onboarding message only.

For members due for the next round, the update should be tied to round readiness. For members in dispute, the update should be tied to monitoring and next import timing. For billing/onboarding issues, FUNDz should not send a normal update until the owner clears the account.

## Time-In-System Cadence

The message should depend on how long the member has been in the system and what stage they are in.

| Time In System | Contact Frequency | Primary Purpose | Message Style |
|---|---:|---|---|
| Days 0-7 | Every business day | Welcome, setup, portal habit, expectation setting | Short, reassuring, action-oriented |
| Days 8-14 | Every business day if setup is not complete; otherwise every other business day | Keep onboarding moving | Friendly reminders and setup checks |
| Days 15-45 | Every other business day | Build confidence and reduce "what is happening?" anxiety | Monitoring notes, next-step reminders, education |
| Days 46-90 | Every other business day when movement is active; otherwise twice weekly | Show steady attention without repeating the same update | Tracker watch, round status, soft check-ins |
| Days 91+ | Twice weekly minimum; every other business day if due/active/problem window | Retention and confidence | Progress review, monitoring, availability, next-round readiness |

Do not message seven days per week unless the owner explicitly approves a special situation. Keep routine sends inside the 9 AM to 9 PM Central contact window, preferably late morning or early afternoon.

## Touch Rotation

To avoid repetitive messages, rotate the purpose of each touch:

- Touch A: file/status update
- Touch B: portal/check-your-tracker reminder
- Touch C: education or expectation setting
- Touch D: "we are still monitoring" reassurance
- Touch E: action-needed reminder, if applicable
- Touch F: owner-review or escalation note, if applicable

FUNDz should not send two messages in a row with the same wording unless the owner explicitly approves it.

## Starter Message Sequence

### Credit Tracker / App Message 1

Hello {first_name}, thank you for your patience as our team continues working on your file. We are reviewing your latest import and preparing the next dispute-round update. Our goal is to keep making steady progress and keep you informed as new tracker updates come in. You can also check your Credit Tracker portal for updates, and you are welcome to reply here if you have any questions.

### Email Message 1

Subject: FUNDz file update

Hi {first_name},

Thank you for your patience as our team continues working on your file. We are reviewing your latest import and preparing the next dispute-round update.

Our goal is to keep making steady progress and keep you informed as new tracker updates come in. You can also check your Credit Tracker portal for updates, and you are welcome to reply here or in the app if you have any questions.

FUNDz

### Every-Other-Day Monitoring Touch

Hello {first_name}, FUNDz is still monitoring your file and tracker activity. There is nothing extra you need to do right now unless you see a new alert or have a question. We will keep watching it and update you as the next step becomes clear.

### Portal Habit Touch

Hello {first_name}, quick reminder from FUNDz: you can check your Credit Tracker portal anytime for updates or alerts. If something new appears and you want us to review it, reply here and we will take a look.

### Education Touch

Hello {first_name}, FUNDz is continuing to monitor your file. Some tracker changes can show at different times depending on the bureau, creditor, and monitoring source, so we review the file and tracker together before giving the next update.

### New Member Setup Touch

Hello {first_name}, welcome again to FUNDz. We are checking your setup and tracker access so your file can keep moving smoothly. If anything in the portal looks incomplete, please reply here and we will help you get it handled.

### Due For Next Round Message

Hello {first_name}, FUNDz is reviewing your file for the next dispute round. Thank you for your patience while we check the latest import and prepare the next update. We will keep you posted as soon as the next step is ready.

### Active Dispute Message

Hello {first_name}, your dispute round is active and FUNDz is continuing to monitor your tracker. You do not need to take action right now unless you receive a new alert or notice something you want us to review.

### No Response Follow-Up

Hello {first_name}, FUNDz is checking in to make sure you are receiving our updates. Please reply here if you have questions or if anything changed in your Credit Tracker portal.

### Billing / ScoreFusion Hold Message

Hi {first_name}, I see this may need ScoreFusion billing review before we give a full file update. Please check your ScoreFusion account for any missed payment or billing notice. I am also flagging this for Brandon so we do not give you the wrong information.

## Audit Steps Before Expansion

1. Review the latest AutoFox audit failures and classify each row as provider/test noise, billing/client-card issue, real failed member message, or resend needed.
2. Review the duplicate candidates and identify any workflows that could send the same message twice in one day.
3. Review after-hours sends and confirm whether AutoFox is using Central time and the 9 AM to 9 PM contact window.
4. Export or capture AutoFox workflow names/templates so FUNDz can map each AutoFox message to a member lifecycle stage.
5. Compare AutoFox recipients against the 180 active-member state so every member has a last-contact date and channel.
6. Freeze broad sending until the first small Credit Tracker batch is reviewed and accepted.

## Rollout Plan

### Phase 1: Audit And Map

Build a member contact ledger with:

- member name or client key
- active status
- lifecycle lane
- last AutoFox message date
- last Credit Tracker/app message date
- last email date
- last reply date
- delivery status
- next scheduled FUNDz touch
- owner-review reason, if any

### Phase 2: Small Credit Tracker Pilot

Send only 3 to 5 owner-approved Credit Tracker/app messages from the `send_ready` lane. Do not include billing, incomplete onboarding, missing next import, failed-send, duplicate-risk, or unclear-status members.

Send the matching email companion in the same pilot window after confirming the HighLevel/Credit Tracker contact record has a valid email. If the platform rejects email because the contact has no email, do not keep retrying; mark that member for contact-record cleanup.

Success criteria:

- message accepted by provider
- companion email accepted by provider, or blocked with a clear contact-record reason
- visible in contact conversation history
- no duplicate send
- no risky credit-repair language
- no send outside business hours
- receipt written locally

### Phase 3: Email Backup

For pilot members who do not reply or do not have confirmed delivery after 3 days, send the matching email follow-up. Keep the email short and point them back to Credit Tracker/app for ongoing updates.

### Phase 4: Weekly Routine

Every week, FUNDz should:

- rebuild the active-member state
- rerun the AutoFox audit
- update the contact ledger
- draft the next send-ready batch
- create an owner-review list
- prepare message previews before anything live goes out

### Phase 5: Controlled Expansion

Increase live batches only after the pilot is clean:

- week 1: 3 to 5 members
- week 2: 10 members
- week 3: 25 members
- after that: daily cap set by owner approval and deliverability results

## Proof That Nobody Is Missed

FUNDz should produce a weekly report with:

- active members count
- contacted in last 7 days
- contacted in last 30 days
- not contacted in 30 days
- failed sends needing owner review
- duplicate-risk members
- DND/opt-out members
- billing/onboarding holds
- next planned batch

The main rule: every active member must either have a recent contact, a future scheduled contact, or a clear owner-review/blocker reason.

## Immediate Next Action

Start with the 66 `draft_for_approval` members, then narrow that to a 3 to 5 member Credit Tracker/app pilot after removing anyone with recent duplicate risk, unresolved contact ID, billing issue, onboarding issue, missing next import, DND, or failed prior delivery.

Before live routine messaging, the HighLevel token still needs conversation/message read scope so FUNDz can confirm replies and delivery history from HighLevel. The permanent Cloudflare tunnel is still useful for webhooks, but the HighLevel inbox poller can be the fallback once that token scope is fixed.
