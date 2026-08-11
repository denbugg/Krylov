#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: /usr/local/sbin/elite-configure-telegram" >&2
  exit 1
fi

ENV_FILE=/etc/elite/elite.env
CURRENT=/srv/elite-bot/current
VENV_PY="$CURRENT/venv/bin/python"
EXPECTED_USERNAME=rg_elite_bot
export PYTHONPATH="$CURRENT/site"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Deploy the site first." >&2
  exit 1
fi
if [ ! -x "$VENV_PY" ]; then
  echo "Missing ELITE bot release. Run bot-bootstrap first." >&2
  exit 1
fi

read -r -p "Telegram BotFather token: " BOT_TOKEN
echo
if [ -z "$BOT_TOKEN" ]; then
  echo "Bot token is required." >&2
  exit 1
fi

# sitecustomize.py is loaded through PYTHONPATH and restricts requests/urllib3
# to IPv4 for this bot process. The VPS currently has an unusable IPv6 route.
DETECTED_USERNAME="$(TELEGRAM_BOT_TOKEN="$BOT_TOKEN" "$VENV_PY" - <<'PY'
import os
import sys
import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
url = f"https://api.telegram.org/bot{token}/getMe"
try:
    response = requests.post(url, timeout=15)
except requests.RequestException as exc:
    print(f"Telegram API connection failed over IPv4 ({type(exc).__name__}): {exc}", file=sys.stderr)
    raise SystemExit(1)
if response.status_code != 200:
    description = ""
    try:
        description = str(response.json().get("description") or "")
    except ValueError:
        pass
    suffix = f": {description}" if description else ""
    print(f"Telegram getMe returned HTTP {response.status_code}{suffix}", file=sys.stderr)
    raise SystemExit(1)
data = response.json()
result = data.get("result") or {}
if not data.get("ok") or not result.get("is_bot") or not result.get("username"):
    print("Telegram rejected the token or did not return a bot username.", file=sys.stderr)
    raise SystemExit(1)
print(result["username"])
PY
)"

if [ "${DETECTED_USERNAME,,}" != "${EXPECTED_USERNAME,,}" ]; then
  echo "This token belongs to @${DETECTED_USERNAME}, expected @${EXPECTED_USERNAME}. Refusing to bind the wrong bot." >&2
  unset BOT_TOKEN
  exit 1
fi
BOT_USERNAME="$DETECTED_USERNAME"
echo "Telegram token accepted for @${BOT_USERNAME}"

TELEGRAM_BOT_TOKEN="$BOT_TOKEN" "$VENV_PY" - <<'PY'
import os
import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
base = f"https://api.telegram.org/bot{token}"

def call(method: str, payload: dict) -> None:
    response = requests.post(base + "/" + method, json=payload, timeout=15)
    if response.status_code != 200:
        raise SystemExit(f"Telegram {method} returned HTTP {response.status_code}")
    data = response.json()
    if not data.get("ok"):
        raise SystemExit(f"Telegram {method} failed: {data.get('description') or 'unknown error'}")

call("deleteWebhook", {"drop_pending_updates": False})
call(
    "setMyCommands",
    {
        "commands": [
            {"command": "admin", "description": "Подключить чат менеджера"},
            {"command": "leads", "description": "Последние заявки"},
            {"command": "stats", "description": "Сводка по заявкам"},
            {"command": "lead", "description": "Карточка заявки по номеру"},
            {"command": "note", "description": "Добавить заметку к заявке"},
            {"command": "help", "description": "Команды Elite менеджера"},
        ]
    },
)
print("Telegram long polling and manager commands configured")
PY

set_env() {
  local key="$1"
  local value="$2"
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

chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"
systemctl daemon-reload
systemctl enable --now elite-bot.service
systemctl restart elite-bot.service
systemctl restart elite.service

sleep 1
if ! systemctl is-active --quiet elite-bot.service; then
  echo "elite-bot failed to start. Recent log:" >&2
  journalctl -u elite-bot.service -n 40 --no-pager >&2 || true
  unset BOT_TOKEN
  exit 1
fi

encryption_key="$(sed -n 's/^LEADS_ENCRYPTION_KEY=//p' "$ENV_FILE" | tail -n 1)"
db_path="$(sed -n 's/^LEADS_DB_PATH=//p' "$ENV_FILE" | tail -n 1)"
db_path="${db_path:-/var/lib/elite/leads.sqlite3}"
runuser -u elite -- env \
  TELEGRAM_BOT_TOKEN="$BOT_TOKEN" \
  LEADS_ENCRYPTION_KEY="$encryption_key" \
  LEADS_DB_PATH="$db_path" \
  SITE_ENV=production \
  PYTHONPATH="$CURRENT/site" \
  "$VENV_PY" "$CURRENT/site/bot_entry.py" --check
curl -fsS http://127.0.0.1:8000/healthz >/dev/null
unset BOT_TOKEN TELEGRAM_BOT_TOKEN encryption_key db_path

echo
echo "Elite менеджер is active as @${BOT_USERNAME}."
echo "Site deep link: https://t.me/${BOT_USERNAME}?start=site"
echo "Open @${BOT_USERNAME} from @Undina_007 and send /admin once to bind the operator chat."