# Next Steps

## Immediate Next Step

1. Run `sh scripts/check-memory.sh`.
2. Commit only the new handoff-system files.
3. Create or connect the intended private GitHub remote for FUNDz.
4. Push the handoff-system commit.

## After That

- Use `make start` at the beginning of each FUNDz coding session.
- Before each handoff, update the required memory files and run `make handoff MSG="Clear commit message"` only when all local changes are ready to commit.
- Update `SYSTEM_MAP.md` with more FUNDz details as workflows stabilize.
- Add a FUNDz-specific Google Drive backup doc if Brandon wants Drive reference access.

## Not Started

- Live Supabase/Postgres memory implementation.
- Branch protection requiring the Memory Check workflow.
- FUNDz-specific Google Drive backup snapshot.
