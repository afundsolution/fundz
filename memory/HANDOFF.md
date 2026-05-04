# Handoff

## Current Goal

Install the portable AI handoff and memory system into the FUNDz repo so Brandon can pause work in Codex and continue in Claude, Dispatch, or another coding agent without losing context.

## Current Status

The memory scaffold and command shortcuts have been copied into the FUNDz project. Existing FUNDz app logic and current uncommitted work were left untouched.

## Last Completed Step

Copied and tailored `AGENTS.md`, `memory/`, command scripts, Makefile shortcuts, and the GitHub Actions memory check in FUNDz.

## Next Step

Commit only the new handoff-system files, create/connect a private GitHub remote for FUNDz if needed, and push the handoff setup.

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

## Commands / Tests Run

- Checked FUNDz Git status and confirmed existing uncommitted project changes were already present.
- Checked for existing `AGENTS.md`, `memory/`, command scripts, and Makefile: none were present.
- Copied the handoff scaffold from `/Users/turbo/Desktop/Save A Token`.
- Ran `sh scripts/check-memory.sh`: passed.

## Open Questions

- Should FUNDz use a new private GitHub repo named `afundsolution/fundz`, or should it connect to a different existing remote?
- Should the Google Drive backup doc be updated with a FUNDz-specific handoff snapshot after the GitHub remote is connected?

## Blockers

- FUNDz does not currently have a Git remote configured.

## Notes for Next AI

Read this file first, then read `memory/CURRENT_STATUS.md` and `memory/NEXT_STEPS.md`. Do not commit unrelated existing FUNDz changes unless Brandon explicitly asks. Before stopping, update the required memory files and run the memory check.
