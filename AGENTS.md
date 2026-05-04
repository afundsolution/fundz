# Agent Instructions

This repository uses the `memory/` folder as the durable, portable handoff record for AI coding agents. GitHub is the source of truth for shared context between Codex, Claude, Dispatch, and any future agent.

## Start Here

Every AI agent must begin by reading:

1. `memory/HANDOFF.md`
2. `memory/CURRENT_STATUS.md`
3. `memory/NEXT_STEPS.md`

Always read memory/HANDOFF.md first.

Use those files to understand the current goal, recent work, exact next action, blockers, and any instructions from Brandon or the previous agent.

## Working Rules

- Do not overwrite existing work without checking context first.
- Review recent changes before editing files that may have been touched by another agent.
- Keep app logic unchanged unless the current task explicitly asks for implementation work.
- Prefer small, clear changes that can be reviewed and handed off easily.
- If tests are available, run them before stopping and record the command plus result in `memory/HANDOFF.md`.
- Run `sh scripts/check-memory.sh` before committing when the script exists.
- To finish a session on command, update the required memory files and run `make handoff MSG="Clear commit message"`.
- If blocked, write the blocker clearly in `memory/HANDOFF.md`.

## Before Stopping

Before ending a session, every agent must update:

- `memory/HANDOFF.md`
- `memory/CURRENT_STATUS.md`
- `memory/NEXT_STEPS.md`
- `memory/CHANGELOG.md`

Include what changed, what was tested, what remains, and the exact next step for the next agent.

## Commit Expectations

Commit changes with a clear message before handing off whenever this workspace is inside a Git repository. The commit message should summarize the completed step, for example:

```text
Add portable AI handoff memory scaffold
```

If a commit cannot be created, record why in `memory/HANDOFF.md`.
