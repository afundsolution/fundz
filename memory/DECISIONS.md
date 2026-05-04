# Decisions

## 2026-05-01: GitHub Is the Durable Handoff Record

Decision: Use GitHub and committed repository files as the portable source of truth for AI handoffs.

Reason: Codex, Claude, Dispatch, and future agents can all read repository files, making GitHub the most portable baseline memory layer.

## 2026-05-01: Live Memory Can Come Later

Decision: Do not implement Supabase/Postgres memory yet.

Reason: The first task is templates only. A live memory system can be added later without weakening the GitHub handoff record.

## 2026-05-01: Agents Must Update Handoff Files Before Stopping

Decision: Every agent must update `HANDOFF.md`, `CURRENT_STATUS.md`, `NEXT_STEPS.md`, and `CHANGELOG.md` before ending a session.

Reason: This keeps the next agent from reconstructing context from chat history or unstated assumptions.

## 2026-05-02: Add Lightweight Memory Validation

Decision: Add `scripts/check-memory.sh` and a GitHub Actions workflow to validate required memory files.

Reason: The handoff system should be easy for every agent to verify before committing or merging changes.
