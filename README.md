# FUNDz

## Status: Safe Local Autonomy / Sleep Mode

FUNDz is currently parked from live client operations: fun, locally autonomous,
inactive for client sends, and not sending clients. Brandon explicitly woke the
local autonomous-operator and iMessage fallback LaunchAgents on May 8, 2026.
Start with `FUNDZ_SLEEP_MODE.md` before doing any operational work. Use
`make autonomous` for safe local board/intake/maintenance refreshes, and use
`make inactive` to stop the local bridge, tunnel, poller, and iMessage fallback
when this folder needs to fully sleep again.

FUNDz is set up as a hybrid project:

- Develop locally using files under `data/local`, `data/exports`, and `logs`.
- Track code, docs, config templates, and scripts in Git.
- Keep secrets in `.env.local` or a secrets manager, never in the repository.
- Store production and user data in a managed database with automated backups.
- Generate local backup archives with `scripts/backup.sh`, then optionally sync them to remote storage with `rclone`.

## First-Time Local Setup

1. Copy `.env.example` to `.env.local`.
2. Fill in local-only values and any managed database URL you use for production.
3. Keep `.env.local` private.
4. Run `scripts/backup.sh` whenever you want a local backup archive.

## Recommended Remote Setup

Use one remote Git host for project history, such as GitHub, GitLab, or Bitbucket.

Use one managed database for production/user data, such as Supabase, Neon, AWS RDS, Google Cloud SQL, or Azure Database for PostgreSQL.

Use one remote backup destination for archives, such as Google Drive, S3, Backblaze B2, Dropbox, or another `rclone`-supported service.

See `config/hybrid-storage-policy.md` for the operating rules.

## Ask FUNDz For Updates

FUNDz now has a local assistant guide in `assistant/fundz-assistant.md`.

To give FUNDz information from Dispute Fox, add the latest Dispute Fox export to:

```text
data/dispute-fox/
```

Supported starter formats:

- `.csv`
- `.json`
- `.jsonl`

Then run:

```sh
scripts/fundz_update.py
```

The update command summarizes the latest Dispute Fox/export data, the latest local audit, what needs attention, and the next move. Dispute Fox files stay local and are ignored by Git.

## Build The FUNDz Client Brain

After pulling the richer DisputeFox reports, build one master operational state file:

```sh
scripts/fundz_operational_state.py
```

This combines the active-client export, dispute deleted/repaired report, email report, and SMS report into:

- `data/local/fundz-client-state.json`
- `data/local/fundz-client-state-summary.csv`
- `data/local/fundz-client-index.json`

The JSON file is the machine-readable client brain. The CSV is the quick review sheet with status, next import, current round, dispute counts, send counts, flags, and the recommended next action. The index is the ready-to-search name list FUNDz should check before ever saying a client record is unavailable. These outputs stay local and are ignored by Git.

To sync that client brain into live Supabase/Postgres memory, set `FUNDZ_MEMORY_DATABASE_URL` or `SUPABASE_DB_URL` in `.env.local`, then run:

```sh
scripts/fundz_postgres_memory.py --apply-schema --sync-operational-state
```

For a no-write review of the exact SQL:

```sh
scripts/fundz_postgres_memory.py --apply-schema --sync-operational-state --print-sql
```

If a direct Postgres password/connection string is not available, generate small SQL chunks for the Supabase dashboard SQL editor:

```sh
scripts/fundz_postgres_memory.py --sync-operational-state --write-dashboard-chunks data/local/supabase-dashboard-sync
```

Run the chunk files in order, then run the final `*-verify.sql` chunk and confirm the total/active counts match the local summary.

To answer a named client update directly:

```sh
scripts/fundz_update.py --client "Client Name"
```

The client lookup works for any client in the stored DisputeFox exports. It merges DisputeFox display labels like `*New` with the base client name, so active-client rows and dispute-count rows stay connected.

The webhook bridge uses this same lookup for messages like "send me an update on Brandon Jordan." If the client is found locally, FUNDz replies with the answer immediately instead of saying it will check and follow up later.

## Run The Command Center

The command center pulls together the current client brain, semi-autonomous queue, AutoFox audit, recent receipts, bridge logs, and known external blockers:

```sh
make command-center
```

It writes local, Git-ignored operator outputs:

- `data/local/command-center/fundz-command-center.md`
- `data/local/command-center/fundz-command-center.json`
- `data/local/command-center/fundz-contact-ledger.csv`
- `data/local/command-center/fundz-send-visibility-command-center.md`
- `data/local/command-center/fundz-send-ledger.csv`
- `data/local/command-center/fundz-next-send-queue.csv`
- `data/local/command-center/fundz-send-kill-switch.md`
- `data/local/command-center/fundz-pilot-status.md`
- `data/local/command-center/fundz-weekly-owner-summary.md`
- `data/local/command-center/fundz-pre-send-release-checklist.md`
- `data/local/command-center/fundz-owner-review-queue.csv`
- `data/local/command-center/fundz-no-recent-contact-exceptions.csv`
- `data/local/command-center/fundz-next-safe-batch-candidates.csv`
- `data/local/command-center/fundz-autofox-mobile-app-migration-checklist.md`
- `data/local/command-center/fundz-owner-review-packet.md`
- `data/local/command-center/fundz-owner-decision-queue.csv`
- `data/local/command-center/fundz-owner-decision-packet.md`
- `data/local/command-center/fundz-gap-closure-plan.md`
- `data/local/command-center/fundz-missing-steps-recheck.md`
- `data/local/command-center/fundz-no-approval-work-queue.csv`

Use this before expanding outreach. It shows today's top actions, owner-review clients, no-recent-contact exceptions, next safe batch candidates, pilot status, AutoFox failure/duplicate/after-hours counts, memory freshness, what changed since the last run, and the current Cloudflare/HighLevel/Credit Tracker blockers. The send visibility view shows what FUNDz has sent or attempted from local receipts/audits, the exact next queued message bodies from the current preview packet, and whether the required owner text notice has been sent at least two minutes before live send. The send kill switch blocks live client/lead sends, HighLevel live replies, DF/AutoFox campaign assignment sends, and webhook-driven client responses when `data/local/command-center/fundz-send-kill-switch.json` has `"enabled": true`. The owner decision outputs convert owner-review clients into approval choices such as billing review, import/round confirmation, onboarding follow-up, approve draft, or hold messaging. The missing-steps recheck keeps the remaining live proof, external permissions, CI, and rollout gaps visible after each refresh.

To put the Command Center on its protected domain, run:

```sh
make command-center-domain
```

This starts a local protected Command Center web server on `127.0.0.1:8797`, creates or reuses `fundz-command.afundsolution.com`, and routes it through the existing Cloudflare named tunnel. The owner URL and private token are written only to `data/local/command-center/fundz-command-center-domain.json`, which is ignored by Git. The public `/health` path is open; every dashboard page requires the owner token. `make autonomous` explicitly allows this protected Command Center server/tunnel while continuing to flag the live bridge, HighLevel poller, client sends, campaign assignments, and webhook/client-reply runtime as gated.

## Build The ScoreFusion Billing Dashboard

ScoreFusion billing reporting uses Google Drive as the shared communication layer between DisputeFox, HighLevel, FUNDz, and manual review.

Use this Drive structure:

```text
ScoreFusion Billing Tracker/
  ScoreFusion Billing Dashboard
  ScoreFusion Billing SOP
  DisputeFox Billing Exports/
  HighLevel Sync Logs/
```

Add the newest DisputeFox `Invoice Due` or `Future Billing Report` CSV export to:

```text
data/dispute-fox/
```

Then generate Drive-ready dashboard files:

```sh
scripts/scorefusion_billing_dashboard.py
```

If DisputeFox shows exact live ScoreFusion totals but a row-level billing export is not available yet, capture those totals in a JSON summary and pass it in:

```sh
scripts/scorefusion_billing_dashboard.py --live-summary data/local/scorefusion-billing-dashboard/scorefusion-live-summary-YYYYMMDD.json
```

Outputs are written locally and ignored by Git:

- `data/local/scorefusion-billing-dashboard/dashboard.csv`
- `data/local/scorefusion-billing-dashboard/client-billing-roster.csv`
- `data/local/scorefusion-billing-dashboard/disputefox-import-log.csv`
- `data/local/scorefusion-billing-dashboard/exceptions.csv`
- `data/local/scorefusion-billing-dashboard/billing-risk-queue.csv`
- `data/local/scorefusion-billing-dashboard/scorefusion-billing-dashboard.json`

Import or sync those CSVs into the Google Sheet tabs with matching names:

- `Dashboard`
- `Client Billing Roster`
- `DisputeFox Import Log`
- `Exceptions`

The active-client DisputeFox export can show who is enrolled, but it does not always include exact amount-due values. Exact owed amounts should come from the DisputeFox billing export. If no billing export is present, the dashboard can still use a live DisputeFox summary for exact dashboard totals and writes a `client_level_billing_export_needed` exception until the per-client export is added.

HighLevel remains the action system: pipeline stages, billing-warning workflows, dispute escalation, and cancellation monitoring. Google Drive remains the shared reporting and audit system. Live HighLevel field updates require authorized HighLevel API access.

### Sync ScoreFusion Fields To HighLevel

Create or verify the HighLevel contact custom fields:

```sh
python3 scripts/highlevel_scorefusion_setup.py --location-id TWntg8tCBSQQjwgPmU2I
```

Generate the standard HighLevel create/update import CSV from the shared ScoreFusion roster:

```sh
python3 scripts/highlevel_scorefusion_sync.py --location-id TWntg8tCBSQQjwgPmU2I --drive-paths --write-import-csv
```

That writes:

```text
data/G Drive/scorefusion-billing-dashboard/highlevel-scorefusion-create-update-import.csv
```

Upload that CSV in HighLevel under Contacts -> Import, choose Contacts, choose Create and update contacts, and map the `SF_...` columns to their matching contact custom fields. Direct contact API sync needs a location-level HighLevel Private Integration token with contact lookup/update scopes. If the API reports a 401 scope error, keep using the CSV import path until the token includes contact read/write access.

## Run Semi-Autonomous Mode

Semi-autonomous mode rebuilds the client brain, creates a prioritized action queue, drafts safe follow-ups, and prepares controlled pilot packets. It does not send live messages unless a single pilot send is explicitly approved.

Run one local pass:

```sh
scripts/fundz_semi_autonomous_bot.py --once
```

Outputs stay local and ignored by Git:

- `data/local/semi-autonomous/fundz-action-queue.json`
- `data/local/semi-autonomous/fundz-action-queue.md`
- `data/local/semi-autonomous/pilot-packet.json`

Prepare a dry-run pilot with a safe test contact:

```sh
scripts/fundz_semi_autonomous_bot.py --pilot-dry-run --pilot-name "Test Client" --pilot-contact-id "contact-id" --pilot-phone "+15555550123"
```

If you only have the client email/phone from DisputeFox, resolve the real HighLevel contact ID first:

```sh
scripts/fundz_semi_autonomous_bot.py --pilot-dry-run --resolve-contact --pilot-name "Test Client" --pilot-channel Email --pilot-email "client@example.com"
```

For a live pilot, use only one approved test contact and keep the message owner-reviewed. The script requires `--approved-live-send` and refuses to send while `CREDIT_TRACKER_DRY_RUN=true`.

Live pilot and batch sends also refuse to run on weekends or outside 9 AM - 9 PM local time unless `FUNDZ_ALLOW_AFTER_HOURS_SENDS=true` is set for a specific approved action window.

## Expand With A Controlled Batch

After a successful pilot, FUNDz can prepare a tiny expansion batch from the `draft_for_approval` queue. This creates previews only; it does not send.

```sh
scripts/fundz_semi_autonomous_bot.py --batch-preview --batch-size 3 --batch-channel Email
```

Batch preview presets are available:

- `safe_expansion`: draft-ready clients only.
- `tiny_pilot`: caps the preview to one client.
- `urgent_action_needed`: owner-review/action-needed preview list only.
- `long_running_stable`: monitor-list preview for stable active-dispute clients.

Example:

```sh
scripts/fundz_semi_autonomous_bot.py --batch-preview --batch-preset tiny_pilot --batch-size 5 --batch-channel Email
```

If you want the batch to be ready for live approval, resolve the real HighLevel contact IDs during preview:

```sh
scripts/fundz_semi_autonomous_bot.py --batch-preview --batch-size 3 --batch-channel Email --resolve-contact --batch-location-id "location-id"
```

Outputs stay local and ignored by Git:

- `data/local/semi-autonomous/expansion-batch-packet.json`
- `data/local/semi-autonomous/expansion-batch-preview.md`

Live expansion sends are still approval-gated and capped by `FUNDZ_BATCH_MAX_SIZE`:

```sh
scripts/fundz_semi_autonomous_bot.py --batch-live --approved-batch-send
```

Before a live pilot or batch can send to clients, FUNDz now sends Brandon an owner-only iMessage notice and blocks the client send until that notice is at least two minutes old. Configure `FUNDZ_OWNER_NOTIFY_TARGET` or `FUNDZ_OWNER_COMMAND_SENDERS`, then either let the approved live-send command send the notice and stop, or send the notice manually:

```sh
make owner-pre-send-notice
```

Each batch writes a receipt under `data/local/semi-autonomous/receipts/`. A prepared batch cannot be accidentally sent twice; prepare a new preview for every new expansion.

## Draft Credit Tracker Replies

To have FUNDz draft client-ready credit tracker replies from the newest local exports, run:

```sh
scripts/fundz_credit_tracker_replies.py
```

Drafts are written to `data/local/credit-tracker-replies/`, which is ignored by Git. Review anything marked as queued, pending, failed, errored, or dead-lettered before sending it to a client.

## Audit AutoFox Sends

To have FUNDz audit what AutoFox is sending, export AutoFox/DisputeFox outbound activity into:

```text
data/exports/
```

Use CSV, JSON, or JSONL when possible. The best export includes sent SMS/email/action history with:

- sent time
- recipient or contact ID
- client/case ID
- channel
- workflow/campaign/template/action name
- message body
- send status
- failure reason, if any

Then run:

```sh
scripts/fundz_autofox_audit.py
```

Audit reports are written locally to `data/local/autofox-audits/`. Local bridge logs can show what FUNDz sent through this project, but a full AutoFox platform audit needs the AutoFox/DisputeFox outbound export or API data.

## Auto-Respond In Credit Tracker

FUNDz can run a local webhook bridge that receives Credit Tracker messages and sends a reply back through the configured outbound API.

1. Add the Credit Tracker/API values to `.env.local`. Use a HighLevel Private Integration token created at the target sub-account/location level, not an agency-level token.
   Include `CREDIT_TRACKER_LOCATION_ID` so FUNDz can resolve DisputeFox contacts to real HighLevel contact IDs.
2. Keep `CREDIT_TRACKER_DRY_RUN=true` for the first test.
3. Start the bridge:

```sh
scripts/fundz_credit_tracker_bridge.py
```

4. Point the Credit Tracker webhook to:

```text
http://YOUR_PUBLIC_BRIDGE_URL/credit-tracker/webhook
```

For local testing, use a tunnel such as ngrok or Cloudflare Tunnel in front of `http://127.0.0.1:8787`.

The bridge writes private runtime logs to `logs/credit-tracker-bridge.jsonl` and dedupes webhook events in `data/local/credit-tracker-bridge/seen-events.txt`. Both locations are ignored by Git.

Before turning dry-run off, confirm the outbound API expects the JSON shape in `CREDIT_TRACKER_OUTBOUND_TEMPLATE`. If the provider needs different field names, edit that template in `.env.local`.

If LeadConnector blocks Python's default network signature, keep `CREDIT_TRACKER_HTTP_TRANSPORT=auto`. FUNDz will try the normal Python client first, then retry the same failed request once through a local `curl` transport when the provider returns a Cloudflare browser-signature block. Secrets are passed through temporary local config files, not shell command text.

The bridge now skips auto-replies when the payload is missing a `contactId`, the contact is marked do-not-disturb, or the channel requires a valid phone/email and the payload does not provide one.

Before wiring the public webhook into Credit Tracker/AutoFox, run a signed test-only probe. It verifies Cloudflare, the shared secret, and payload handling without sending a client-facing reply:

```sh
make webhook-probe
```

### HighLevel Inbox Fallback

If Cloudflare or the Credit Tracker webhook is not stable, FUNDz can poll HighLevel conversations directly. This lets inbound client texts reach FUNDz without a public tunnel.

Preview mode, no sends:

```sh
scripts/fundz_highlevel_inbox_poller.py --once --limit 5
```

Daemon mode:

```sh
scripts/fundz_highlevel_poller_start.sh
```

Live replies require all of these:

- `CREDIT_TRACKER_DRY_RUN=false`
- `FUNDZ_HIGHLEVEL_POLLER_LIVE=true`
- a HighLevel token with conversation-read and message-send scopes

If the poller reports `The token is not authorized for this scope`, update the HighLevel Private Integration scopes to include conversation/message read access, then rerun the preview command.

If HighLevel API permissions are blocked, use the manual inbox workaround. Export/copy business-only HighLevel conversation rows to `data/local/highlevel-inbox-manual-imports/` as CSV, JSON, TXT, or Markdown, then run:

```sh
make highlevel-inbox-workaround
```

This writes a local classified queue at `data/local/highlevel-inbox-poller/manual-inbox-workaround.csv` and `.md`. It does not send replies.

To diagnose a real webhook payload before enabling live sends:

```sh
scripts/fundz_credit_tracker_diagnose.py /path/to/payload.json
```

To resolve a client email or phone into the real HighLevel contact ID before a pilot:

```sh
scripts/fundz_resolve_highlevel_contact.py --email "client@example.com" --save
```

## Run The Autonomy Loop

FUNDz now has a local PR-gated self-healing loop for the Credit Tracker bridge. It reviews bridge logs, quarantines unsafe/failing events with redacted payloads, and writes improvement proposals for owner review.

Run the full safe local autonomous operator:

```sh
make autonomous
```

This refreshes the daily board, maintenance cleanup, intake governor, phone-app intake, autonomy proposals, and tests while forcing dry-run/no-live-send child settings. It writes:

- `data/local/autonomy/fundz-autonomous-operator-status.md`
- `data/local/autonomy/fundz-autonomous-operator-status.json`
- `data/local/autonomy/fundz-autonomous-operator.jsonl`

It does not start the bridge, HighLevel poller, browser workflows, campaign assignments, or client sends. Per Brandon's May 8 wake request, `make autonomous` allows the owner-command iMessage fallback LaunchAgent and the protected Command Center domain server/tunnel to be enabled without treating those as unsafe findings. The client-facing bridge, live HighLevel replies, DF/AutoFox edits, webhook wiring, and sends remain gated. To run the operator as a watcher, set `FUNDZ_AUTONOMOUS_OPERATOR_ENABLED=true` locally and use:

```sh
make autonomous-watch
```

Run one review:

```sh
scripts/fundz_autonomy_daemon.py --once
```

Run continuously after setting `FUNDZ_AUTONOMY_ENABLED=true` in `.env.local`:

```sh
scripts/fundz_autonomy_daemon.py --watch
```

Runtime outputs stay local and ignored by Git:

- `data/local/autonomy/quarantine/`
- `data/local/autonomy/proposals/`
- `data/local/autonomy/autonomy-events.jsonl`

The autonomy loop does not apply code changes. Keep `FUNDZ_AUTONOMY_APPLY_CODE_CHANGES=false`; proposed fixes must be reviewed before changing live behavior.

## Protected Owner Command Mode

FUNDz can now accept owner-command text, like the kind Brandon would iMessage, through a protected local command layer.

Supported safe commands:

- `FUNDz status`
- `FUNDz health check`
- `FUNDz review quarantine`
- `FUNDz run tests`
- `FUNDz prepare fix`

Approved repair commands:

- `FUNDz APPROVE fix bridge`
- `FUNDz APPROVE fix webhook`

Blocked in owner-command mode:

- bulk sends
- arbitrary code patches
- pilot/client sends

Run locally:

```sh
scripts/fundz_owner_command.py --text "FUNDz health check" --sender "+18325551234"
```

Receipts are written to `data/local/owner-command-mode/receipts/`, with the latest reply in `data/local/owner-command-mode/latest-owner-command-reply.txt`.

Set `FUNDZ_OWNER_COMMAND_SENDERS` in `.env.local` to require an owner phone allowlist. If it is empty, local CLI commands are accepted for setup/testing.

## Local-First AI Brain

FUNDz uses a three-layer privacy gate for owner questions:

1. Local FUNDz tools first, such as client updates and the Daily Board.
2. Local AI on this Mac, using Ollama when installed.
3. Paid/cloud AI only when enabled and allowed by the privacy gate.

Sensitive text that looks like client, money, credit, phone, inbox, billing, or DisputeFox/HighLevel context stays local by default. Paid AI is off by default.

Run locally:

```sh
make ai-router PROMPT="write a short generic follow-up script"
```

Useful `.env.local` settings:

```text
FUNDZ_AI_LOCAL_ENABLED=true
FUNDZ_AI_LOCAL_MODEL=llama3.2:3b
FUNDZ_AI_PAID_ENABLED=false
FUNDZ_AI_PAID_PROVIDER=openai
FUNDZ_AI_PAID_AUTO_FOR_SAFE=true
FUNDZ_AI_PAID_ALLOW_SENSITIVE=false
```

If local AI is not installed, FUNDz still handles deterministic local commands like `update on Dedrick` and `daily board`. Install Ollama and pull the configured model to make random local questions work without sending them to a cloud provider.

## Stable Cloudflare Tunnel

The quick Cloudflare URL is good for testing, but production should use a named tunnel.

1. Log in to Cloudflare on this Mac:

```sh
cloudflared tunnel login
```

2. Optional: set stable hostnames in `.env.local`:

```text
FUNDZ_TUNNEL_HOSTNAME=fundz.yourdomain.com
FUNDZ_COMMAND_CENTER_HOSTNAME=fundz-command.yourdomain.com
```

3. Create/start the named tunnel for the Credit Tracker webhook:

```sh
scripts/fundz_named_tunnel_setup.sh
```

Or create/start the protected Command Center domain plus the webhook ingress on the same named tunnel:

```sh
make command-center-domain
```

If `FUNDZ_TUNNEL_HOSTNAME` is set, the Credit Tracker webhook becomes:

```text
https://YOUR_HOSTNAME/credit-tracker/webhook
```
