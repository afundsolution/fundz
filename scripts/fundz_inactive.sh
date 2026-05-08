#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RECEIPT_DIR="$ROOT/data/local/command-center"
RECEIPT="$RECEIPT_DIR/fundz-inactive-receipt.md"
LABEL="com.afundsolution.fundz-imessage-fallback"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$RECEIPT_DIR"

stop_screen() {
  name="$1"
  if screen -list 2>/dev/null | grep -q "[.]$name[[:space:]]"; then
    screen -S "$name" -X quit >/dev/null 2>&1 || true
    printf 'Stopped screen session: %s\n' "$name"
  else
    printf 'Screen session already stopped: %s\n' "$name"
  fi
}

stop_screen fundz-bridge
stop_screen fundz-tunnel
stop_screen fundz-highlevel-poller

if command -v pkill >/dev/null 2>&1; then
  pkill -f "fundz_credit_tracker_bridge.py --port 8787" >/dev/null 2>&1 || true
  pkill -f "cloudflared.*fundz-credit-tracker" >/dev/null 2>&1 || true
fi

if [ -f "$PLIST" ]; then
  launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
  launchctl disable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  printf 'Disabled LaunchAgent: %s\n' "$LABEL"
else
  printf 'LaunchAgent plist not found: %s\n' "$PLIST"
fi

now="$(date +"%Y-%m-%d %H:%M:%S %Z")"
cat > "$RECEIPT" <<EOF
# FUNDz Inactive Receipt

Parked at: $now

Stopped or disabled:

- screen session: fundz-bridge
- screen session: fundz-tunnel
- screen session: fundz-highlevel-poller
- process match: fundz_credit_tracker_bridge.py --port 8787
- process match: cloudflared.*fundz-credit-tracker
- LaunchAgent: $LABEL

Operational posture:

- No client sends.
- No webhook bridge.
- No Cloudflare tunnel.
- No iMessage fallback loop.
- No DF/HighLevel/Credit Tracker browser action without a fresh wake request.

Wake instructions live in FUNDZ_SLEEP_MODE.md.
EOF

printf 'FUNDz is parked. Receipt: %s\n' "$RECEIPT"
