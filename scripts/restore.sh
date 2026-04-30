#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/restore.sh /path/to/fundz-backup.tar.gz" >&2
  exit 1
fi

ARCHIVE_PATH="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESTORE_DIR="${ROOT_DIR}/restored/$(basename "${ARCHIVE_PATH}" .tar.gz)"

mkdir -p "${RESTORE_DIR}"
tar -xzf "${ARCHIVE_PATH}" -C "${RESTORE_DIR}"

echo "Restored backup into: ${RESTORE_DIR}"
