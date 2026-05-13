#!/usr/bin/env zsh
set -euo pipefail

REPO="/Users/turbo/Desktop/Go High Level Agent/FUNDz"
CLOUDFLARED="${CLOUDFLARED_BIN:-/opt/homebrew/bin/cloudflared}"
CLOUDFLARED_DIR="$HOME/.cloudflared"
TUNNEL_NAME="${FUNDZ_TUNNEL_NAME:-fundz-credit-tracker}"
COMMAND_HOSTNAME="${FUNDZ_COMMAND_CENTER_HOSTNAME:-fundz-command.afundsolution.com}"
COMMAND_PORT="${FUNDZ_COMMAND_CENTER_PORT:-8797}"
WEBHOOK_HOSTNAME="${FUNDZ_TUNNEL_HOSTNAME:-fundz.afundsolution.com}"
CONFIG_PATH="$CLOUDFLARED_DIR/fundz-command-center.yml"

mkdir -p "$CLOUDFLARED_DIR" "$REPO/logs"
cd "$REPO"

if [[ -f "$REPO/.env.local" ]]; then
  set -a
  source "$REPO/.env.local"
  set +a
  TUNNEL_NAME="${FUNDZ_TUNNEL_NAME:-$TUNNEL_NAME}"
  COMMAND_HOSTNAME="${FUNDZ_COMMAND_CENTER_HOSTNAME:-$COMMAND_HOSTNAME}"
  COMMAND_PORT="${FUNDZ_COMMAND_CENTER_PORT:-$COMMAND_PORT}"
  WEBHOOK_HOSTNAME="${FUNDZ_TUNNEL_HOSTNAME:-$WEBHOOK_HOSTNAME}"
fi

if [[ ! -x "$CLOUDFLARED" ]]; then
  echo "cloudflared not found at $CLOUDFLARED"
  exit 2
fi

if [[ ! -f "$CLOUDFLARED_DIR/cert.pem" ]]; then
  echo "Cloudflare login is required first."
  echo "Run: cloudflared tunnel login"
  exit 2
fi

if ! "$CLOUDFLARED" tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  "$CLOUDFLARED" tunnel create "$TUNNEL_NAME"
fi

TUNNEL_ID="$("$CLOUDFLARED" tunnel list | awk -v name="$TUNNEL_NAME" '$0 ~ name {print $1; exit}')"
if [[ -z "$TUNNEL_ID" ]]; then
  echo "Could not find tunnel ID for $TUNNEL_NAME"
  exit 1
fi

CREDENTIAL_FILE="$CLOUDFLARED_DIR/${TUNNEL_ID}.json"
if [[ ! -f "$CREDENTIAL_FILE" ]]; then
  echo "Missing Cloudflare tunnel credential file: $CREDENTIAL_FILE"
  exit 1
fi

python3 scripts/fundz_command_center.py --limit 10 >/dev/null
"$CLOUDFLARED" tunnel route dns "$TUNNEL_NAME" "$COMMAND_HOSTNAME"
if [[ -n "$WEBHOOK_HOSTNAME" ]]; then
  "$CLOUDFLARED" tunnel route dns "$TUNNEL_NAME" "$WEBHOOK_HOSTNAME" || true
fi

cat > "$CONFIG_PATH" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDENTIAL_FILE

ingress:
  - hostname: $COMMAND_HOSTNAME
    service: http://127.0.0.1:$COMMAND_PORT
  - hostname: $WEBHOOK_HOSTNAME
    service: http://127.0.0.1:8787
  - service: http_status:404
EOF

screen -S fundz-command-center -X quit 2>/dev/null || true
pkill -f "fundz_command_center_server.py --host 127.0.0.1 --port $COMMAND_PORT" 2>/dev/null || true
screen -dmS fundz-command-center zsh -lc "cd \"$REPO\" && exec python3 scripts/fundz_command_center_server.py --host 127.0.0.1 --port \"$COMMAND_PORT\" > logs/fundz-command-center.out.log 2> logs/fundz-command-center.err.log"

screen -S fundz-tunnel -X quit 2>/dev/null || true
pkill -f "cloudflared tunnel --config $CONFIG_PATH run $TUNNEL_NAME" 2>/dev/null || true
screen -dmS fundz-tunnel zsh -lc "cd \"$REPO\" && exec \"$CLOUDFLARED\" tunnel --config \"$CONFIG_PATH\" run \"$TUNNEL_NAME\" > logs/cloudflared-fundz.out 2>&1"

sleep 2

python3 - <<'PY'
import json
from pathlib import Path
path = Path("data/local/command-center/fundz-command-center-domain.json")
data = json.loads(path.read_text(encoding="utf-8"))
print("A FUND Solution Command Center domain is ready.")
print("Owner URL: stored locally in data/local/command-center/fundz-command-center-domain.json")
print(f"Local URL: {data.get('local_url')}")
print("Token: stored locally and not printed")
PY
