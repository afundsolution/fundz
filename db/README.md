# FUNDz Database

Use this folder for database structure, not production data.

Track these in Git:

- Schema notes.
- Migration files.
- Seed files with fake/sample data only.
- Restore runbooks.

Do not track these in Git:

- Real customer records.
- Production exports.
- Database dumps.
- Credentials or connection strings.

Production/user data should live in a managed database with automated backups and point-in-time recovery when available.

## Live Memory

`db/migrations/001_live_memory.sql` creates the live FUNDz memory tables:

- `fundz_memory_snapshots`
- `fundz_client_memory`
- `fundz_memory_events`
- `fundz_active_client_memory`

To apply the schema and sync the current local operational state to Supabase or another Postgres database from the command line:

```sh
make supabase-memory-sync
```

Set one of these in `.env.local` first. The value must be a real Postgres connection string, not a Supabase API URL or API key:

- `FUNDZ_MEMORY_DATABASE_URL`
- `SUPABASE_DB_URL`
- `DATABASE_URL`
- `NEON_DATABASE_URL`

For review without touching the database:

```sh
scripts/fundz_postgres_memory.py --apply-schema --sync-operational-state --print-sql
```

If `psql` access is blocked because the database password is unavailable, generate Supabase SQL editor chunks instead:

```sh
make supabase-dashboard-sql
```

Run the chunk files in order in the Supabase SQL editor. The final `*-verify.sql` chunk checks total client rows, active client rows, active-view rows, and the dashboard sync marker.
