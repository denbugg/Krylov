#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

REPO_URL="${GIT_REPO_URL:-https://github.com/denbugg/Krylov.git}"
REPO=/srv/elite-bot/repo

if [ ! -f /etc/elite/elite.env ]; then
  echo "Missing /etc/elite/elite.env. Bootstrap the ELITE site first." >&2
  exit 1
fi
if ! id -u elite >/dev/null 2>&1; then
  echo "Missing elite system user. Bootstrap the ELITE site first." >&2
  exit 1
fi

mkdir -p /srv/elite-bot/releases
chown elite:elite /srv/elite-bot/releases

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

echo
echo "ELITE bot bootstrap OK"
echo "Current bot release: $(basename "$(readlink -f /srv/elite-bot/current)")"
echo "Autodeploy timer: $(systemctl is-active elite-bot-autodeploy.timer 2>/dev/null || echo inactive)"
if grep -q '^TELEGRAM_BOT_TOKEN=.$' /etc/elite/elite.env 2>/dev/null; then
  echo "Telegram token: configured"
else
  token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' /etc/elite/elite.env | tail -n 1)"
  if [ -n "$token" ]; then
    echo "Telegram token: configured"
  else
    echo "Telegram token: not configured"
    echo "Next: /usr/local/sbin/elite-configure-telegram"
  fi
fi
