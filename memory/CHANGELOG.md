# Changelog

## 2026-05-03

### Added

- Added `AGENTS.md` to FUNDz.
- Added the `memory/` handoff scaffold.
- Added `Makefile` shortcuts for `make start`, `make memory-check`, and `make handoff`.
- Added `scripts/start-session.sh`, `scripts/check-memory.sh`, and `scripts/finish-session.sh`.
- Added `.github/workflows/memory-check.yml`.

### Changed

- Tailored core memory files to describe FUNDz instead of the Save A Token setup repo.

### Tests

- `sh scripts/check-memory.sh`: passed.

### Notes

- Existing FUNDz app logic was not changed for this scaffold.
- Existing uncommitted FUNDz work was already present and should not be included in the memory-system commit unless Brandon explicitly approves.
