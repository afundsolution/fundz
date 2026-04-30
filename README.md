# FUNDz

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

## Draft Credit Tracker Replies

To have FUNDz draft client-ready credit tracker replies from the newest local exports, run:

```sh
scripts/fundz_credit_tracker_replies.py
```

Drafts are written to `data/local/credit-tracker-replies/`, which is ignored by Git. Review anything marked as queued, pending, failed, errored, or dead-lettered before sending it to a client.

## Auto-Respond In Credit Tracker

FUNDz can run a local webhook bridge that receives Credit Tracker messages and sends a reply back through the configured outbound API.

1. Add the Credit Tracker/API values to `.env.local`.
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
