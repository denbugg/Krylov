#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo /usr/local/sbin/elite-configure-telegram" >&2
  exit 1
fi

ENV_FILE=/etc/elite/elite.env
CURRENT=/srv/elite/current
VENV_PY="$CURRENT/venv/bin/python"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Deploy the site first." >&2
  exit 1
fi
if [ ! -x "$VENV_PY" ]; then
  echo "Missing current ELITE release. Deploy the site first." >&2
  exit 1
fi

read -r -p "Telegram bot username (without @): " BOT_USERNAME
BOT_USERNAME="${BOT_USERNAME#@}"
BOT_USERNAME="${BOT_USERNAME// /}"
if [ -z "$BOT_USERNAME" ]; then
  echo "Bot username is required." >&2
  exit 1
fi

read -r -s -p "Telegram BotFather token (hidden): " BOT_TOKEN
echo
if [ -z "$BOT_TOKEN" ]; then
  echo "Bot token is required." >&2
  exit 1
fi

TELEGRAM_BOT_TOKEN="$BOT_TOKEN" "$VENV_PY" - <<'PY'
import json
import os
import sys
import urllib.request

token = os.environ["TELEGRAM_BOT_TOKEN"]
try:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=12) as response:
        data = json.load(response)
except Exception:
    print("Could not validate token against Telegram Bot API.", file=sys.stderr)
    raise SystemExit(1)
if not data.get("ok") or not data.get("result", {}).get("is_bot"):
    print("Telegram rejected this bot token.", file=sys.stderr)
    raise SystemExit(1)
print("Telegram token validated for @" + data["result"].get("username", "<unknown>"))
PY

set_env() {
  local key="$1" value="$2"
  "$VENV_PY" - "$ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

set_env TELEGRAM_BOT_TOKEN "$BOT_TOKEN"
set_env TELEGRAM_BOT_USERNAME "$BOT_USERNAME"
set_env TELEGRAM_ADMIN_USERNAME "Undina_007"

CURRENT_ADMIN_TOKEN="$(sed -n 's/^ADMIN_TOKEN=//p' "$ENV_FILE" | tail -n 1)"
if [ -z "$CURRENT_ADMIN_TOKEN" ]; then
  GENERATED_ADMIN_TOKEN="$($VENV_PY - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
)"
  set_env ADMIN_TOKEN "$GENERATED_ADMIN_TOKEN"
fi

chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"
systemctl daemon-reload
systemctl enable --now elite-bot.service
systemctl restart elite-bot.service
systemctl restart elite.service

sleep 1
if ! systemctl is-active --quiet elite-bot.service; then
  echo "elite-bot failed to start. Recent log:" >&2
  journalctl -u elite-bot.service -n 30 --no-pager >&2 || true
  exit 1
fi
curl -fsS http://127.0.0.1:8000/healthz >/dev/null

unset BOT_TOKEN TELEGRAM_BOT_TOKEN

echo
echo "Telegram bot is active."
echo "Site deep link: https://t.me/${BOT_USERNAME}?start=hero"
echo "Next: open the bot from @Undina_007 and send /admin once to bind the operator chat."
