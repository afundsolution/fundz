# System Map

## Repository Purpose

FUNDz supports local operational automation around client updates, DisputeFox exports, HighLevel contact/workflow support, ScoreFusion billing reporting, and semi-autonomous action preparation.

## Current Structure

```text
/
  AGENTS.md
  Makefile
  README.md
  assistant/
  config/
  db/
  scripts/
    check-memory.sh
    finish-session.sh
    start-session.sh
  tests/
  memory/
    README.md
    COMMANDS.md
    CURRENT_STATUS.md
    HANDOFF.md
    NEXT_STEPS.md
    DECISIONS.md
    TODO.md
    SYSTEM_MAP.md
    CHANGELOG.md
    agents/
      codex.md
      claude.md
      dispatch.md
    workflows/
      ai_handoff_workflow.md
    logs/
      session-template.md
  .github/
    workflows/
      memory-check.yml
```

## Durable Memory Layer

The `memory/` folder is the portable handoff record for AI agents.

GitHub should become the durable source of truth once a FUNDz remote is configured and pushed.

## Command Layer

`make start` prints the required reading order and starter prompt. `make memory-check` validates the memory packet. `make handoff MSG="Clear commit message"` runs the memory check, commits local changes, and pushes the current branch.

## Validation Layer

`scripts/check-memory.sh` validates the required memory files and required `HANDOFF.md` sections. `.github/workflows/memory-check.yml` runs the same check in GitHub Actions on pushes and pull requests after the repo is pushed to GitHub.

## App Logic

No app logic was changed while installing this handoff scaffold.
