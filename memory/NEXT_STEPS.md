# Next Steps

## Immediate Next Step

1. Keep FUNDz in safe local autonomous mode with both requested LaunchAgents enabled and the protected Command Center domain awake. Use `make autonomous` for local board/intake/maintenance/proposal/test refreshes; do not restart `fundz-bridge`, `fundz-highlevel-poller`, or any live browser/client-send workflow unless Brandon gives exact action-time approval for that specific live step. The only allowed `fundz-tunnel` screen is the protected Command Center tunnel created by `make command-center-domain`.
2. Start any future work by reading `FUNDZ_SLEEP_MODE.md`, then `memory/HANDOFF.md`, `memory/CURRENT_STATUS.md`, and this file.
3. Codex automation `fundz-safe-autonomous-operator` is active and scheduled hourly, and macOS LaunchAgent `com.afundsolution.fundz-autonomous-operator` is also enabled by Brandon request. Review output before adding any additional scheduler.
4. Latest safe autonomy proof: `data/local/autonomy/fundz-autonomous-operator-status.md`; latest run passed 6/6 operator steps, had no safety findings, allowed only the protected Command Center domain tunnel, and kept live sends disabled.
5. Review `data/local/command-center/fundz-send-visibility-command-center.md` before any client/lead messaging decision. It shows what FUNDz has locally sent or attempted, plus the next-send queue with exact message bodies.
6. The protected Command Center domain is `https://fundz-command.afundsolution.com/`. Get the tokenized owner URL from Git-ignored `data/local/command-center/fundz-command-center-domain.json`; do not commit or paste that token into public docs. `make autonomous` allows this protected domain tunnel with `FUNDZ_ALLOW_COMMAND_CENTER_DOMAIN_TUNNEL=true` while still blocking live send/edit/webhook runtimes. Latest public checks: `/health` 200, missing token friendly 403, bad token friendly 403, tokenized dashboard 200.
7. Before any approved semi-autonomous live send, verify the owner text notice gate. The queue should show `owner_notice_status=ready`; otherwise run `make owner-pre-send-notice`, wait at least 120 seconds, and rerun the approved live-send command.
8. Use `data/local/command-center/fundz-send-kill-switch.json` as the Command Center kill switch. Setting `"enabled": true` hard-blocks live client/lead sends, live HighLevel replies, DF/AutoFox campaign-assignment sends, and webhook-driven client responses while local reporting continues.
9. If Brandon only wants the folder to remain parked, run `make inactive` again and verify no `screen` sessions or matching FUNDz runtime processes are running.
10. If Brandon asks to wake a live piece, first run `make autonomous` or `make daily-board`, review the Work Queue, Client Communication Control Board, Send Visibility Command Center, owner text notice status, and kill-switch state, then re-enable only the exact runtime or workflow he named.
11. Current LaunchAgent proof: `launchctl print-disabled gui/$(id -u)` shows `com.afundsolution.fundz-autonomous-operator` and `com.afundsolution.fundz-imessage-fallback` enabled; both report last exit code `0`. The autonomous LaunchAgent still forces dry-run/no-live-send settings.

## Wake Backlog

The backlog below is preserved for a future wake request. Do not treat it as permission to resume live operations while the folder is inactive.

1. Start each work block with `make daily-board`. Work from the five-line board and the Work Queue before opening DF/Pulse, AutoFox, Credit Tracker, or HighLevel in the browser.
2. Review `data/local/command-center/fundz-client-communication-control-board.md` and `data/local/command-center/fundz-client-communication-control-board.csv` before any outreach decision. Current baseline: 168 Blocked, 10 Hold, 1 Needs Brandon, and 1 Done across 180 active clients.
3. Treat Erika's admin-side App SMS/App Message visibility proof as cleared: DF `Messages` / `Communications Center` / `All Messages` shows Workflow `App Message` rows marked `Sent`, with `Installed 05/04/26` and `Logged In` visible on the same profile. Proof: `data/local/semi-autonomous/receipts/erika-app-message-history-sent-proof-20260506.png`. The local missing-steps recheck now recognizes this proof and still keeps broad outreach blocked.
4. Do not treat the May 6 Portal Messages `0 results` search as an App SMS failure; Brandon clarified that Portal Messages was the wrong place to look. Henry Fisher Sr. is now the first freshly verified Installed / Logged In candidate for the next one-client test, with proof at `data/local/semi-autonomous/receipts/henry-fisher-app-status-installed-logged-in-proof-20260506.png`. The next live client-facing action, if any, still needs exact action-time approval naming Henry Fisher Sr. and the exact campaign/action target. Anthony Williams is suppressed for the current operating cycle per Brandon's instruction. Cloudflare domain/cert is complete.
4. Keep the OpenClaw iMessage fallback LaunchAgent enabled per Brandon's May 8 request. Check `logs/fundz-imessage-fallback.out.log`, `logs/fundz-imessage-fallback.err.log`, and `data/local/owner-command-mode/imessage-fallback-receipts.jsonl` if he reports another owner-command issue. The fallback handles owner-allowlisted `/new`/reset, stored client update/status requests, Daily Board / What's Next, and simple local-AI owner questions; restore OpenRouter credits or fix the OpenAI/Codex endpoint issue for the full OpenClaw agent path.
5. Use the local-first AI router for owner questions before paying for cloud AI. `make ai-router PROMPT="..."` uses local Ollama first. Paid AI is disabled by default, and sensitive client/money/credit/message context must stay blocked from paid AI unless Brandon deliberately changes `FUNDZ_AI_PAID_ALLOW_SENSITIVE=true`.
6. If Brandon reports that Daily Board / What's Next replies still do not arrive by iMessage, inspect the Messages send path separately. The fallback now caps retries, but recent sends failed with `imsg rpc exited (code 1)`.
4. Keep the No Browser Without Queue Row rule: every manual browser action needs a Work Queue row with owner, due date, next step, status, proof required, and evidence/proof location.
5. Refresh the shared Google Sheet when the queue changes materially: regenerate `data/local/command-center/fundz-work-queue-google-sheet-import.csv`, import/sync it, and update the `Daily Board` tab. If Brandon wants the new board in the shared workbook too, import `data/local/command-center/fundz-client-communication-control-board.csv` as a `Communication Control Board` tab.
6. Use Governor's safe-fix report before sending anything. Safe fixes can mark Failed, Proof Needed, Blocked, missing owner/due/next-step/proof, stale rows, duplicates, and alerts. Unsafe actions still need Brandon approval.
7. Review `data/local/command-center/fundz-personal-phone-needs-reply-triage.md` before adding any personal-phone rows to the shared Work Queue. Current triage says 2 rows are false-positive/no-company-action and 1 Travis Vance historical-client phone match needs Brandon decision. Short-code security-code Messages are now excluded before triage. Use `data/local/command-center/fundz-personal-phone-work-queue-candidates.csv` only if Brandon approves adding that sanitized row. Do not upload personal-phone message content to Google Sheets or Slack without fresh Brandon approval.
8. Run `make intake-governor-visual` after phone import, daily-board generation, or any major intake change. Review `data/local/command-center/fundz-intake-governor-dashboard.html` or `data/local/command-center/fundz-intake-governor.md`; current output has 1 Travis Vance approval-gated candidate, 0 auto-create candidates, and 10 compressed alerts.
9. Run `make phone-app-intake` after adding approved phone-app exports to `data/local/phone-app-imports/` or after refreshing Messages. Review `data/local/command-center/fundz-phone-app-intake-dashboard.html`; current output has 19 intake rows, 8 revenue/money signals, 1 risk signal, and 3 approval-needed items. Do not import personal banking, credentials, family, medical, or private content.
10. If Brandon wants the shorter new-lead signup SMS applied live, update the second GHL/HighLevel conversation message to: "Nice to meet you, {first_name}! To get started, please pull your 3-bureau credit report here: https://biz.afundsolution.com/apply-now" plus "It's $1 and takes about 5 minutes. Once you finish the signup and identity check, reply DONE and I'll send your scheduling calendar." Then add a 6-minute wait with a DONE-reply guard. If no `DONE` reply was received, send: "Just checking in, {first_name}. When you finish the quick report signup, reply DONE so I can send your scheduling calendar. Here's the link again: https://biz.afundsolution.com/apply-now". Test with one internal contact.
2. Continue the approved AutoFox member experience implementation by opening `data/local/command-center/fundz-autofox-member-experience-system.md` and `data/local/command-center/fundz-autofox-credit-tips-round1-10.csv`.
3. Brandon needs to log back into DF/Pulse in the in-app browser before live DF edits can continue. The browser returned to the login page after the first credit-tip delayed-step save failed.
4. Before adding all credit tips, retest one controlled delayed step save in DF. The failed attempt used `Start = Delay`, `Interval Type = Days`, and `Interval Value = 3` in Round 1, and DF returned `Something went wrong`. Receipt: `data/local/semi-autonomous/receipts/autofox-credit-tip-delay-save-attempt-20260505.md`.
5. In DF/Pulse, add the 20 credit-tip messages as `Mobile App SMS` actions across Round 1 through Round 10 sent campaigns only after the controlled delayed-step save succeeds. Use 3 days after round sent for the first tip and 10 days after round sent for the second tip.
6. Use `data/local/command-center/fundz-autofox-owner-review-actions.md` and `.csv` to add owner-review/internal task actions for billing issue, app SMS failed, no app login, no import, no response, duplicate messaging, stale round, and high-touch confusion. Use member-facing holding copy only when appropriate.
7. Verify Round 5 through Round 10 score-update AutoFoxes have matching Mobile App SMS wherever regular SMS exists.
8. Run one controlled safe-profile test before broad use and save DF activity-history/app-visibility proof.
1. Run `make command-center` at the start of the next work block and review `data/local/command-center/fundz-command-center.md`.
2. Review `data/local/command-center/fundz-missing-steps-recheck.md`; latest recheck shows 5 blocked items, 3 review items, and 2 pass items. The Erika app-communication pilot is review/pending app visibility proof, not blocked for missing assignment proof.
3. Review `data/local/command-center/fundz-pilot-status.md`; the pilot has provider receipts for all five app/SMS and email sends but still needs app/portal visibility confirmation and reply monitoring.
4. Review `data/local/command-center/fundz-pre-send-release-checklist.md` before any live broad outreach.
5. Use the contact ledger to work the highest-priority owner-review and no-recent-contact exceptions before broad outreach.
6. Review `data/local/command-center/fundz-owner-review-queue.csv`, `data/local/command-center/fundz-no-recent-contact-exceptions.csv`, and `data/local/command-center/fundz-next-safe-batch-candidates.csv` for work-list handoff.
7. Review `data/local/command-center/fundz-owner-decision-packet.md`; current decision grouping is 50 onboarding/setup follow-ups, 22 billing-review-before-outreach decisions, and 7 import/round confirmation decisions.
8. Review `data/local/command-center/fundz-owner-review-packet.md`; current raw grouping is 22 billing attention, 7 missing next import, and 50 onboarding/setup.
9. Review `data/local/command-center/fundz-gap-closure-plan.md` and `data/local/command-center/fundz-no-approval-work-queue.csv` whenever live/client/cloud tasks are blocked.
10. Review `data/local/scorefusion-billing-dashboard/billing-risk-queue.csv` before any billing-warning campaign changes.
11. Use the `Next Safe Batch Candidates` section or `--batch-preset tiny_pilot` to prepare the next approved preview batch, not a live send.
12. Keep the live-send guard in place: pilot/batch live sends are blocked on weekends and outside 9 AM - 9 PM local time unless Brandon explicitly approves an override and `FUNDZ_ALLOW_AFTER_HOURS_SENDS=true` is set for that action window.
13. Confirm the five Credit Tracker/app pilot messages are visible in Credit Tracker/HighLevel conversation history.
14. Confirm the five email companion messages are visible in HighLevel history.
15. Monitor replies from Anitra Thomas, Ashley Stancil, Brenda Taylor, Deja Eaton, and Jasmine Neeley.
16. HighLevel inbox preview access is currently working. Continue using preview/dry-run polling for intake verification unless Brandon explicitly approves live replies.
17. Keep `make highlevel-inbox-workaround` available for exported/copied business-only conversation rows if API access fails again.
17. Erika's DF App SMS/App Message visibility is confirmed in the admin `Messages` tab: two Workflow `App Message` rows are marked `Sent`, and the profile shows `Installed 05/04/26` / `Logged In`. Direct client-side Credit Tracker app confirmation is optional additional proof, not a blocker for the admin-side proof gate.
18. Decide how to handle clients already inside old running workflows. Fresh AutoFox Mobile App SMS sends work, but Erika's retro-added Round 1 `App SMS Sent` actions still show `In-Progress`.
19. Review Erika's app-communication redirect pilot proof before any expansion. DF activity history shows Mobile App SMS success and Email success; the old regular SMS failed as expected. The regular SMS action is paused in the campaign template because DF did not delete it after confirmation.
20. Review `data/local/command-center/fundz-app-main-communication-rollout-plan.md`. The clean campaign `FUNDz App Main Communication Notice - App Email Only` (`autofox_id=1638487`) is active and has Mobile App SMS plus Email only. Henry Fisher Sr. is the current verified Installed / Logged In candidate; Bianca Alexander and Don Dupre were checked and are not eligible yet because they only show invitation-sent app status.
21. Owner-review approvals are complete for the current 79-client queue: 69 approved and 10 held. The approved rollout subset exists at `data/local/command-center/fundz-approved-app-email-send-roster-20260505.csv`.
22. Review `data/local/semi-autonomous/receipts/download-mobile-app-sequence-send-log-20260505.csv` before any follow-up. The existing `Download Mobile App` sequence has been sent/confirmed for all 180 active-client roster IDs: 11 newly assigned, 169 already present/assigned, and 0 unresolved failures.
23. Before continuing with the clean app/email communication campaign, resolve the Anthony Williams clean-campaign result: `App SMS Sent` failed. Anthony's app invitation email was sent and app status changed to `Invitation Sent On 05/05/26`, but Mobile App SMS remained failed while Email completed. Confirm whether Mobile App SMS requires client app activation, or get Brandon's explicit approval for an email-only/app-invite fallback.
23. Use the troubleshooting finding before continuing clean-campaign sends: Mobile App SMS works for Erika with `Installed` / `Logged In` app status and fails for Anthony with only `Invitation Sent`. Recommended next decision is app-invite-first rollout, email-only fallback, or waiting for app install/login.
24. GOVERNOR should watch this rollout through `data/local/command-center/fundz-governor-watch-manifest-20260505.md` and escalate if broad clean-campaign assignment resumes while `App SMS Sent` is still failing.
22. If Erika/Brandon confirm app/portal visibility, decide whether to use fresh assignment, step restart, or the clean dedicated app/email-only campaign for active clients who missed retro-added messages. Do not disable/delete old regular SMS actions without Brandon's action-time approval.
23. If Brandon approves the next test explicitly, assign the clean campaign to Henry Fisher Sr. only, verify Mobile App SMS and Email success plus app visibility, then prepare a tiny 5-10 client batch from the safe candidate list, not a broad send.
24. Do not send the clean campaign to all 180 active clients in one pass. Exclude owner-review clients, the no-recent-contact exception, billing-risk clients, duplicate-risk clients, and any DND/opt-out contacts until reviewed.
25. Round 1 through Round 10 sent campaigns now have Mobile App SMS coverage for known regular SMS spots. Repeat the SMS-to-Mobile-App-SMS migration for any other active client AutoFox sequences outside the verified sent campaigns that still rely on regular SMS. Use `assistant/df-mobile-app-sms-migration.md` as the click-by-click guide.
26. Keep email actions in the same sequence steps so email and mobile-app message go out together.
27. Build the next outreach batch from the high-touch time-in-system cadence in `assistant/fundz-routine-messaging-plan.md`, using Credit Tracker/app/portal trigger plus email together.
28. Review the pilot outcome before sending the next batch; do not expand until the pilot is clean.
29. Review the latest AutoFox audit failures, duplicate candidates, and after-hours rows before any broad resend or workflow expansion.
30. Use `outputs/autofox-audit/fundz-autofox-message-audit-birds-eye-view.xlsx` when Brandon needs the AutoFox bird's-eye message view. If a complete day-by-day SMS history is required, export a richer DF/Pulse SMS activity report that includes sent date, message body, workflow/campaign, and status because the current SMS export does not expose those fields.
31. Use `outputs/autofox-audit/fundz-download-mobile-app-readiness-buckets.xlsx` to work the active-client app-readiness buckets. Next operational step: verify DF app status for the 178 unknown clients, or choose email/app-invite follow-up instead of Mobile App SMS until each client shows Installed / Logged In.
32. For Brandon's May 7 revenue goal, open `outputs/revenue-sprint/fundz-2000-tomorrow-revenue-sprint.xlsx` first thing. Work the `Top Closers` tab before admin tasks, use the scripts in the workbook, and track actual collected cash in the dashboard. Do not use automated broad SMS for the sprint.
30. Round 1-4 score-update Mobile App SMS migration is complete and verified. Proof: `data/local/semi-autonomous/receipts/round1-4-score-update-mobile-app-sms-added-20260505.png`.
30. Round 7-10 sent-campaign Mobile App SMS migration is complete and verified for Steps 1 and 3. Proof screenshots: `data/local/semi-autonomous/receipts/round7-sent-mobile-app-sms-added-20260505.png`, `round8-sent-mobile-app-sms-added-20260505.png`, `round9-sent-mobile-app-sms-added-20260505.png`, and `round10-sent-mobile-app-sms-added-20260505.png`.
31. Cloudflare domain/cert is complete. The permanent tunnel is `fundz-credit-tracker`, and the stable public health URL is `https://fundz.afundsolution.com/health`.
32. The signed test-only webhook probe is clean. Before wiring the webhook live, repeat `make webhook-probe` after any bridge/tunnel restart or payload-template change.
33. Put the final webhook URL `https://fundz.afundsolution.com/credit-tracker/webhook` into Credit Tracker/AutoFox/DisputeFox only after Brandon approves the live wiring step.
34. Keep `fundz-bridge` and `fundz-tunnel` running, then convert them to a LaunchAgent/service if Brandon wants always-on startup behavior after reboots.
35. Watch `logs/credit-tracker-bridge.jsonl` and `logs/cloudflared-fundz.out` after the first real webhook event.
36. Keep GitHub branch protection verified after major workflow changes; `main` currently requires both `memory-check` and `python-tests`.
37. Optional future cleanup: add a real Supabase/Postgres connection string to `.env.local` as `FUNDZ_MEMORY_DATABASE_URL` or `SUPABASE_DB_URL` so future live-memory syncs can run by command instead of dashboard SQL chunks.
38. If a database URL is still unavailable, use `scripts/fundz_postgres_memory.py --sync-operational-state --write-dashboard-chunks data/local/supabase-dashboard-sync` and run the generated SQL chunks in order in Supabase.

## After That

- Use `make start` at the beginning of each FUNDz coding session.
- Before each handoff, update the required memory files and run `make handoff MSG="Clear commit message"` only when all local changes are ready to commit.
- Update `SYSTEM_MAP.md` with more FUNDz details as workflows stabilize.
- Keep the FUNDz Google Drive backup doc updated after major handoff changes.
- Keep the named Cloudflare tunnel running; the old quick-tunnel fallback is no longer the primary path.
- Use the HighLevel manual inbox workaround now; use the API inbox poller after the token scope is fixed for automation and redundancy.
- Build a weekly member contact ledger/report proving every active member has a recent contact, a scheduled contact, or a clear owner-review/blocker reason.
- Expand the command-center report into a weekly owner-facing summary once the first daily version is accepted.

## Blocked / Remaining

- Normal OpenClaw iMessage AI replies are still blocked by model-provider access: OpenRouter returned `402 Insufficient credits`, and the OpenAI/Codex route returned provider endpoint/DNS failure after gateway restart. The local fallback is active for owner update commands, Daily Board / What's Next, and simple local-AI owner questions.
- Paid/cloud AI for FUNDz is intentionally off by default. Enable it only for safe/non-sensitive prompts or after Brandon deliberately approves a sensitive-data policy change.
- iMessage fallback send delivery may still fail independently of the AI router; recent failed sends returned `imsg rpc exited (code 1)`.
- HighLevel API inbox poller live mode, blocked on valid conversation/message read token scope. Manual inbox workaround is available now.
- Credit Tracker mobile-app/App SMS admin-side visual confirmation for Erika is cleared in the DF `Messages` tab / `All Messages` table. DF-side fresh workflow proof is successful, and the May 6 Portal Messages `0 results` search should be ignored as wrong-surface evidence; retro-added Round 1 actions remain `In-Progress`.
- AutoFox credit tips are designed locally but not saved in DF yet; first delayed-step save returned `Something went wrong`.
- Owner-review task actions are designed locally but not saved in DF yet.

## 2026-05-07 Maintenance Cleanup Next Review

- Review the regenerated maintenance cleanup board: `data/local/maintenance-cleanup/fundz-maintenance-cleanup-board.md`.
- Review duplicates CSV (review-once queue): `data/local/maintenance-cleanup/fundz-duplicate-billing-review.csv`.
- Latest maintenance autopilot status: `data/local/maintenance-cleanup/fundz-maintenance-autopilot-status.md` (generated 2026-05-08 09:14 CDT; OK; no safety findings; approval required; live sends disabled; selected=0).
- Keep outreach approval-gated; do not enable live sends from this repo while parked inactive.
