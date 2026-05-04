# Handoff

## Current Goal

Install the portable AI handoff and memory system into the FUNDz repo so Brandon can pause work in Codex and continue in Claude, Dispatch, or another coding agent without losing context.

## Current Status

The memory scaffold and command shortcuts have been installed in FUNDz, committed, pushed to the private GitHub repository `https://github.com/afundsolution/fundz`, and backed up to Google Drive. Existing FUNDz app logic and current uncommitted work were left untouched.

## Last Completed Step

Created the private GitHub remote, pushed `main`, verified the Memory Check workflow, and created the FUNDz Google Drive backup doc.

## Next Step

Use `make start` at the beginning of each FUNDz coding session. Before handoff, update memory files and use `make handoff MSG="Clear commit message"` only when all local changes are ready to commit.

## Files Changed Recently

- `AGENTS.md`
- `Makefile`
- `.github/workflows/memory-check.yml`
- `memory/README.md`
- `memory/COMMANDS.md`
- `memory/CURRENT_STATUS.md`
- `memory/HANDOFF.md`
- `memory/NEXT_STEPS.md`
- `memory/DECISIONS.md`
- `memory/TODO.md`
- `memory/SYSTEM_MAP.md`
- `memory/CHANGELOG.md`
- `memory/agents/codex.md`
- `memory/agents/claude.md`
- `memory/agents/dispatch.md`
- `memory/workflows/ai_handoff_workflow.md`
- `memory/logs/session-template.md`
- `scripts/check-memory.sh`
- `scripts/start-session.sh`
- `scripts/finish-session.sh`
- GitHub repo: `https://github.com/afundsolution/fundz`
- Google Doc: `https://docs.google.com/document/d/1LJvMBEzbjSp9ZIuRrrEgVWEFOEu7SOOM4Eh8aP7owC4/edit`

## Commands / Tests Run

- Checked FUNDz Git status and confirmed existing uncommitted project changes were already present.
- Checked for existing `AGENTS.md`, `memory/`, command scripts, and Makefile: none were present.
- Copied the handoff scaffold from `/Users/turbo/Desktop/Save A Token`.
- Ran `sh scripts/check-memory.sh`: passed.
- Committed scaffold as `86c9b8e Add AI handoff memory system`.
- Created private GitHub repo `afundsolution/fundz`.
- Pushed `main` to `https://github.com/afundsolution/fundz`.
- Ran `gh run watch 25300657050 --repo afundsolution/fundz --exit-status`: Memory Check workflow passed.
- Ran `make start`: printed the required reading order and startup prompt.
- Created Google Doc `FUNDz - AI Handoff Memory Packet`.
- Read the Google Doc back through the connector and verified the content was present.

## Open Questions

- Should live Supabase/Postgres memory be added later, or should GitHub plus Google Drive remain the first operating mode?

## Blockers

- None for the handoff system.

## Notes for Next AI

Read this file first, then read `memory/CURRENT_STATUS.md` and `memory/NEXT_STEPS.md`. Do not commit unrelated existing FUNDz changes unless Brandon explicitly asks. `make handoff` commits all local changes, so use it only when the worktree is ready. Before stopping, update the required memory files and run the memory check.
