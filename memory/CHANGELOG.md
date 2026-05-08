# Changelog

## 2026-05-08

### Command Center Send Visibility

- Added a Command Center send visibility board at `data/local/command-center/fundz-send-visibility-command-center.md`.
- Added a consolidated local send ledger at `data/local/command-center/fundz-send-ledger.csv` from FUNDz receipts, HighLevel reply receipts, and the latest normalized AutoFox/Credit Tracker audit.
- Added a next-send queue at `data/local/command-center/fundz-next-send-queue.csv` that shows the exact queued preview message bodies and why each row is or is not allowed to send now.
- Added a Command Center kill switch status file at `data/local/command-center/fundz-send-kill-switch.md` and local control file at `data/local/command-center/fundz-send-kill-switch.json`.
- The kill switch blocks live client/lead sends, live HighLevel replies, DF/AutoFox campaign-assignment sends, and webhook-driven client responses when enabled; local reporting and dry-run autonomy still run.
- Updated the Daily Board so an enabled kill switch is visible in the blocked line before any live send decision.
- Added test coverage for kill-switch blocking, control-file state, and next-send queue gating.

### LaunchAgent Wake

- Recreated `~/Library/LaunchAgents/com.afundsolution.fundz-autonomous-operator.plist` after Brandon explicitly requested both FUNDz LaunchAgents enabled.
- Enabled `com.afundsolution.fundz-autonomous-operator` and `com.afundsolution.fundz-imessage-fallback`; `launchctl print-disabled` now reports both enabled.
- The autonomous LaunchAgent runs hourly with dry-run/no-live-send environment settings and `FUNDZ_ALLOW_IMESSAGE_FALLBACK_LAUNCHAGENT=true`.
- The iMessage fallback LaunchAgent runs every 30 seconds in live owner-command mode.
- Updated `scripts/fundz_autonomous_operator.py` and `Makefile` so an explicitly allowed iMessage fallback LaunchAgent does not create a false unsafe finding, while live sends, client edits, campaign assignments, and webhook wiring remain gated.
- Added test coverage for the explicit fallback LaunchAgent allow setting.
- Verified `make autonomous`: passed 6/6 operator steps with no safety findings and maintenance autopilot 7/7.
- Verified `python3 -m unittest tests.test_fundz_autonomous_operator -q`: passed 4 tests.
- Verified `make test`: passed 184 tests.

### Safe Local Autonomy

- Added `scripts/fundz_autonomous_operator.py` as the single safe autonomy entrypoint.
- Added `make autonomous` for one local autonomous pass and `make autonomous-watch` for an explicitly enabled local watcher.
- The autonomous operator runs bridge/autonomy review, maintenance autopilot, intake governor, intake dashboard, phone-app intake, command center, and tests with child settings forced to dry-run/no-live-send mode.
- Added `data/local/autonomy/fundz-autonomous-operator-status.md`, `.json`, and `.jsonl` as the local status outputs.
- Updated `.env.example`, `README.md`, `FUNDZ_SLEEP_MODE.md`, and `assistant/fundz-assistant.md` to document safe local autonomy.
- Added `tests/test_fundz_autonomous_operator.py`.
- Ran `python3 -m unittest tests.test_fundz_autonomous_operator -q`: passed 3 tests.
- Ran `make inactive` after finding the iMessage fallback LaunchAgent enabled but not running; the fallback LaunchAgent is disabled again.
- Ran `TODAY=2026-05-08 make autonomous`: passed 6/6 operator steps, had no safety findings, and kept runtime quiet. Maintenance autopilot passed 7/7 including tests.
- No commit was created because the worktree still contains many unrelated modified/untracked FUNDz changes.

### Publish + Recurring Autonomy

- Direct push to protected `main` was rejected as expected by branch protection.
- Pushed `codex/fundz-safe-autonomy-operating-system` and opened PR #1.
- Updated branch protection so `main` requires both `memory-check` and `python-tests`.
- Fixed CI-only SMS pilot dry-run payload shape by adding an explicit HighLevel-safe pilot SMS template with `contactId`.
- Merged PR #1 after both required GitHub checks passed and synced local `main`.
- Created hourly Codex automation `fundz-safe-autonomous-operator` to run the safe operator in this workspace.
- Verified HighLevel inbox preview mode returned status 200, fetched 5, handled 2, and sent 0.
- Generated Supabase dashboard SQL chunks under `data/local/supabase-dashboard-sync` because no local database URL is configured.
- Tried a macOS LaunchAgent for safe autonomy, then removed it because launchd cannot access this Desktop workspace without extra macOS privacy access.

## 2026-05-07

### Sleep Mode

- Added `FUNDZ_SLEEP_MODE.md` so the folder is visibly marked as fun, inactive, and not sending.
- Added `scripts/fundz_inactive.sh` and `make inactive` to stop local runtime sessions and the FUNDz iMessage fallback LaunchAgent.
- Ran `make inactive`; it stopped `fundz-bridge` and `fundz-tunnel`, found `fundz-highlevel-poller` already stopped, disabled `com.afundsolution.fundz-imessage-fallback`, and wrote `data/local/command-center/fundz-inactive-receipt.md`.
- Verified no `screen` sessions remain, the fallback LaunchAgent is disabled/unloaded, and no matching bridge/tunnel/poller/fallback processes are running.
- Updated `README.md`, `memory/HANDOFF.md`, `memory/CURRENT_STATUS.md`, and `memory/NEXT_STEPS.md` to make the inactive posture clear.
- Verified `sh -n scripts/fundz_inactive.sh`, `sh scripts/check-memory.sh`, and `make test` all passed; `make test` ran 139 tests.
- No commit was created because the worktree already contains many unrelated modified/untracked FUNDz changes.

### Maintenance Cleanup Autopilot

- Ran `python3 scripts/fundz_maintenance_autopilot.py --today 2026-05-07 --run-tests` at 2026-05-07 22:02 CDT.
- Result: OK (7/7 steps), no safety findings; rollout packet remained approval-gated (`approval_required=true`, `live_send_allowed=false`, `selected=0`).
- Summary counts: billing rows 195, unique clients 184, archived/excluded 7, bounced routes 1, duplicate-review 57.

## 2026-05-06

### Webhook Probe Hardening

- Hardened Credit Tracker bridge event logging so a macOS log-file permission error cannot crash webhook request handling or create Cloudflare `502` responses.
- Hardened the HighLevel inbox poller log writer the same way.
- Updated protected owner-command bridge restart and HighLevel poller startup scripts to use stable `/usr/bin/python3` by default instead of the broken Homebrew Python on this Mac.
- Restarted `fundz-bridge`; verified local health at `http://127.0.0.1:8787/health`.
- Verified public Cloudflare health at `https://fundz.afundsolution.com/health`.
- Re-ran `make webhook-probe`: the provider-shaped, signed, `fundz_test_only=true` POST returned HTTP `200`, `test_only: true`, and `would_reply: true` without sending a client-facing message.
- Re-ran the HighLevel inbox poller; it still returns HTTP `401`, so the remaining fix is to log into HighLevel and update the Private Integration conversation/message read permissions.
- Verified `make test`: 118 tests passed.
- After `View Conversations - conversations.readonly` was added in HighLevel, the inbox poller returned HTTP `200`, fetched 5 conversations, preview-handled 1 real inbound reply, and ignored 4 empty-body conversations without sending.
- Tightened the poller so empty-body conversations no longer enter `classified-replies.jsonl`, added message-ID dedupe for repeated preview runs, and cleaned 4 old empty-body rows from the local reply queue.
- Added HighLevel reply intake rows to the generated Work Queue. Erika Jordan's score-change question now appears as a `Proof Needed` HighLevel `Client Reply` row requiring Credit Tracker/DisputeFox/report proof before any response.
- Fixed the command-center HighLevel blocker check so a successful latest poll clears stale older `401` failures.
- Regenerated `make daily-board`; HighLevel is no longer the top blocker. The current next action is app/portal visibility proof.
- Verified `make test`: 122 tests passed.
- Verified Erika Jordan's score/report evidence from local DisputeFox/FUNDz records before replying: status `In Dispute`, stage `Round 1 Sent (04/17/26)`, next import `18 Days`, 38 items in dispute, 0 deleted, and 0 repaired in the latest local deleted/repaired report.
- Sent one narrow HighLevel SMS reply to Erika with that precise evidence; HighLevel accepted it with HTTP `201`.
- Saved a local reply receipt at `data/local/highlevel-inbox-poller/reply-receipts.jsonl` and marked the inbound message seen.
- Updated the command-center Work Queue integration so sent HighLevel replies attach the receipt and show `Sent` instead of staying `Proof Needed`.
- Re-ran the inbox poller after sending; it fetched 5, handled 0, previewed 0, and sent 0.
- Verified `make test`: 123 tests passed.

### AutoFox Local Recheck

- Refreshed `make daily-board` and corrected the generated missing-steps recheck so the completed Erika one-member app-communication pilot is no longer hardcoded as blocked when proof exists.
- `data/local/command-center/fundz-missing-steps-recheck.md` now shows 5 blocked, 3 review, and 2 pass items; the app-communication pilot is `review` pending app/portal visibility proof.
- Updated the Cloudflare recheck next step so the verified named tunnel/webhook probe are treated as complete local infrastructure, with live webhook wiring still approval-gated.
- Updated `data/local/command-center/fundz-app-main-communication-rollout-plan.md` to record Anthony Williams's clean-campaign App SMS failure and the current `Installed` / `Logged In` Mobile App SMS gate.
- Captured Erika's DF app-readiness proof: `Installed 05/04/26` and `Logged In`, with screenshot at `data/local/semi-autonomous/receipts/erika-df-app-status-installed-logged-in-proof-20260506.png`.
- Checked Portal Messages history for `Erika Jordan`, which returned `0 results`, then corrected the interpretation after Brandon clarified the expected surface was App SMS/Mobile App SMS rather than Portal Messages. The portal result is wrong-surface evidence only and does not count as an App SMS failure.
- Captured the correct Erika App SMS/App Message visibility proof in DF `Messages` / `Communications Center` / `All Messages`: two Workflow `App Message` rows are marked `Sent`, with `Installed 05/04/26` and `Logged In` visible on the same profile.
- Saved proof screenshot `data/local/semi-autonomous/receipts/erika-app-message-history-sent-proof-20260506.png` and receipt note `data/local/semi-autonomous/receipts/erika-app-message-history-sent-proof-20260506.md`.
- Performed a read-only DF/Pulse candidate check for the next one-client clean-campaign test. Bianca Alexander and Don Dupre were not eligible because they only showed invitation-sent app status. Henry Fisher Sr. was verified as eligible with `Installed 07/30/25` and `Logged In`; saved proof screenshot `data/local/semi-autonomous/receipts/henry-fisher-app-status-installed-logged-in-proof-20260506.png` and receipt note `data/local/semi-autonomous/receipts/henry-fisher-installed-logged-in-readiness-proof-20260506.md`. No AutoFox assignment, send, or client edit was performed.
- Updated `scripts/fundz_command_center.py` so the Erika App Message receipt clears the narrow app-visibility proof and one-member app-communication pilot checks while broad outreach remains blocked.
- Added focused test coverage for the App Message visibility receipt and broad-rollout blocking behavior.
- No live DF/AutoFox browser action or client send was performed.
- Verified `python3 -m unittest tests.test_fundz_command_center -q`: 28 tests passed.
- Regenerated `make daily-board`; missing-steps recheck is now 5 pass, 3 review, 2 blocked, with broad outreach still blocked.
- Verified `make test`: 124 tests passed.
- Verified `sh scripts/check-memory.sh`: passed.

### Local-First AI Brain

- Added `scripts/fundz_ai_router.py`, a local-first AI router for FUNDz owner questions.
- Routing order is local deterministic FUNDz tools first, local Ollama AI second, and paid/cloud AI only when enabled and allowed by the privacy gate.
- Paid AI is disabled by default. Sensitive client, money, credit, phone, email, inbox, payment, or dispute prompts are blocked from paid AI by default, even if the prompt says to approve paid AI.
- Added `tests/test_fundz_ai_router.py`, `make ai-router`, README guidance, and `.env.example` settings for local-first and paid-AI policy.
- Installed and started Ollama locally with Homebrew and pulled `llama3.2:3b`.
- Verified a generic prompt routes to local Ollama and a sensitive client/credit-style prompt still stays local when `--allow-paid` is passed.
- Connected `scripts/fundz_imessage_fallback.py` to local Daily Board / What's Next tools and the AI router for owner-allowlisted free-form questions.
- Moved the iMessage fallback sender allowlist check before tools or AI are invoked, so non-owner messages cannot trigger local tools or model calls.
- Added a retry cap and compact error storage for iMessage fallback send failures.
- Verified `python3 -m py_compile scripts/fundz_ai_router.py scripts/fundz_imessage_fallback.py`: passed.
- Verified `python3 -m unittest tests.test_fundz_ai_router tests.test_fundz_imessage_fallback -q`: 16 tests passed.
- Verified `make test`: 117 tests passed.

### iMessage / Messages Intake Safety

- Tightened the Mac Messages personal-phone importer so unknown keyword-only inbound rows are `Review` instead of `Needs Reply`; known client phone/name matches still become `Needs Reply`.
- Added a short-code security-code filter so private verification-code texts are excluded before local queue output.
- Updated Phone App Intake so unknown keyword-only inbound rows stay review/approval-gated in downstream dashboards.
- Refreshed local outputs: personal-phone queue is now 18 rows, 3 inbound, and 1 true Needs Reply; Phone App Intake is now 19 rows with 3 approval-needed items.
- Updated the sanitized personal-phone triage to remove the excluded security-code row and keep only the Travis Vance approval-gated candidate.
- Verified `python3 -m unittest discover -s tests -q`: 101 tests passed.

### OpenClaw iMessage Fallback

- Diagnosed the live iMessage failure from OpenClaw FUNDz session logs and gateway logs. The bridge received Brandon's iMessage, but the model call failed because OpenRouter returned `402 Insufficient credits`.
- Backed up the OpenClaw config and switched the FUNDz model route toward `openai-codex/gpt-5.4-mini`; after gateway restart, direct testing still returned provider endpoint/DNS failure, so the normal free-form OpenClaw path remains provider-blocked.
- Added `scripts/fundz_imessage_fallback.py`, a deterministic owner-command fallback that scans failed FUNDz iMessage turns, verifies the sender against `FUNDZ_OWNER_COMMAND_SENDERS`, and answers only `/new`/reset or stored client update/status requests.
- Added `tests/test_fundz_imessage_fallback.py` and `make imessage-fallback`.
- Sent the missed Dedrick Williams update to Brandon's owner-allowlisted iMessage sender suffix `9919` at 2026-05-06 15:38 CDT.
- Installed and started `~/Library/LaunchAgents/com.afundsolution.fundz-imessage-fallback.plist` so the fallback runs every 30 seconds. Logs are `logs/fundz-imessage-fallback.out.log` and `logs/fundz-imessage-fallback.err.log`; receipts are `data/local/owner-command-mode/imessage-fallback-receipts.jsonl`.
- Verified `make test`: 107 tests passed.

### Cloudflare Named Tunnel

- Authorized Cloudflare Tunnel for `afundsolution.com` and confirmed Cloudflare saved the origin certificate at `~/.cloudflared/cert.pem`.
- Started the local Credit Tracker bridge on `127.0.0.1:8787`.
- Created permanent named tunnel `fundz-credit-tracker` with tunnel ID `db5ef353-fcb9-4556-ab84-602fa8e9661d`.
- Added Cloudflare DNS route `fundz.afundsolution.com`.
- Started detached runtime sessions `fundz-bridge` and `fundz-tunnel`.
- Verified public bridge health at `https://fundz.afundsolution.com/health`.
- Saved `FUNDZ_TUNNEL_NAME=fundz-credit-tracker` and `FUNDZ_TUNNEL_HOSTNAME=fundz.afundsolution.com` in local config.
- Regenerated the Daily Board; the next action moved from Cloudflare domain/cert to the HighLevel conversation/message read-scope blocker.
- Refreshed the shared `LOGIC + FUNDz Work Orders` Daily Board / Work Queue summary and imported a current 182-row full queue snapshot at `https://docs.google.com/spreadsheets/d/1CQuJFW2c7NHhar3Tx6Fv-ynGcUPzVatxC4OzSJ39OaY`.

### HighLevel Token Scope

- Re-ran the HighLevel inbox poller after the Cloudflare work; it still failed with HTTP `401`, confirming the Private Integration token still lacks the needed conversation/message scope.
- Opened the HighLevel sub-account Private Integrations URL for location `TWntg8tCBSQQjwgPmU2I`, but the browser is at the HighLevel login screen and needs Brandon to sign in before permissions can be changed.
- Verified the bridge reply path with `CREDIT_TRACKER_DRY_RUN=true` self-test. No client-facing message was sent.
- Kept the final webhook unwired from Credit Tracker/AutoFox pending a real provider-shaped signed POST test.
- Added a HighLevel manual inbox workaround to `scripts/fundz_highlevel_inbox_poller.py`: exported/copied business-only inbox rows from `data/local/highlevel-inbox-manual-imports/` are normalized, classified, and written to `data/local/highlevel-inbox-poller/manual-inbox-workaround.csv` and `.md`.
- Added `make highlevel-inbox-workaround`.
- Added `data/local/highlevel-inbox-manual-imports/_README.md` with the accepted import shape.
- Added a signed webhook probe mode that honors `fundz_test_only=true` / `X-FUNDZ-Test-Only: true` and returns a would-reply response without sending.
- Added `scripts/fundz_credit_tracker_webhook_probe.py` and `make webhook-probe`.
- Restarted the local bridge so test-only probe handling is active.
- Verified `make webhook-probe`: public Cloudflare POST returned HTTP `200`, `test_only: true`, and `would_reply: true`; no client-facing message was sent.
- Updated the Daily Board so the next action is the manual HighLevel inbox workaround while token scope/login remains blocked.
- Verified `make highlevel-inbox-workaround`: currently imports 0 rows because no manual HighLevel export has been dropped in yet.
- Verified `make test`: 98 tests passed.

### AutoFox Message Audit Workbook

- Built Brandon's bird's-eye AutoFox message audit workbook at `outputs/autofox-audit/fundz-autofox-message-audit-birds-eye-view.xlsx`.
- Added workbook views for `Birds Eye View`, `Day Round Method`, `All Messages`, and `Sources & Limits`.
- Grouped auditable outbound records by send day, round/stage, method, and status bucket.
- Enriched round/stage from the active-client export when client names could be matched.
- Included May 5 Mobile App SMS / Email proof rows for Erika Jordan and Anthony Williams, plus the `Download Mobile App` sequence assignment receipt.
- Documented the main source limitation in the workbook: the DF SMS export contains thousands of SMS rows but does not expose sent day, message body, workflow/campaign, or status.
- Verified the workbook by inspecting summary ranges, scanning for formula-error strings, rendering all sheets, and exporting the final `.xlsx`.
- Built a follow-up Download Mobile App readiness bucket workbook at `outputs/autofox-audit/fundz-download-mobile-app-readiness-buckets.xlsx`.
- Split the 180 active-client Download Mobile App roster into: 1 Installed / Logged In, 1 Invitation Sent / not installed, and 178 Unknown / failed / regular SMS only.
- Marked Erika Jordan as the only locally proven safe Mobile App SMS candidate and Anthony Williams as email/app-invite follow-up only because his Mobile App SMS failed while app status was invitation-only.

### Revenue Sprint

- Built the May 7, 2026 $2,000 revenue sprint workbook at `outputs/revenue-sprint/fundz-2000-tomorrow-revenue-sprint.xlsx`.
- Added `Tomorrow Dashboard`, `Top 100 Targets`, `Top Closers`, `Quick Wins`, `Review First`, `Scripts`, `Day Plan`, and `Source Notes` tabs.
- Created a quick action plan at `outputs/revenue-sprint/fundz-2000-tomorrow-revenue-sprint.md`.
- Prioritized warm FUNDz targets from owner decision, billing-risk, active-client, contact ledger, and phone-app intake sources.
- Added scripts for $1,000 action-plan, $500 restart, billing restart, $250 payment recovery, warm lead follow-up, and close/payment-link moments.
- Kept the safety rule explicit: manual call/email and approved channels only, no automated broad SMS.
- Double-checked and rebuilt the workbook so `Top Closers` starts with $1,000 opportunities and Anthony Williams is excluded from all sprint tabs due to the current operator suppression.

## 2026-05-05

### Operating System v2

- Implemented the FUNDz / Governor / LOGIC queue-first operating system locally.
- Added `make daily-board` so the day starts with exactly five operating lines: Today's Objective, Next Action, Blocked, Needs Brandon, and Proof Required.
- Extended the command center to write `fundz-daily-board.md`, `fundz-work-queue.csv`, `fundz-work-queue-google-sheet-import.csv`, `fundz-governor-safe-fixes.md`, and `fundz-governor-alerts.csv`.
- Converted current owner-review, approved, sent, failed, monitor, app-invite, proof, and blocker states into the Work Queue statuses: Hold, Needs Brandon, Approved, Sent, Proof Needed, Failed, Blocked, and Done.
- Added proof gates so broad outreach is blocked while App SMS failures, app visibility proof gaps, owner holds, or reply-monitoring/system blockers remain unresolved.
- Updated Governor into an aggressive-safe watchdog with explicit safe auto-fixes and explicit Brandon-approval-only actions.
- Added Definition of Done, No Browser Without Queue Row, One Active Objective, weekly owner summary counts, and 24-hour stale-work surfacing.
- Added tests for exact five-line daily board output, held-client gating, App SMS broad-rollout blocking, missing proof, approved rows, Governor safe fixes, and stale work alerts.
- Added the Client Communication Control Board output and CSV:
  - `data/local/command-center/fundz-client-communication-control-board.md`
  - `data/local/command-center/fundz-client-communication-control-board.csv`
- The board combines the active-client ledger, Work Queue, Brandon owner decisions, full 180 reconciliation, and known App SMS failure evidence into client-level communication readiness.
- Current board baseline: 180 active client rows, with 168 Blocked, 10 Hold, 1 Failed - fix first, and 1 Needs Brandon.
- Added tests for the communication board writer and Mobile App SMS gating while app installed/logged-in status is unproven.
- Imported the current 183-row Work Queue to native Google Sheets: `https://docs.google.com/spreadsheets/d/1M3VsIFnpVnz4Dpgz9wfLepsKLYMHr0TZSmSMUn-TOUE`.
- Added `Daily Board` and `Work Queue` tabs to the shared `LOGIC + FUNDz Work Orders` workbook.
- Updated LOGIC so Lucy, Brandon/BOSS, and Jay can ask daily-board, work-queue, client update, and dispute next-step questions through existing Slack permission gates.
- Fixed Credit Tracker bridge HTTP error-body extraction so token-refresh retry tests work against urllib HTTPError mocks.
- Verified FUNDz `make test`: 82 tests passed.
- Verified LOGIC `python3 -m unittest discover -s tests -q`: 210 tests passed.

### Personal Phone Message Queue

- Added `scripts/fundz_personal_phone_message_queue.py` and `make personal-phone-queue`.
- The importer is scoped to Brandon's approval: it exports only Mac Messages rows matching known FUNDz client names, known client phone numbers, or approved business keywords.
- Output target is `data/local/command-center/fundz-personal-phone-message-queue.csv` with contact, phone, last message, date, direction, needs reply, owner, status, next step, and source.
- Added a summary output at `data/local/command-center/fundz-personal-phone-message-queue-summary.md`.
- Added tests with a synthetic Messages database proving unrelated personal messages are excluded.
- Real local run is currently blocked by macOS privacy: `~/Library/Messages/chat.db` and the local iPhone backup folder return authorization/operation denied until Codex or the terminal app has Full Disk Access.
- After Brandon granted Full Disk Access, `make personal-phone-queue` ran successfully and wrote 19 business-message rows: 4 inbound/Needs Reply and 15 outbound/Review.
- Triaged the 4 inbound/Needs Reply rows with sanitized summaries only in `data/local/command-center/fundz-personal-phone-needs-reply-triage.md` and `.csv`.
- Recommendation from triage: move 0 rows automatically, treat 3 as no-company-action false positive/security rows, and hold 1 Travis Vance historical-client phone match for Brandon decision.
- Added a sanitized candidate row at `data/local/command-center/fundz-personal-phone-work-queue-candidates.csv` without copying the sensitive-looking message body.
- Verified FUNDz `make test`: 86 tests passed.

### Intake Governor

- Added `scripts/fundz_intake_governor.py` and `make intake-governor`.
- Intake Governor is the extra bot layer: a safe intake/control bot, not a sending bot.
- It reads Work Queue rows, Governor alerts, personal-phone triage, personal-phone candidate rows, and the Client Communication Control Board.
- It writes `data/local/command-center/fundz-intake-governor.md`, `.json`, `fundz-intake-governor-candidates.csv`, and `fundz-intake-governor-alerts.csv`.
- Current output has 1 Travis Vance approval-gated candidate, 0 safe-to-auto-create candidates, and 13 compressed alerts.
- Added tests proving personal-phone candidates require approval, false positives stay out, and outputs render correctly.
- Added `scripts/fundz_intake_governor_visual.py` and `make intake-governor-visual`.
- Generated local visual dashboard: `data/local/command-center/fundz-intake-governor-dashboard.html`.
- The dashboard shows intake sources, safety gate, Work Queue status bars, approval candidates, compressed alerts, and safety rules.
- Added dashboard rendering tests.
- Verified FUNDz `make test`: 91 tests passed.

### Phone App Intake

- Added `scripts/fundz_phone_app_intake.py` and `make phone-app-intake`.
- Implemented an approved-app registry for Messages, Phone/Voicemail/Call Recordings, Notes, Photos/Screenshots, Gmail/Mail, Calendar, Slack, and business-only payment exports.
- Phone App Intake reads business-filtered Messages, Intake Governor candidates, and approved manual exports from `data/local/phone-app-imports/`.
- It writes `data/local/command-center/fundz-phone-app-intake.md`, `.json`, `.csv`, `fundz-phone-app-intake-registry.md`, and `fundz-phone-app-intake-dashboard.html`.
- It classifies approved app signals into Money / Billing, Lead / Revenue, Risk / Retention, Client Work, Proof / Receipt, Security / Keep Private, Owner Decision, or Review.
- Current output: 20 intake rows, 8 revenue/money signals, 1 risk signal, 3 approval-needed items, and 1 security/private no-company-action row.
- Added tests for money/risk classification, security-code privacy, source aggregation, and output rendering.
- Verified FUNDz `make test`: 95 tests passed.

### Work Queue Suppression

- Added `data/local/command-center/fundz-work-queue-suppressions.csv`.
- Added queue suppression support to the command center so Brandon can suppress a client from the active next-action path without deleting evidence.
- Recorded Brandon's instruction to ignore Anthony Williams for the current operating cycle.
- Regenerated the Daily Board; next action now points to the Cloudflare tunnel/domain/certificate blocker instead of Anthony.
- Verified FUNDz `make test`: 96 tests passed.

### Copy

- Prepared shorter replacement copy for the second new-lead signup SMS shown in Brandon's screenshot.
- Added the requested 6-minute no-DONE reminder copy with the signup link repeated.
- Searched local FUNDz and nearby Trade Line App files; the exact message source was not found.
- Tried HighLevel connector search for the signup/apply-now workflow, but access is blocked by HighLevel auth `401`.
- No live CRM workflow, send behavior, or app logic was changed.

### AutoFox App Communication Pilot

- With Brandon logged into DF/Pulse, manually assigned `FUNDz App Communication Notice - Email SMS App` to Erika Jordan from her client AutoFox tab.
- Verified the assigned workflow completed just after assignment with 3 total actions, 0 in-progress, 0 pending, and 2 completed.
- DF activity history shows `App Communication Mobile App SMS Sent Mobile App SMS` with `Success` and `App Communication Email Send Email` with `Success`.
- The regular SMS action in the same campaign failed, which matches the known old-SMS channel issue; the Mobile App SMS and Email channels succeeded.
- Saved proof screenshot: `data/local/semi-autonomous/receipts/app-communication-erika-sent-proof-20260505.png`.
- Tried to delete the regular SMS action from the app-communication campaign after Brandon requested removal. DF accepted the confirmation modal but did not remove the completed-history SMS action after refresh.
- Paused the regular SMS action instead and saved the AutoFox. The step now shows `Action Pause`, with Mobile App SMS and Email still present. Proof screenshot: `data/local/semi-autonomous/receipts/app-communication-regular-sms-paused-20260505.png`.
- Created clean manual DF AutoFox campaign `FUNDz App Main Communication Notice - App Email Only` (`autofox_id=1638487`) for controlled active-client rollout.
- Added instant Step 1 `Use Credit Tracker App for Updates` with Mobile App SMS and Email actions only. No regular SMS action is included in the clean campaign.
- Activated the clean campaign. DF now shows the campaign as `Active`, Step 1 as `In Progress / Active`, and the step action toggle as `Active`.
- Saved proof screenshot: `data/local/semi-autonomous/receipts/app-main-communication-app-email-only-ready-20260505.png`.
- Added rollout readiness note: `data/local/command-center/fundz-app-main-communication-rollout-plan.md`.
- Confirmed the clean campaign is ready for controlled assignment after fresh approval, but broad outreach to all 180 active clients is still blocked pending app visibility confirmation, reply-monitoring readiness, owner-review exclusions, and Brandon approval.
- Recorded Brandon's full 79-client owner-review decisions in `data/local/command-center/fundz-owner-approval-decisions-20260505.md` and `.csv`: 69 approved clients and 10 held clients. No live messages were sent from these approval steps.
- Built approved send roster with exact DF customer IDs at `data/local/command-center/fundz-approved-app-email-send-roster-20260505.csv`.
- Started rollout by assigning `FUNDz App Main Communication Notice - App Email Only` to Anthony Williams only. DF showed the workflow, but `App SMS Sent` failed and `Email Sent` was still in progress, so the rollout was stopped before assigning anyone else. Send log: `data/local/semi-autonomous/receipts/app-email-rollout-send-log-20260505.md`.
- Sent Anthony Williams the prebuilt Mobile App invitation email. DF returned `Success! Email sent Successfully.` and app status changed to `Invitation Sent On 05/05/26`. Recheck showed the clean-campaign email completed but `App SMS Sent` remained failed.
- Troubleshot the Mobile App SMS failure by comparing Anthony Williams to Erika Jordan. Erika is `Installed` / `Logged In` and Mobile App SMS succeeds; Anthony is only `Invitation Sent` and Mobile App SMS fails. Added `data/local/semi-autonomous/receipts/app-sms-troubleshooting-20260505.md`.
- Checked the existing `Download Mobile App` AutoFox (`autofox_id=522913`); it contains Email plus regular SMS, so it is not clean enough for broad app-invite rollout while regular SMS is unreliable.
- Added full active-client rollout reconciliation at `data/local/command-center/fundz-full-180-app-email-rollout-reconciliation-20260505.csv` after Brandon clarified he wants all 180 active clients sent after the 69 approved group.
- Updated GOVERNOR watch access/instructions in `assistant/governor.md` and added `data/local/command-center/fundz-governor-watch-manifest-20260505.md` so GOVERNOR can monitor this project, the 180-client rollout files, and the Anthony Mobile App SMS failure blocker.
- With Brandon's approval, sent/confirmed the existing `Download Mobile App` AutoFox sequence across the full 180 active-client roster.
- Final rollout receipt: `data/local/semi-autonomous/receipts/download-mobile-app-sequence-send-log-20260505.csv`.
- Final tally: 180 active clients accounted for, 11 newly assigned, 169 already present/assigned, and 0 unresolved failures. This existing sequence includes Email plus regular SMS, so the regular-SMS deliverability risk remains.
- Added matching Mobile App SMS actions to the score-update AutoFoxes for Rounds 1 through 4 wherever regular SMS exists:
  - `Client (step 05) - Round 1 Score Update` (`autofox_id=160040`)
  - `Client (step 07) - Round 2 Score Update` (`autofox_id=160042`)
  - `Client (step 09) - Round 3 Score Update` (`autofox_id=160043`)
  - `Client (step 11) - Round 4 Score Update` (`autofox_id=160056`)
- Verified all four now show Mobile App SMS in the step action list. Proof screenshot: `data/local/semi-autonomous/receipts/round1-4-score-update-mobile-app-sms-added-20260505.png`.
- Added matching Mobile App SMS actions to the sent-and-campaign AutoFoxes for Rounds 7 through 10 wherever regular SMS appears in Steps 1 and 3:
  - `Client (step 16) - Round 7 Sent & Campaign` (`autofox_id=160065`)
  - `Client (step 18) - Round 8 Sent & Campaign` (`autofox_id=160067`)
  - `Client (step 20) - Round 9 Sent & Campaign` (`autofox_id=160069`)
  - `Client (step 22) - Round 10 Sent & Campaign` (`autofox_id=160071`)
- Saved proof screenshots: `data/local/semi-autonomous/receipts/round7-sent-mobile-app-sms-added-20260505.png`, `round8-sent-mobile-app-sms-added-20260505.png`, `round9-sent-mobile-app-sms-added-20260505.png`, and `round10-sent-mobile-app-sms-added-20260505.png`.
- The old regular SMS actions remain present in Rounds 7-10; they were not disabled or deleted.

### Command Center / Outreach Safety

- Added `scripts/fundz_command_center.py`, a local command-center report that combines operational client state, the semi-autonomous queue, AutoFox audit evidence, bridge/poller logs, receipts, blockers, top actions, safe batch candidates, duplicate contact checks, and a contact cadence ledger.
- Added `make command-center`.
- Generated the first command-center outputs: `data/local/command-center/fundz-command-center.md`, `data/local/command-center/fundz-command-center.json`, and `data/local/command-center/fundz-contact-ledger.csv`.
- Extended the command center with `data/local/command-center/fundz-pilot-status.md`, `data/local/command-center/fundz-weekly-owner-summary.md`, and `data/local/command-center/fundz-pre-send-release-checklist.md`.
- Added pilot status parsing from local provider receipts. Current pilot receipt baseline: 5 of 5 app/SMS provider receipts, 5 of 5 email receipts, 0 app/portal visibility confirmations, 0 replies seen, and 5 unresolved clients because app visibility is still unconfirmed.
- Added memory freshness and "what changed since last run" sections to the command-center JSON/weekly summary.
- Current command-center baseline: 180 active clients, 79 owner-review-before-message, 1 no-recent-contact-found, action queue counts of 79 owner-review / 66 draft-for-approval / 35 monitor, and AutoFox snapshot of 5,488 outbound records, 251 failures, 99 possible duplicates, and 36 after-hours records.
- Added HighLevel inbox reply classification for `cancel`, `complaint`, `billing`, `document_request`, `question`, and `no_action`, plus a local classified reply queue at `data/local/highlevel-inbox-poller/classified-replies.jsonl`.
- Added live-send window protection to semi-autonomous pilot and batch sends: live sends now block on weekends and outside 9 AM - 9 PM local time unless `FUNDZ_ALLOW_AFTER_HOURS_SENDS=true` is explicitly set.
- Added deterministic phase-based message variation for semi-autonomous drafts, including next-round, active-dispute-with-import, active-dispute, and default review templates.
- Added action priority scores and message phase labels to the semi-autonomous action queue.
- Added batch preview presets: `safe_expansion`, `tiny_pilot`, `urgent_action_needed`, and `long_running_stable`.
- Added `do_not_send_because` explanations to batch preview items that are not ready for live approval.
- Added command-center drilldown CSVs for owner-review clients, no-recent-contact exceptions, and next safe batch candidates.
- Added `data/local/command-center/fundz-owner-review-packet.md`, grouped by billing attention, missing next import, onboarding/setup, next-round review, and generic owner review.
- Added `data/local/command-center/fundz-owner-decision-queue.csv` and `data/local/command-center/fundz-owner-decision-packet.md`, converting owner-review clients into concrete approval choices. Current decision counts: 50 onboarding/setup follow-ups, 22 billing-review-before-outreach decisions, and 7 import/round confirmation decisions.
- Added `data/local/command-center/fundz-gap-closure-plan.md`, mapping each FUNDz Power-Up backlog area to done/partial/blocked plus the remaining gap.
- Added `data/local/command-center/fundz-missing-steps-recheck.md`, a generated recheck of remaining live/external gaps. Current recheck: 7 blocked, 2 review, 1 pass.
- Added `data/local/command-center/fundz-no-approval-work-queue.csv`, listing safe local work that can continue while live/client/cloud work is blocked.
- Added `data/local/command-center/fundz-autofox-mobile-app-migration-checklist.md` so remaining AutoFox Mobile App SMS migration work has a generated checklist.
- Added `data/local/command-center/fundz-autofox-member-experience-system.md`, mapping AutoFox into Onboarding, Round Updates, Education / Credit Tips, and Problem / Owner Review lanes.
- Added `data/local/command-center/fundz-autofox-credit-tips-round1-10.csv`, with 20 Mobile App SMS credit tips scheduled two per round from Round 1 through Round 10.
- Attempted to save the first 3-day delayed credit-tip step in Round 1 (`autofox_id=160038`) with `Start = Delay`, `Interval Type = Days`, and `Interval Value = 3`. DF returned `Something went wrong`; after reload, the in-app browser returned to the DF login page.
- Saved the failed delayed-step receipt at `data/local/semi-autonomous/receipts/autofox-credit-tip-delay-save-attempt-20260505.md`.
- Added `data/local/command-center/fundz-autofox-owner-review-actions.md` and `data/local/command-center/fundz-autofox-owner-review-actions.csv`, with eight internal Problem / Owner Review task actions and member-safe holding copy where appropriate.
- Added ScoreFusion billing-risk queue generation at `data/local/scorefusion-billing-dashboard/billing-risk-queue.csv` and surfaced ScoreFusion enrolled/owed/at-risk/exception counts in the command center.
- Added an AutoFox audit guard so generated reporting files are not treated as outbound platform evidence.
- Added `make test` and `.github/workflows/tests.yml` so GitHub can run the full Python unit suite.
- Documented the command center and send-window override in `README.md` and `.env.example`.
- Added tests for command-center output, reply classification, and live-send window blocking.
- Verified `python3 scripts/fundz_semi_autonomous_bot.py --batch-preview --batch-preset tiny_pilot --batch-size 5 --batch-channel Email`: prepared a one-client preview with `send_ready: 0` because contact resolution was not requested.
- Verified `python3 scripts/scorefusion_billing_dashboard.py --today 2026-05-05`: generated Drive-ready files plus `billing-risk-queue.csv`; baseline showed 246 enrolled, 246 owed payments, $6,073.83 total amount due, and 154 exceptions.
- Verified local bridge health OK, HighLevel conversation polling still `401`, and Cloudflare named tunnel still missing origin certificate.
- Verified branch protection still requires only `memory-check`; the Python Tests workflow exists but is not yet required.
- Verified `make test`: 74 tests passed.
- Verified `sh scripts/check-memory.sh`: passed.
- Verified `python3 -m unittest discover -s tests -q`: passed, 75 tests.
- Verified `python3 -m unittest tests/test_fundz_command_center.py -q`: passed, 14 tests.

## 2026-05-04

### Live Memory / Infrastructure

- Added `db/migrations/001_live_memory.sql` for Supabase/Postgres live memory tables, indexes, and active-client view.
- Added `scripts/fundz_postgres_memory.py` to apply the live memory schema and sync the local FUNDz operational client brain into Postgres through `psql`.
- Added `tests/test_fundz_postgres_memory.py`; full test suite now includes live memory SQL generation coverage.
- Updated `.env.example`, `README.md`, and `db/README.md` with live memory connection variables and run commands.
- Added `scripts/fundz_branch_protection_check.sh` to verify GitHub branch protection status and print the current private-repo plan blocker.
- Checked GitHub branch protection/rulesets. GitHub returned `403`: private-repo branch protection requires GitHub Pro or making the repo public.
- Checked HighLevel inbox poller live readiness. HighLevel returned `401`, so the current token still cannot read conversations.
- Checked Cloudflare named tunnel readiness. `cloudflared` still cannot find `~/.cloudflared/cert.pem`, so permanent named tunnel setup remains blocked.
- Verified live memory SQL generation with `scripts/fundz_postgres_memory.py --apply-schema --sync-operational-state --print-sql`.
- Verified the live memory command fails safely without a configured database URL.
- Checked the logged-in Supabase dashboard. A Fund Solution has `afs-portal` paused and `logic-memory` active.
- Confirmed the Supabase database password/connection string is not available locally; the dashboard says the password is not viewable after creation.
- Attempted SQL editor apply path, but the editor did not reliably accept/run the large generated live-memory SQL payload through browser automation. Live apply remains blocked until Brandon provides the database connection string/password or approves a password reset/project resume.
- With Brandon approval, changed `afundsolution/fundz` from private to public on GitHub.
- Enabled branch protection on `main`, requiring the `memory-check` status check with strict checks and admin enforcement. Force pushes and branch deletions are disabled.
- Applied `db/migrations/001_live_memory.sql` to Supabase `logic-memory` through the SQL editor.
- Used Supabase's safer `Run and enable RLS` option after the dashboard warned that new tables would otherwise be created without Row Level Security.
- Supabase returned `Success. No rows returned`; the schema is live with RLS enabled.
- With Brandon's approval, synced the full FUNDz client-memory payload to Supabase `logic-memory` through SQL editor chunks because no database password/connection string was available locally.
- Replayed the dashboard chunks more slowly after the first verification was short from skipped runs.
- Verified Supabase live memory counts: 357 total client rows, 180 active client rows, 180 active-client view rows, and 1 dashboard sync snapshot marker.
- Added a repeatable Supabase dashboard SQL chunk fallback to `scripts/fundz_postgres_memory.py`, with docs in `README.md` and `db/README.md`.
- Added test coverage for dashboard chunk generation and final verification SQL.
- Rechecked live blockers: Credit Tracker bridge health is OK, branch protection is still enabled, HighLevel inbox polling still returns `401`, and Cloudflare still lacks `cert.pem`.
- Ran the approved Erika Jordan live portal trigger. HighLevel accepted the tag request with HTTP `201`, but `tagsAdded` was empty because Erika already had `fundz_portal_touch`, so a tag-added workflow may not have fired.
- Updated `scripts/fundz_autofox_portal_trigger.py` to report `newly_added` vs `already_present` and added a controlled `--force-retrigger` option for removing/re-adding the trigger tag after fresh approval.
- With Brandon approval, force re-triggered Erika by removing and re-adding `fundz_portal_touch`. HighLevel removed the tag with HTTP `200` and re-added it with HTTP `201`; the receipt reports `newly_added: true`.
- Captured Erika trigger proof in `data/local/semi-autonomous/receipts/erika-portal-trigger-proof-20260504.md`: HighLevel contact read returned HTTP `200`, the contact still has `fundz_portal_touch`, and `dateUpdated` is `2026-05-05T04:04:08.733Z`.
- Tried to capture DF/AutoFox run-history proof, but Scorexer Google sign-in failed with OAuth `Error 400: origin_mismatch`.
- Brandon logged into Pulse/DF in the Codex in-app browser. Automation could not continue from that pane because the available Computer Use tool cannot control the Codex in-app browser directly; Chrome remains blocked and Safari is not logged in.
- Attached to the Codex in-app browser with Browser Use and opened Erika Jordan's DF AutoFox tab.
- Captured DF proof that Erika's active Round 1 workflow contains `App SMS Sent` actions, but they are currently `In-Progress`, not successful/completed.
- Captured activity-history proof that email actions succeeded and regular SMS actions failed, with no `App SMS` / `Mobile App SMS` success line yet.
- Saved proof screenshots: `data/local/semi-autonomous/receipts/erika-df-autofox-status-20260505.png` and `data/local/semi-autonomous/receipts/erika-df-autofox-history-20260505.png`.
- Created a fresh DF AutoFox campaign `FUNDz Erika Mobile App SMS Test 2026-05-05` (`autofox_id=1638056`) with one instant Mobile App SMS action named `Fresh Erika Mobile App SMS Test`.
- Assigned the fresh campaign manually to Erika Jordan from her DF profile.
- Verified the fresh campaign completed successfully: DF showed `Workflow Completed`, 1 completed action, and activity history line `Fresh Erika Mobile App SMS Test Sent Mobile App SMS` with `Success`.
- Saved fresh proof screenshots: `data/local/semi-autonomous/receipts/erika-fresh-autofox-mobile-app-action-20260505.png`, `data/local/semi-autonomous/receipts/erika-fresh-autofox-assigned-20260505.png`, `data/local/semi-autonomous/receipts/erika-fresh-autofox-status-recheck-20260505.png`, `data/local/semi-autonomous/receipts/erika-fresh-autofox-mobile-app-completed-20260505.png`, and `data/local/semi-autonomous/receipts/erika-fresh-autofox-activity-history-20260505.png`.
- Created active manual DF AutoFox campaign `FUNDz App Communication Notice - Email SMS App` for current members.
- Added instant Step 1 `Use Credit Tracker App for Updates`.
- Saved regular SMS and Mobile App SMS actions telling members to communicate through the Credit Tracker app/client portal.
- Attempted the matching DF email action with subject `Please Use Your Credit Tracker App for Updates`, but DF did not save it and kept the modal open around the `To` / `Client Email` field.
- Preserved the intended email body and proof screenshots in `data/local/semi-autonomous/receipts/app-communication-notice-proof-20260505.md`.
- Saved the matching DF email action after Brandon confirmed the visible `Client Email` recipient field.
- Verified `FUNDz App Communication Notice - Email SMS App` Step 1 now shows SMS, Mobile App SMS, and Email Message Details in the same instant step.
- Saved proof screenshot: `data/local/semi-autonomous/receipts/app-communication-all-three-actions-visible-20260505.png`.

### Routine Messaging

- Added `assistant/fundz-routine-messaging-plan.md` for Credit Tracker/app-first routine member outreach.
- Captured the current baseline: 180 active members, 66 draft-ready, 35 monitor-only, and 79 requiring owner review before messaging.
- Captured the latest AutoFox audit baseline: 5,451 outbound records, 559 unique recipients, 250 failed/error records, 75 duplicate candidates, 0 risky-language records, and 14 outside-business-hour records.
- Linked the routine messaging plan from `assistant/fundz-assistant.md`.
- Updated memory handoff files with the routine outreach next step and pilot constraints.
- Prepared a preview-only five-member pilot approval sheet at `data/local/semi-autonomous/first-credit-tracker-pilot-approval.md`.
- Generated a preview batch packet/report for Anitra Thomas, Ashley Stancil, Brenda Taylor, Deja Eaton, and Jasmine Neeley. The batch is intentionally not send-ready until contact IDs are resolved.
- Updated the pilot with Brandon-approved professional patience/continued-progress wording and verified the message has no risky-language hits.
- Resolved all five pilot members to HighLevel/Credit Tracker contacts; no live messages were sent.
- Sent the approved five-member Credit Tracker/app live pilot on May 4, 2026 at 12:38 PM CDT with dry-run disabled only for the send command.
- Provider accepted all five pilot messages with HTTP `201`; sent `5`, failed/blocked `0`, skipped `0`.
- Sent the matching email companion batch for the same five members. Email sent `4`, failed `1`; Anitra Thomas failed because HighLevel returned `Contact has no email`.
- Updated `assistant/fundz-routine-messaging-plan.md` so future approved routine outreach sends Credit Tracker/app and email together, with failed-channel cleanup instead of waiting three days for the email backup.
- With Brandon approval, updated Anitra Thomas's HighLevel contact email from local state, then retried only her email companion. HighLevel accepted the contact update with HTTP `200` and accepted the email retry with HTTP `201`.
- Updated `assistant/fundz-routine-messaging-plan.md` to a high-touch, time-in-system cadence: every other business day by default, daily business-day touches during onboarding/action-needed/next-round windows, and twice-weekly minimum for long-running stable files.
- Added `scripts/fundz_autofox_portal_trigger.py` to trigger a configured AutoFox/Credit Tracker portal workflow by workflow ID or trigger tag.
- Added `assistant/autofox-credit-tracker-portal-setup.md` documenting the required AutoFox/Credit Tracker portal workflow setup.
- Confirmed the current HighLevel SMS/email sends do not prove Credit Tracker app/portal visibility; portal visibility is blocked until the AutoFox workflow ID or trigger tag is configured.
- Prepared Erika Jordan as a single-contact portal/app visibility test and generated a preview receipt; live portal trigger remains blocked until the AutoFox/Credit Tracker workflow trigger is configured.
- Sent Erika Jordan a controlled Credit Tracker/SMS and email test. Both were accepted with HTTP `201`. Attempted portal trigger live, but the script blocked because no AutoFox portal workflow ID or trigger tag is configured.
- Configured local portal trigger tag `fundz_portal_touch` and applied it live to Erika Jordan. HighLevel accepted the tag action with HTTP `201`; AutoFox/Credit Tracker portal visibility now depends on a workflow listening for that tag.
- Re-ran the Erika portal trigger test on request. HighLevel again accepted tag `fundz_portal_touch` with HTTP `201`; no SMS/email resend was performed.
- Investigated the failed portal/mobile-app visibility path. DF admin opens at `secure.scorexer.com`, but the browser is currently at the DF login screen and needs Brandon login before sequence edits can be made.
- Added `assistant/df-mobile-app-sms-migration.md` documenting the required AutoFox sequence change: copy each existing SMS body into a `Mobile App SMS` action, keep email alongside it, and remove old SMS only after the mobile-app action is saved.
- After Brandon logged into DF, updated `Client (step 02) - Client On-Boarding & Portal Login` Step 1 by adding and saving a `Mobile App SMS` action named `Agent Welcome Mobile App SMS`.
- Saved the Brandon-approved Mobile App SMS body: "Hi [FIRST-NAME], This is [COMPANY-NAME] Please Check your email for your Client Portal Login details, and some instructions on the next steps. Any questions, please let me know‼️ (346) 680-3466".
- Verified Step 1 now shows Email, SMS, and Mobile App SMS; the old regular SMS action remains active pending Brandon approval to disable/delete it.
- Updated `Client (step 04) - Round 1 Sent & Campaign` so Steps 1, 2, 3, and 4 each include a saved `Mobile App SMS` action copied from the existing SMS content.
- Verified the Round 1 workflow list shows `Mobile App SMS` under Steps 1, 2, 3, and 4; the old regular SMS actions remain active pending Brandon approval to disable/delete them.
- Updated Round 2 through Round 6 sent-and-campaign workflows so every regular SMS spot now has a matching saved `Mobile App SMS` action.
- Added 11 Round 2-6 Mobile App SMS actions total: Round 2 Steps 1-3, Round 3 Steps 1 and 4, Round 4 Steps 1 and 3, Round 5 Steps 1 and 3, and Round 6 Steps 1 and 3.
- Varied the new mobile app message content with credit education, credit monitoring payment reminders, portal/mail reminders, and soft tradeline review language. Brandon's number was standardized as `(346)680-3466`.
- Verified Round 2 through Round 6 each now show one `Mobile App SMS` action for every regular SMS step; old regular SMS actions remain active pending Brandon approval to disable/delete them.

## 2026-05-03

### Cloudflare / Credit Tracker

- Confirmed the local Credit Tracker bridge on port `8787` is healthy.
- Confirmed the current quick Cloudflare public tunnel returns bridge health OK.
- Added/staged named tunnel setup support with `scripts/fundz_named_tunnel_setup.sh`.
- Attempted Cloudflare tunnel login. The Cloudflare dashboard opened to "Authorize Cloudflare Tunnel", but no selectable domain/zone appeared, so Cloudflare did not issue the origin certificate required for a permanent named tunnel.
- Recorded the named tunnel blocker and next steps in memory files and the shareable FUNDz operational update.
- Added HighLevel inbox poller fallback so inbound client texts can be checked directly from HighLevel when Cloudflare/webhooks are unavailable.
- Added `scripts/fundz_highlevel_poller_start.sh` to run the fallback poller as a local screen daemon.
- Tested the poller in preview mode; HighLevel returned a missing-scope authorization response for conversation-read access.

### Added

- Added `AGENTS.md` to FUNDz.
- Added the `memory/` handoff scaffold.
- Added `Makefile` shortcuts for `make start`, `make memory-check`, and `make handoff`.
- Added `scripts/start-session.sh`, `scripts/check-memory.sh`, and `scripts/finish-session.sh`.
- Added `.github/workflows/memory-check.yml`.
- Created private GitHub repository `afundsolution/fundz`.
- Created Google Drive backup/reference doc: `https://docs.google.com/document/d/1LJvMBEzbjSp9ZIuRrrEgVWEFOEu7SOOM4Eh8aP7owC4/edit`.

### Changed

- Tailored core memory files to describe FUNDz instead of the Save A Token setup repo.
- Updated memory files with the FUNDz GitHub and Google Drive links.

### Tests

- `sh scripts/check-memory.sh`: passed.
- `git push -u origin main`: pushed FUNDz to GitHub.
- `gh run watch 25300657050 --repo afundsolution/fundz --exit-status`: Memory Check workflow passed.
- `make start`: printed the required reading order and startup prompt.
- Google Docs connector readback: verified the Drive doc content exists.

### Notes

- Existing FUNDz app logic was not changed for this scaffold.
- Existing uncommitted FUNDz work was already present and should not be included in the memory-system commit unless Brandon explicitly approves.
- `make handoff` commits all local changes by design; review the worktree before using it in FUNDz.

## 2026-05-07

- Ran maintenance cleanup autopilot (ScoreFusion refresh + boards + command center + rollout approval-gate verification + tests).
- Wrote status + outputs under `data/local/maintenance-cleanup/` (no live sends; approval remained required).
