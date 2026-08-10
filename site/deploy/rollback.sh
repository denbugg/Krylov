#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

UPDATE_LOCK=/run/elite-update.lock
exec 9>"$UPDATE_LOCK"
if ! flock -n 9; then
  echo "Another ELITE deploy/watchdog operation is already running; rollback not started." >&2
  exit 1
fi

RELEASES=/srv/elite/releases
CURRENT=/srv/elite/current
PREVIOUS=/srv/elite/previous
STATE_DIR=/var/lib/elite
TARGET="${1:-}"

atomic_link() {
  local target="$1" link="$2" tmp="${link}.new"
  ln -sfn "$target" "$tmp"
  mv -Tf "$tmp" "$link"
}

if [ -n "$TARGET" ]; then
  TARGET_RELEASE="$RELEASES/$TARGET"
else
  TARGET_RELEASE="$(readlink -f "$PREVIOUS" 2>/dev/null || true)"
fi

if [ -z "$TARGET_RELEASE" ] || [ ! -d "$TARGET_RELEASE/site" ] || [ ! -x "$TARGET_RELEASE/venv/bin/python" ]; then
  echo "Rollback target is not available as a prepared release." >&2
  echo "Available releases:" >&2
  find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort >&2 || true
  exit 1
fi

CURRENT_RELEASE="$(readlink -f "$CURRENT" 2>/dev/null || true)"
TARGET_SHA="$(basename "$TARGET_RELEASE")"
CURRENT_SHA="$(basename "$CURRENT_RELEASE" 2>/dev/null || true)"

# Verify the target before switching.
(
  cd "$TARGET_RELEASE/site"
  PYTHONPATH="$TARGET_RELEASE/site" "$TARGET_RELEASE/venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -q
)

[ -n "$CURRENT_RELEASE" ] && [ -d "$CURRENT_RELEASE" ] && atomic_link "$CURRENT_RELEASE" "$PREVIOUS"
atomic_link "$TARGET_RELEASE" "$CURRENT"

install -m 0644 "$TARGET_RELEASE/site/deploy/fallback.html" /srv/elite/fallback/index.html
install -m 0644 "$TARGET_RELEASE/site/deploy/elite.service" /etc/systemd/system/elite.service
[ -f "$TARGET_RELEASE/site/deploy/elite-bot.service" ] && install -m 0644 "$TARGET_RELEASE/site/deploy/elite-bot.service" /etc/systemd/system/elite-bot.service
install -m 0755 "$TARGET_RELEASE/site/deploy/update.sh" /usr/local/sbin/elite-update
install -m 0755 "$TARGET_RELEASE/site/deploy/rollback.sh" /usr/local/sbin/elite-rollback

domain="$(sed -n 's/^SITE_DOMAIN=//p' /etc/elite/elite.env | tail -n 1)"
[ -n "$domain" ]
nginx_template="$TARGET_RELEASE/site/deploy/nginx.conf.template"
if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
  nginx_template="$TARGET_RELEASE/site/deploy/nginx.https.conf.template"
fi
sed "s/__DOMAIN__/$domain/g" "$nginx_template" >/etc/nginx/sites-available/elite

systemctl daemon-reload
nginx -t
systemctl restart elite.service
systemctl reload nginx
curl --retry 10 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null

token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' /etc/elite/elite.env | tail -n 1)"
if [ -n "$token" ] && [ -f /etc/systemd/system/elite-bot.service ]; then
  systemctl restart elite-bot.service
fi

printf '%s\n' "$TARGET_SHA" >"$STATE_DIR/deployed-sha"
[ -n "$CURRENT_SHA" ] && printf '%s\n' "$CURRENT_SHA" >"$STATE_DIR/previous-sha"
echo "ELITE rolled back atomically to ${TARGET_SHA:0:7}; former current ${CURRENT_SHA:0:7}"
