#!/usr/bin/env sh
set -eu

printf 'AI handoff start command\n'
printf '\n'
printf 'Read these files in order:\n'
printf '1. AGENTS.md\n'
printf '2. memory/HANDOFF.md\n'
printf '3. memory/CURRENT_STATUS.md\n'
printf '4. memory/NEXT_STEPS.md\n'
printf '\n'
printf 'Suggested agent prompt:\n'
printf 'Read AGENTS.md and memory/HANDOFF.md first, then read memory/CURRENT_STATUS.md and memory/NEXT_STEPS.md. Continue from the exact next step and update the memory files before stopping.\n'
