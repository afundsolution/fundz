# Memory System

This folder is the portable AI handoff record for Brandon's coding work.

GitHub is the durable source of truth. Agents may later use faster live memory such as Supabase or Postgres, but the files here should always contain enough context for Codex, Claude, Dispatch, or another coding agent to continue work without guessing.

## Required Reading Order

1. `HANDOFF.md`
2. `CURRENT_STATUS.md`
3. `NEXT_STEPS.md`
4. `DECISIONS.md`
5. `SYSTEM_MAP.md`

## Required Updates Before Stopping

Every agent must update:

- `HANDOFF.md`
- `CURRENT_STATUS.md`
- `NEXT_STEPS.md`
- `CHANGELOG.md`

If the agent runs commands or tests, record the results in `HANDOFF.md`. If the agent is blocked, record the blocker there too.

## Validation

Run this before committing memory-system changes:

```sh
sh scripts/check-memory.sh
```

The check confirms that required files exist, required handoff headings are present, and `AGENTS.md` tells agents to read `memory/HANDOFF.md` first.

## Command Shortcut

Use `make start` at the beginning of a session and `make handoff MSG="Clear commit message"` before stopping. See `COMMANDS.md` for details.

## Folder Guide

- `CURRENT_STATUS.md`: Current state of the project and active work.
- `HANDOFF.md`: Short, direct handoff for the next AI agent.
- `NEXT_STEPS.md`: Prioritized next actions.
- `DECISIONS.md`: Durable technical and workflow decisions.
- `TODO.md`: Open tasks that are not necessarily the immediate next step.
- `SYSTEM_MAP.md`: High-level map of the repo, systems, services, and important files.
- `CHANGELOG.md`: Session-by-session change history.
- `COMMANDS.md`: Command shortcuts for starting, checking, and finishing handoffs.
- `agents/`: Agent-specific operating notes.
- `workflows/`: Repeatable workflows.
- `logs/`: Session log templates and optional session notes.
