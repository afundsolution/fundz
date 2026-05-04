#!/usr/bin/env sh
set -eu

message=${1:-}

if [ -z "$message" ]; then
  message="Update AI handoff memory"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Not inside a Git repository.\n'
  exit 1
fi

branch=$(git branch --show-current)

if [ -z "$branch" ]; then
  printf 'Could not determine the current Git branch.\n'
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  printf 'No origin remote is configured.\n'
  exit 1
fi

sh scripts/check-memory.sh

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "$message"
else
  printf 'No local changes to commit.\n'
fi

if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
  git push
else
  git push -u origin "$branch"
fi

printf 'Handoff pushed on %s.\n' "$branch"
