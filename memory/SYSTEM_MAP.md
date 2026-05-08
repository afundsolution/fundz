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

GitHub is the durable source of truth for committed FUNDz handoff memory:

```text
https://github.com/afundsolution/fundz
```

## Google Drive Backup

Google Drive stores a human-friendly backup/reference copy of the current memory packet:

```text
https://docs.google.com/document/d/1LJvMBEzbjSp9ZIuRrrEgVWEFOEu7SOOM4Eh8aP7owC4/edit
```

If GitHub and the Google Doc disagree, trust GitHub first and update the Drive copy from the repo memory files.

## Command Layer

`make start` prints the required reading order and starter prompt. `make memory-check` validates the memory packet. `make handoff MSG="Clear commit message"` runs the memory check, commits local changes, and pushes the current branch.

`make command-center` builds the local FUNDz operator view from the client brain, semi-autonomous queue, AutoFox audit, recent receipts, bridge/poller logs, and current blockers. Outputs stay local under `data/local/command-center/`.

## Validation Layer

`scripts/check-memory.sh` validates the required memory files and required `HANDOFF.md` sections. `.github/workflows/memory-check.yml` runs the same check in GitHub Actions on pushes and pull requests.

Latest verified state: Memory Check passed on `main` after the handoff-system push.

## App Logic

FUNDz now has local app logic for:

- Credit Tracker bridge/webhook handling with dry-run, signed probe, quarantine, and proposal support.
- HighLevel inbox/manual-import classification.
- Command-center, daily-board, Governor safe-fix, and client communication control-board generation.
- Semi-autonomous batch preview and approval-gated send preparation.
- ScoreFusion billing-risk reporting and maintenance cleanup.
- Intake Governor, phone-app intake, local AI router, owner-command fallback, and safe autonomous operator.

Live sends, DF/AutoFox browser edits, campaign assignments, webhook wiring, and owner-command loops remain action-time approval gated.
