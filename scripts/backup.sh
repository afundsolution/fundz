#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.local"

if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
TIMESTAMP="$(date +"%Y%m%d-%H%M%S")"
ARCHIVE_NAME="fundz-backup-${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${BACKUP_DIR}/${ARCHIVE_NAME}"

mkdir -p "${BACKUP_DIR}"

tar \
  --exclude=".git" \
  --exclude=".env" \
  --exclude=".env.*" \
  --exclude="backups" \
  --exclude="node_modules" \
  --exclude="dist" \
  --exclude="build" \
  --exclude=".next" \
  --exclude=".turbo" \
  -czf "${ARCHIVE_PATH}" \
  -C "${ROOT_DIR}" .

echo "Created local backup: ${ARCHIVE_PATH}"

if [ -n "${RCLONE_REMOTE:-}" ]; then
  if ! command -v rclone >/dev/null 2>&1; then
    echo "RCLONE_REMOTE is set, but rclone is not installed or not on PATH." >&2
    exit 1
  fi

  rclone copy "${ARCHIVE_PATH}" "${RCLONE_REMOTE}"
  echo "Copied backup to remote: ${RCLONE_REMOTE}"
fi
