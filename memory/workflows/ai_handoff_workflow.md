# AI Handoff Workflow

## Purpose

Allow Brandon to pause work in one AI coding agent and continue in another without losing context.

## Workflow

1. Agent starts work.
2. Agent reads `AGENTS.md`.
3. Agent reads `memory/HANDOFF.md`.
4. Agent reads `memory/CURRENT_STATUS.md`.
5. Agent reads `memory/NEXT_STEPS.md`.
6. Agent completes the requested task.
7. Agent runs available tests when relevant.
8. Agent updates required memory files.
9. Agent runs `sh scripts/check-memory.sh` when the script exists.
10. Agent commits changes with a clear message when Git is available.
11. Next agent continues by reading the same files.

## Required Handoff Updates

Before stopping, update:

- `memory/HANDOFF.md`
- `memory/CURRENT_STATUS.md`
- `memory/NEXT_STEPS.md`
- `memory/CHANGELOG.md`

## Handoff Quality Bar

A good handoff tells the next agent:

- What Brandon is trying to accomplish.
- What is already done.
- What changed recently.
- What commands or tests were run.
- What is blocked.
- What exact step to take next.
- What not to touch.

## Commit Guidance

Use clear, task-focused commit messages. Examples:

```text
Add portable AI handoff memory scaffold
Update handoff after auth flow fix
Record deployment blocker and next steps
```
