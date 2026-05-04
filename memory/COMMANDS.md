# Memory Commands

These commands make the handoff workflow easier to run consistently.

## Start a Session

```sh
make start
```

This prints the required reading order and a ready-to-use agent prompt.

## Check Memory Files

```sh
make memory-check
```

This validates the required files and required `HANDOFF.md` sections.

## Finish a Session

```sh
make handoff MSG="Update handoff after current task"
```

This runs the memory check, commits all local changes, and pushes the current branch to `origin`.

Before running this command, the agent must update:

- `memory/HANDOFF.md`
- `memory/CURRENT_STATUS.md`
- `memory/NEXT_STEPS.md`
- `memory/CHANGELOG.md`

## Direct Script Commands

The same commands can be run without `make`:

```sh
sh scripts/start-session.sh
sh scripts/check-memory.sh
sh scripts/finish-session.sh "Update handoff after current task"
```
