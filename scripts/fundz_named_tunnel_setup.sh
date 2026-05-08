#!/usr/bin/env zsh
set -euo pipefail

REPO="/Users/turbo/Desktop/Go High Level Agent/FUNDz"
TUNNEL_NAME="${FUNDZ_TUNNEL_NAME:-fundz-credit-tracker}"
HOSTNAME="${FUNDZ_TUNNEL_HOSTNAME:-}"
CLOUDFLARED="${CLOUDFLARED_BIN:-/opt/homebrew/bin/cloudflared}"
CLOUDFLARED_DIR="$HOME/.cloudflared"
CONFIG_PATH="$CLOUDFLARED_DIR/fundz-credit-tracker.yml"

mkdir -p "$CLOUDFLARED_DIR"
cd "$REPO"

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

if [[ -n "$HOSTNAME" ]]; then
  "$CLOUDFLARED" tunnel route dns "$TUNNEL_NAME" "$HOSTNAME"
  cat > "$CONFIG_PATH" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDENTIAL_FILE

ingress:
  - hostname: $HOSTNAME
    service: http://127.0.0.1:8787
  - service: http_status:404
EOF
else
  cat > "$CONFIG_PATH" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDENTIAL_FILE

ingress:
  - service: http://127.0.0.1:8787
EOF
fi

screen -S fundz-tunnel -X quit 2>/dev/null || true
screen -dmS fundz-tunnel zsh -lc "cd \"$REPO\" && exec \"$CLOUDFLARED\" tunnel --config \"$CONFIG_PATH\" run \"$TUNNEL_NAME\" > logs/cloudflared-fundz.out 2>&1"

echo "Named tunnel started: $TUNNEL_NAME"
echo "Config: $CONFIG_PATH"
if [[ -n "$HOSTNAME" ]]; then
  echo "Webhook URL: https://$HOSTNAME/credit-tracker/webhook"
else
  echo "No hostname configured. Set FUNDZ_TUNNEL_HOSTNAME before running this script if you want a stable public URL."
fi
