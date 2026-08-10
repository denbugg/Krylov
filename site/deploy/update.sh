#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

REPO=/srv/elite/repo
RELEASES=/srv/elite/releases
CURRENT=/srv/elite/current
PREVIOUS=/srv/elite/previous
STATE_DIR=/var/lib/elite
FALLBACK_DIR=/srv/elite/fallback
TMP_DIR="$(mktemp -d /tmp/elite-update.XXXXXX)"
CANDIDATE_PORT=18000
SWITCHED=0
OLD_RELEASE=""
trap 'rm -rf -- "$TMP_DIR"' EXIT

git_elite() {
  runuser -u elite -- git -C "$REPO" "$@"
}

atomic_link() {
  local target="$1" link="$2" tmp="${link}.new"
  ln -sfn "$target" "$tmp"
  mv -Tf "$tmp" "$link"
}

install_runtime() {
  local release="$1" site="$release/site"
  mkdir -p "$STATE_DIR" "$FALLBACK_DIR"
  chown elite:www-data "$STATE_DIR"
  chmod 0750 "$STATE_DIR"
  install -m 0644 "$site/deploy/fallback.html" "$FALLBACK_DIR/index.html"
  install -m 0755 "$site/deploy/update.sh" /usr/local/sbin/elite-update
  install -m 0755 "$site/deploy/rollback.sh" /usr/local/sbin/elite-rollback
  [ -f "$site/deploy/configure-telegram.sh" ] && install -m 0755 "$site/deploy/configure-telegram.sh" /usr/local/sbin/elite-configure-telegram
  [ -f "$site/deploy/security-smoke.sh" ] && install -m 0755 "$site/deploy/security-smoke.sh" /usr/local/sbin/elite-security-smoke
  [ -f "$site/deploy/backup-leads.sh" ] && install -m 0755 "$site/deploy/backup-leads.sh" /usr/local/sbin/elite-backup-leads

  install -m 0644 "$site/deploy/elite.service" /etc/systemd/system/elite.service
  [ -f "$site/deploy/elite-bot.service" ] && install -m 0644 "$site/deploy/elite-bot.service" /etc/systemd/system/elite-bot.service
  [ -f "$site/deploy/elite-autodeploy.service" ] && install -m 0644 "$site/deploy/elite-autodeploy.service" /etc/systemd/system/elite-autodeploy.service
  [ -f "$site/deploy/elite-autodeploy.timer" ] && install -m 0644 "$site/deploy/elite-autodeploy.timer" /etc/systemd/system/elite-autodeploy.timer
  [ -f "$site/deploy/elite-backup.service" ] && install -m 0644 "$site/deploy/elite-backup.service" /etc/systemd/system/elite-backup.service
  [ -f "$site/deploy/elite-backup.timer" ] && install -m 0644 "$site/deploy/elite-backup.timer" /etc/systemd/system/elite-backup.timer

  domain="$(sed -n 's/^SITE_DOMAIN=//p' /etc/elite/elite.env | tail -n 1)"
  [ -n "$domain" ]
  nginx_template="$site/deploy/nginx.conf.template"
  if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
    nginx_template="$site/deploy/nginx.https.conf.template"
  fi
  sed "s/__DOMAIN__/$domain/g" "$nginx_template" >/etc/nginx/sites-available/elite
  ln -sfn /etc/nginx/sites-available/elite /etc/nginx/sites-enabled/elite
  rm -f /etc/nginx/sites-enabled/default

  systemctl daemon-reload
  nginx -t
  systemctl enable nginx >/dev/null 2>&1 || true
  [ -f /etc/systemd/system/elite-autodeploy.timer ] && systemctl enable --now elite-autodeploy.timer >/dev/null 2>&1 || true
  [ -f /etc/systemd/system/elite-backup.timer ] && systemctl enable --now elite-backup.timer >/dev/null 2>&1 || true
}

build_release() {
  local target="$1" release="$2"
  if [ -d "$release/site" ] && [ -x "$release/venv/bin/python" ]; then
    echo "Release ${target:0:7} already prepared"
    return
  fi

  rm -rf "$release"
  install -d -o elite -g elite "$release"
  echo "Materializing candidate ${target:0:7}..."
  runuser -u elite -- bash -c "git -C '$REPO' archive '$target' site | tar -x -C '$release'"
  runuser -u elite -- python3 -m venv "$release/venv"
  runuser -u elite -- "$release/venv/bin/pip" install --upgrade pip
  runuser -u elite -- "$release/venv/bin/pip" install -r "$release/site/requirements.txt"

  "$release/venv/bin/python" -m py_compile "$release/site/app.py" "$release/site/wsgi.py" "$release/site/bot.py"
  echo "Running security/regression tests against candidate..."
  (
    cd "$release/site"
    PYTHONPATH="$release/site" "$release/venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
  )

  echo "Starting isolated candidate smoke test on 127.0.0.1:${CANDIDATE_PORT}..."
  runuser -u elite -- sh -c "exec env SITE_ENV=staging SITE_DOMAIN=localhost SITE_INDEXABLE=false LEADS_DB_PATH='$TMP_DIR/candidate.sqlite3' '$release/venv/bin/gunicorn' --chdir '$release/site' --workers 1 --bind 127.0.0.1:${CANDIDATE_PORT} --access-logfile /dev/null --error-logfile '$TMP_DIR/candidate.log' wsgi:app" &
  candidate_pid=$!
  candidate_ok=0
  for _ in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:${CANDIDATE_PORT}/healthz" >/dev/null 2>&1; then
      candidate_ok=1
      break
    fi
    sleep 0.5
  done
  kill "$candidate_pid" >/dev/null 2>&1 || true
  wait "$candidate_pid" 2>/dev/null || true
  if [ "$candidate_ok" -ne 1 ]; then
    echo "Candidate healthcheck failed:" >&2
    cat "$TMP_DIR/candidate.log" >&2 || true
    return 1
  fi
}

restore_old_release() {
  if [ "$SWITCHED" -eq 1 ] && [ -n "$OLD_RELEASE" ] && [ -d "$OLD_RELEASE" ]; then
    echo "Activation failed; atomically restoring $(basename "$OLD_RELEASE" | cut -c1-7)" >&2
    atomic_link "$OLD_RELEASE" "$CURRENT"
    install_runtime "$OLD_RELEASE" || true
    systemctl restart elite.service || true
    token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' /etc/elite/elite.env | tail -n 1)"
    [ -n "$token" ] && systemctl restart elite-bot.service >/dev/null 2>&1 || true
    systemctl reload nginx || true
  fi
}
trap 'status=$?; if [ $status -ne 0 ]; then restore_old_release; fi; rm -rf -- "$TMP_DIR"; exit $status' EXIT

mkdir -p "$RELEASES" "$STATE_DIR" "$FALLBACK_DIR"
chown elite:elite "$RELEASES"

git_elite fetch --prune origin sitest
TARGET="$(git_elite rev-parse origin/sitest)"
RELEASE="$RELEASES/$TARGET"
CURRENT_SHA=""
if [ -L "$CURRENT" ]; then
  OLD_RELEASE="$(readlink -f "$CURRENT")"
  CURRENT_SHA="$(basename "$OLD_RELEASE")"
fi

if [ "$TARGET" = "$CURRENT_SHA" ]; then
  echo "ELITE already on ${TARGET:0:7}; verifying current release"
  (
    cd "$CURRENT/site"
    PYTHONPATH="$CURRENT/site" "$CURRENT/venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
  )
  install_runtime "$CURRENT"
  exit 0
fi

build_release "$TARGET" "$RELEASE"

if [ -n "$OLD_RELEASE" ] && [ -d "$OLD_RELEASE" ]; then
  atomic_link "$OLD_RELEASE" "$PREVIOUS"
fi
atomic_link "$RELEASE" "$CURRENT"
SWITCHED=1

install_runtime "$RELEASE"
systemctl enable --now elite.service
systemctl restart elite.service
systemctl reload nginx
curl --retry 12 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null

token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' /etc/elite/elite.env | tail -n 1)"
if [ -n "$token" ] && [ -f /etc/systemd/system/elite-bot.service ]; then
  systemctl enable --now elite-bot.service
  systemctl restart elite-bot.service
  systemctl is-active --quiet elite-bot.service
fi

domain="$(sed -n 's/^SITE_DOMAIN=//p' /etc/elite/elite.env | tail -n 1)"
if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ] && [ -x /usr/local/sbin/elite-security-smoke ]; then
  /usr/local/sbin/elite-security-smoke "$domain"
fi

printf '%s\n' "$TARGET" >"$STATE_DIR/deployed-sha"
if [ -n "$CURRENT_SHA" ]; then printf '%s\n' "$CURRENT_SHA" >"$STATE_DIR/previous-sha"; fi
chown elite:www-data "$STATE_DIR"/*-sha 2>/dev/null || true
chmod 0640 "$STATE_DIR"/*-sha 2>/dev/null || true
SWITCHED=0

# Keep current + previous + at most two additional releases for fast/manual recovery.
current_real="$(readlink -f "$CURRENT")"
previous_real="$(readlink -f "$PREVIOUS" 2>/dev/null || true)"
mapfile -t candidates < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
kept_extra=0
for dir in "${candidates[@]}"; do
  if [ "$dir" = "$current_real" ] || [ "$dir" = "$previous_real" ]; then continue; fi
  kept_extra=$((kept_extra + 1))
  if [ "$kept_extra" -gt 2 ]; then rm -rf -- "$dir"; fi
done

echo "ELITE activated ${TARGET:0:7}; previous ${CURRENT_SHA:0:7}; fallback and rollback ready"
