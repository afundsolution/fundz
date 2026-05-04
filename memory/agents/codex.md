# Codex Notes

## Start Procedure

1. Read `AGENTS.md`.
2. Read `memory/HANDOFF.md`.
3. Read `memory/CURRENT_STATUS.md`.
4. Read `memory/NEXT_STEPS.md`.

## Working Style

- Inspect the workspace before editing.
- Keep changes scoped to the current task.
- Do not overwrite user or agent work without understanding it first.
- Run available tests when the change touches behavior.
- Run `sh scripts/check-memory.sh` before committing memory-system changes.
- Record commands, test results, blockers, and next steps in `memory/HANDOFF.md`.

## Before Stopping

- Update `memory/HANDOFF.md`.
- Update `memory/CURRENT_STATUS.md`.
- Update `memory/NEXT_STEPS.md`.
- Update `memory/CHANGELOG.md`.
- Commit with a clear message when Git is available.
