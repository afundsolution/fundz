#!/usr/bin/env zsh
set -euo pipefail

REPO="/Users/turbo/Desktop/Go High Level Agent/FUNDz"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

cd "$REPO"
mkdir -p logs

screen -S fundz-highlevel-poller -X quit 2>/dev/null || true
screen -dmS fundz-highlevel-poller zsh -lc "cd \"$REPO\" && exec \"$PYTHON_BIN\" scripts/fundz_highlevel_inbox_poller.py --daemon > logs/highlevel-inbox-poller.out 2>&1"

echo "FUNDz HighLevel inbox poller started in screen session fundz-highlevel-poller."
echo "Mode is controlled by FUNDZ_HIGHLEVEL_POLLER_LIVE and CREDIT_TRACKER_DRY_RUN."
