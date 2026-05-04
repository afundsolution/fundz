#!/usr/bin/env sh
set -eu

required_files="
AGENTS.md
Makefile
memory/README.md
memory/COMMANDS.md
memory/CURRENT_STATUS.md
memory/HANDOFF.md
memory/NEXT_STEPS.md
memory/DECISIONS.md
memory/TODO.md
memory/SYSTEM_MAP.md
memory/CHANGELOG.md
memory/agents/codex.md
memory/agents/claude.md
memory/agents/dispatch.md
memory/workflows/ai_handoff_workflow.md
memory/logs/session-template.md
scripts/start-session.sh
scripts/check-memory.sh
scripts/finish-session.sh
"

missing=0

for file in $required_files; do
  if [ ! -s "$file" ]; then
    printf 'Missing or empty: %s\n' "$file"
    missing=1
  fi
done

for heading in "## Current Goal" "## Current Status" "## Last Completed Step" "## Next Step" "## Files Changed Recently" "## Commands / Tests Run" "## Open Questions" "## Blockers" "## Notes for Next AI"; do
  if ! grep -Fq "$heading" memory/HANDOFF.md; then
    printf 'HANDOFF.md missing heading: %s\n' "$heading"
    missing=1
  fi
done

if ! grep -Fq "Always read memory/HANDOFF.md first." AGENTS.md; then
  printf 'AGENTS.md must explicitly instruct agents to read memory/HANDOFF.md first.\n'
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  printf 'Memory check failed.\n'
  exit 1
fi

printf 'Memory check passed.\n'
