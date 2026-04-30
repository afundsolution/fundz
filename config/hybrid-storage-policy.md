# FUNDz Hybrid Storage Policy

## What Lives Locally

Use local storage for development-only data:

- Temporary imports and exports.
- Local test databases.
- Local audit files.
- Debug logs.
- Scratch files used while building or testing.

Local-only paths:

- `data/local/`
- `data/exports/`
- `logs/`
- `backups/`
- `.env.local`

These are excluded from Git.

## What Lives In Git

Use Git for project assets that should be versioned:

- Source code.
- Documentation.
- Configuration templates.
- Database migrations.
- Backup and maintenance scripts.
- Non-secret examples.

Do not commit real customer data, API keys, passwords, tokens, production exports, or raw logs.

## What Lives In Managed Production Storage

Production and user data should live in a managed database or managed storage service with:

- Automated daily backups.
- Point-in-time recovery when available.
- Encryption at rest.
- TLS connections.
- Access control by role.
- A documented restore process.

Good default choices for a small FUNDz deployment are Supabase or Neon for Postgres. Larger deployments can use AWS RDS, Google Cloud SQL, or Azure Database for PostgreSQL.

## Secrets

Local secrets belong in `.env.local`.

Production secrets belong in a secrets manager, such as:

- AWS Secrets Manager.
- Google Secret Manager.
- Azure Key Vault.
- Doppler.
- 1Password Secrets Automation.

Never commit `.env.local`, API keys, database passwords, OAuth tokens, private keys, or webhook signing secrets.

## Backups

Use `scripts/backup.sh` to create a timestamped local archive.

If `RCLONE_REMOTE` is set in `.env.local`, the script will also copy the archive to the configured remote destination.

Backup checks:

- Confirm that a new archive exists after every backup run.
- Confirm that remote sync succeeds when configured.
- Test restore with `scripts/restore.sh` before relying on backups.
- Keep at least one off-machine backup.
