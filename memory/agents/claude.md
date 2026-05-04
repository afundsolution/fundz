# Claude Notes

## Start Procedure

1. Read `AGENTS.md`.
2. Read `memory/HANDOFF.md`.
3. Read `memory/CURRENT_STATUS.md`.
4. Read `memory/NEXT_STEPS.md`.

## Working Style

- Treat the memory files as the shared project context.
- Preserve existing work unless Brandon explicitly asks for a reset.
- Keep implementation notes concise and durable.
- Run `sh scripts/check-memory.sh` before committing memory-system changes.
- When making code changes, update the handoff with files touched, tests run, and the next exact step.

## Before Stopping

- Update `memory/HANDOFF.md`.
- Update `memory/CURRENT_STATUS.md`.
- Update `memory/NEXT_STEPS.md`.
- Update `memory/CHANGELOG.md`.
- Commit with a clear message when Git is available.
