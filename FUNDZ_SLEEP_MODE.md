# FUNDz Sleep Mode

Status: FUN, AUTONOMOUS LOCALLY, AND NOT SENDING CLIENTS.

```text
        ______________________________
       /                              \
      |  FUNDz is awake locally.       |
      |  Lights: cozy.                 |
      |  Client sends: off.            |
      |  Owner commands: awake.        |
      |  Next live move: on purpose.   |
       \______________________________/
```

## What Inactive Means

- Do not send client messages, assign campaigns, wire webhooks, edit DF/HighLevel/Credit Tracker records, or open operational browser sessions unless Brandon explicitly asks to wake that exact live step.
- Brandon explicitly requested the local autonomous operator and FUNDz iMessage fallback LaunchAgents enabled on May 8, 2026. Keep `fundz-bridge`, `fundz-tunnel`, and `fundz-highlevel-poller` stopped unless named.
- Local reporting, reading, memory review, and the safe autonomous operator are fine, but keep them read-only and dry-run by default.
- `make autonomous` may refresh local boards, intake, cleanup, proposals, and tests while FUNDz is asleep. It must not start live runtime pieces or send client messages.
- The first file for the next agent is still `memory/HANDOFF.md`; this sleep-mode note is the big friendly sign on the door.

## How To Park It Again

Run:

```sh
make inactive
```

That stops the local runtime sessions and writes a local receipt under `data/local/command-center/`.

## How To Wake It Later

Only after a fresh explicit request from Brandon:

1. Read `memory/HANDOFF.md`, `memory/CURRENT_STATUS.md`, and `memory/NEXT_STEPS.md`.
2. Run `make daily-board` and review the Work Queue before touching any live system.
3. Re-enable only the specific runtime piece Brandon asked for.
4. Keep live sends and browser edits behind exact action-time approval.
