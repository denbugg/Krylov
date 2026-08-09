#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

REPO=/srv/elite/repo
SITE=/srv/elite/site
VENV=/srv/elite/venv
STATE_DIR=/var/lib/elite
TMP_DIR="$(mktemp -d /tmp/elite-update.XXXXXX)"
trap 'rm -r -- "$TMP_DIR"' EXIT

git_elite() {
  runuser -u elite -- git -C "$REPO" "$@"
}

install_runtime_units() {
  mkdir -p "$STATE_DIR"
  chown elite:www-data "$STATE_DIR"
  chmod 0750 "$STATE_DIR"
  install -m 0755 "$SITE/deploy/update.sh" /usr/local/sbin/elite-update
  install -m 0755 "$SITE/deploy/rollback.sh" /usr/local/sbin/elite-rollback
  install -m 0644 "$SITE/deploy/elite.service" /etc/systemd/system/elite.service
  if [ -f "$SITE/deploy/elite-bot.service" ]; then
    install -m 0644 "$SITE/deploy/elite-bot.service" /etc/systemd/system/elite-bot.service
  fi
  if [ -f "$SITE/deploy/elite-autodeploy.service" ] && [ -f "$SITE/deploy/elite-autodeploy.timer" ]; then
    install -m 0644 "$SITE/deploy/elite-autodeploy.service" /etc/systemd/system/elite-autodeploy.service
    install -m 0644 "$SITE/deploy/elite-autodeploy.timer" /etc/systemd/system/elite-autodeploy.timer
  fi
  systemctl daemon-reload
  if [ -f /etc/systemd/system/elite-autodeploy.timer ]; then
    systemctl enable --now elite-autodeploy.timer >/dev/null 2>&1 || true
  fi
  token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' /etc/elite/elite.env | tail -n 1)"
  if [ -n "$token" ] && [ -f /etc/systemd/system/elite-bot.service ]; then
    systemctl enable --now elite-bot.service >/dev/null 2>&1 || true
  fi
}

# Always install the latest deployment units from the currently checked-out site.
# This makes the second invocation after the first upgrade complete the one-time
# bot/autodeploy installation even when there is no newer Git commit.
install_runtime_units

PREV="$(git_elite rev-parse HEAD)"
git_elite fetch --prune origin sitest
TARGET="$(git_elite rev-parse origin/sitest)"

if [ "$TARGET" = "$PREV" ]; then
  echo "ELITE already up to date at ${PREV:0:7}"
  exit 0
fi

cp -a /etc/nginx/sites-available/elite "$TMP_DIR/nginx.conf"
cp -a /etc/systemd/system/elite.service "$TMP_DIR/elite.service"

rollback() {
  echo "Update failed; rolling back to $PREV" >&2
  git_elite reset --hard "$PREV"
  git_elite sparse-checkout set site
  "$VENV/bin/pip" install -r "$SITE/requirements.txt"
  install -m 0644 "$TMP_DIR/nginx.conf" /etc/nginx/sites-available/elite
  install -m 0644 "$TMP_DIR/elite.service" /etc/systemd/system/elite.service
  systemctl daemon-reload
  nginx -t
  systemctl restart elite
  systemctl reload nginx
  curl -fsS http://127.0.0.1:8000/healthz >/dev/null
}

deploy() {
  git_elite reset --hard "$TARGET" || return 1
  git_elite sparse-checkout set site || return 1
  "$VENV/bin/python" -m py_compile "$SITE/app.py" "$SITE/wsgi.py" "$SITE/bot.py" || return 1
  "$VENV/bin/pip" install -r "$SITE/requirements.txt" || return 1

  domain="$(sed -n 's/^SITE_DOMAIN=//p' /etc/elite/elite.env | tail -n 1)"
  [ -n "$domain" ] || return 1
  nginx_template="$SITE/deploy/nginx.conf.template"
  if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
    nginx_template="$SITE/deploy/nginx.https.conf.template"
  fi
  sed "s/__DOMAIN__/$domain/g" "$nginx_template" >"$TMP_DIR/nginx.new"
  install -m 0644 "$TMP_DIR/nginx.new" /etc/nginx/sites-available/elite
  install_runtime_units
  nginx -t || return 1
  systemctl restart elite || return 1
  systemctl reload nginx || return 1
  curl --retry 8 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null || return 1

  token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' /etc/elite/elite.env | tail -n 1)"
  if [ -n "$token" ] && [ -f /etc/systemd/system/elite-bot.service ]; then
    systemctl restart elite-bot || return 1
  fi
}

if ! deploy; then
  rollback
  exit 1
fi

printf '%s\n' "$PREV" >"$STATE_DIR/previous-sha"
git_elite rev-parse HEAD >"$STATE_DIR/deployed-sha"
echo "ELITE updated to $(git_elite rev-parse --short HEAD); rollback target ${PREV:0:7}"
