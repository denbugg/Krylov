#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

REPO_URL="${GIT_REPO_URL:-https://github.com/denbugg/Krylov.git}"
REPO=/srv/elite-bot/repo
ENV_FILE=/etc/elite/elite.env

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Bootstrap the ELITE site first." >&2
  exit 1
fi
if ! id -u elite >/dev/null 2>&1; then
  echo "Missing elite system user. Bootstrap the ELITE site first." >&2
  exit 1
fi

install -d -m 0755 -o elite -g elite /srv/elite-bot /srv/elite-bot/releases

if [ ! -d "$REPO/.git" ]; then
  rm -rf "$REPO"
  runuser -u elite -- git clone --no-checkout --branch elite-bot "$REPO_URL" "$REPO"
  runuser -u elite -- git -C "$REPO" sparse-checkout init --cone
  runuser -u elite -- git -C "$REPO" sparse-checkout set site
  runuser -u elite -- git -C "$REPO" checkout elite-bot
else
  runuser -u elite -- git -C "$REPO" fetch --prune origin elite-bot
  runuser -u elite -- git -C "$REPO" reset --hard origin/elite-bot
  runuser -u elite -- git -C "$REPO" sparse-checkout set site
fi

install -m 0755 "$REPO/site/deploy/bot-update.sh" /usr/local/sbin/elite-bot-update
/usr/local/sbin/elite-bot-update

token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$ENV_FILE" | tail -n 1)"
if [ -z "$token" ]; then
  echo
  echo "Bot code is deployed. Telegram BotFather token is required to start @rg_elite_bot."
  echo "The token will be entered with hidden input and stored only in $ENV_FILE."
  /usr/local/sbin/elite-configure-telegram
else
  echo "Telegram token already configured; updater verification passed."
  systemctl enable --now elite-bot.service >/dev/null 2>&1
  systemctl is-active --quiet elite-bot.service
fi
unset token

echo
echo "ELITE bot bootstrap OK"
echo "Current bot release: $(basename "$(readlink -f /srv/elite-bot/current)")"
echo "Bot service: $(systemctl is-active elite-bot.service 2>/dev/null || echo inactive)"
echo "Autodeploy timer: $(systemctl is-active elite-bot-autodeploy.timer 2>/dev/null || echo inactive)"
echo "Manager: https://t.me/rg_elite_bot"
echo "Next: open @rg_elite_bot from @Undina_007 and send /admin once to bind the operator chat."
