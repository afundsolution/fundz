# Changelog

## 2026-05-03

### Added

- Added `AGENTS.md` to FUNDz.
- Added the `memory/` handoff scaffold.
- Added `Makefile` shortcuts for `make start`, `make memory-check`, and `make handoff`.
- Added `scripts/start-session.sh`, `scripts/check-memory.sh`, and `scripts/finish-session.sh`.
- Added `.github/workflows/memory-check.yml`.
- Created private GitHub repository `afundsolution/fundz`.
- Created Google Drive backup/reference doc: `https://docs.google.com/document/d/1LJvMBEzbjSp9ZIuRrrEgVWEFOEu7SOOM4Eh8aP7owC4/edit`.

### Changed

- Tailored core memory files to describe FUNDz instead of the Save A Token setup repo.
- Updated memory files with the FUNDz GitHub and Google Drive links.

### Tests

- `sh scripts/check-memory.sh`: passed.
- `git push -u origin main`: pushed FUNDz to GitHub.
- `gh run watch 25300657050 --repo afundsolution/fundz --exit-status`: Memory Check workflow passed.
- `make start`: printed the required reading order and startup prompt.
- Google Docs connector readback: verified the Drive doc content exists.

### Notes

- Existing FUNDz app logic was not changed for this scaffold.
- Existing uncommitted FUNDz work was already present and should not be included in the memory-system commit unless Brandon explicitly approves.
- `make handoff` commits all local changes by design; review the worktree before using it in FUNDz.
