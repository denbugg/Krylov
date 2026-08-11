#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

SITE_REPO=/srv/elite/repo
BOT_REPO=/srv/elite-bot/repo

echo "=== REPAIR SITE DEPLOY ==="
runuser -u elite -- git -C "$SITE_REPO" fetch --prune origin sitest
runuser -u elite -- git -C "$SITE_REPO" reset --hard origin/sitest
install -m 0755 "$SITE_REPO/site/deploy/update.sh" /usr/local/sbin/elite-update
/usr/local/sbin/elite-update
systemctl daemon-reload
systemctl enable --now elite-autodeploy.timer
systemctl restart elite-autodeploy.timer

echo
echo "=== REPAIR BOT DEPLOY ==="
if [ -d "$BOT_REPO/.git" ]; then
  runuser -u elite -- git -C "$BOT_REPO" fetch --prune origin elite-bot
  runuser -u elite -- git -C "$BOT_REPO" reset --hard origin/elite-bot
else
  install -d -m 0755 -o elite -g elite /srv/elite-bot /srv/elite-bot/releases
  runuser -u elite -- git clone --no-checkout --branch elite-bot https://github.com/denbugg/Krylov.git "$BOT_REPO"
  runuser -u elite -- git -C "$BOT_REPO" sparse-checkout init --cone
  runuser -u elite -- git -C "$BOT_REPO" sparse-checkout set site
  runuser -u elite -- git -C "$BOT_REPO" checkout elite-bot
fi
install -m 0755 "$BOT_REPO/site/deploy/bot-update.sh" /usr/local/sbin/elite-bot-update
/usr/local/sbin/elite-bot-update
systemctl daemon-reload
systemctl enable --now elite-bot-autodeploy.timer
systemctl restart elite-bot-autodeploy.timer

echo
echo "=== STATE ==="
echo -n "site current: "; basename "$(readlink -f /srv/elite/current)"
echo -n "site github:  "; runuser -u elite -- git -C "$SITE_REPO" rev-parse origin/sitest
echo -n "bot current:  "; basename "$(readlink -f /srv/elite-bot/current)"
echo -n "bot github:   "; runuser -u elite -- git -C "$BOT_REPO" rev-parse origin/elite-bot
echo -n "site timer:   "; systemctl is-active elite-autodeploy.timer
echo -n "bot timer:    "; systemctl is-active elite-bot-autodeploy.timer

echo
echo "Telegram configurator prompt on this VPS:"
grep -F 'Telegram BotFather token' /usr/local/sbin/elite-configure-telegram | head -n 1 || true

echo
echo "Autodeploy repair complete. Future Git pushes should not require manual deploy commands."
