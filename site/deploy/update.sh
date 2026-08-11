#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

# Prevent a manual deploy from racing the systemd autodeploy timer or watchdog.
UPDATE_LOCK=/run/elite-update.lock
exec 9>"$UPDATE_LOCK"
if ! flock -n 9; then
  echo "Another ELITE deploy/watchdog operation is already running; skipping."
  exit 0
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
DEPLOYED_SHA=""

chown elite:elite "$TMP_DIR"
chmod 0700 "$TMP_DIR"

git_elite() {
  runuser -u elite -- git -C "$REPO" "$@"
}

atomic_link() {
  local target="$1"
  local link="$2"
  local tmp="${link}.new"
  ln -sfn "$target" "$tmp"
  mv -Tf "$tmp" "$link"
}

ensure_env_secret() {
  local key="$1"
  local env_file=/etc/elite/elite.env
  local current
  current="$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)"
  if [ -n "$current" ]; then
    return
  fi
  local value
  value="$(python3 - "$key" <<'PY'
import base64
import secrets
import sys

key = sys.argv[1]
if key == "LEADS_ENCRYPTION_KEY":
    print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))
else:
    print(secrets.token_urlsafe(32))
PY
)"
  if grep -q "^${key}=" "$env_file"; then
    python3 - "$env_file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
out = [f"{key}={value}" if line.startswith(key + "=") else line for line in lines]
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  else
    printf '%s=%s\n' "$key" "$value" >>"$env_file"
  fi
  chmod 600 "$env_file"
  chown root:root "$env_file"
  echo "Generated server-only $key"
}

install_runtime() {
  local release="$1"
  local site="${release}/site"
  mkdir -p "$STATE_DIR" "$FALLBACK_DIR"
  chown elite:www-data "$STATE_DIR"
  chmod 0750 "$STATE_DIR"

  ensure_env_secret LEADS_ENCRYPTION_KEY
  ensure_env_secret IP_HASH_SALT

  install -m 0644 "$site/deploy/fallback.html" "$FALLBACK_DIR/index.html"
  install -m 0755 "$site/deploy/update.sh" /usr/local/sbin/elite-update
  install -m 0755 "$site/deploy/rollback.sh" /usr/local/sbin/elite-rollback
  [ -f "$site/deploy/security-smoke.sh" ] && install -m 0755 "$site/deploy/security-smoke.sh" /usr/local/sbin/elite-security-smoke
  [ -f "$site/deploy/backup-leads.sh" ] && install -m 0755 "$site/deploy/backup-leads.sh" /usr/local/sbin/elite-backup-leads
  [ -f "$site/deploy/watchdog.sh" ] && install -m 0755 "$site/deploy/watchdog.sh" /usr/local/sbin/elite-watchdog

  install -m 0644 "$site/deploy/elite.service" /etc/systemd/system/elite.service
  [ -f "$site/deploy/elite-autodeploy.service" ] && install -m 0644 "$site/deploy/elite-autodeploy.service" /etc/systemd/system/elite-autodeploy.service
  [ -f "$site/deploy/elite-autodeploy.timer" ] && install -m 0644 "$site/deploy/elite-autodeploy.timer" /etc/systemd/system/elite-autodeploy.timer
  [ -f "$site/deploy/elite-backup.service" ] && install -m 0644 "$site/deploy/elite-backup.service" /etc/systemd/system/elite-backup.service
  [ -f "$site/deploy/elite-backup.timer" ] && install -m 0644 "$site/deploy/elite-backup.timer" /etc/systemd/system/elite-backup.timer
  [ -f "$site/deploy/elite-watchdog.service" ] && install -m 0644 "$site/deploy/elite-watchdog.service" /etc/systemd/system/elite-watchdog.service
  [ -f "$site/deploy/elite-watchdog.timer" ] && install -m 0644 "$site/deploy/elite-watchdog.timer" /etc/systemd/system/elite-watchdog.timer

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
  [ -f /etc/systemd/system/elite-watchdog.timer ] && systemctl enable --now elite-watchdog.timer >/dev/null 2>&1 || true
}

build_release() {
  local target="$1"
  local release="$2"
  if [ -f "$release/.prepared" ] && [ -d "$release/site" ] && [ -x "$release/venv/bin/python" ]; then
    echo "Release ${target:0:7} already prepared and smoke-tested"
    return
  fi

  rm -rf "$release"
  install -d -o elite -g elite "$release"
  echo "Materializing candidate ${target:0:7}..."
  runuser -u elite -- bash -c "git -C '$REPO' archive '$target' site | tar -x -C '$release'"
  runuser -u elite -- python3 -m venv "$release/venv"
  runuser -u elite -- "$release/venv/bin/pip" install --upgrade pip
  runuser -u elite -- "$release/venv/bin/pip" install -r "$release/site/requirements.txt"

  "$release/venv/bin/python" -m py_compile "$release/site/app.py" "$release/site/wsgi.py" "$release/site/bot.py" "$release/site/lead_crypto.py"
  echo "Running security/regression tests against candidate..."
  (
    cd "$release/site"
    PYTHONPATH="$release/site" "$release/venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
  )

  echo "Starting isolated candidate smoke test on 127.0.0.1:${CANDIDATE_PORT}..."
  runuser -u elite -- sh -c "cd '$release/site' && exec env SITE_ENV=staging SITE_DOMAIN=localhost SITE_INDEXABLE=false LEADS_DB_PATH='$TMP_DIR/candidate.sqlite3' '$release/venv/bin/gunicorn' --chdir '$release/site' --workers 1 --bind 127.0.0.1:${CANDIDATE_PORT} --access-logfile /dev/null --error-logfile '$TMP_DIR/candidate.log' wsgi:app" &
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

  touch "$release/.prepared"
  chown elite:elite "$release/.prepared"
}

restore_old_release() {
  if [ "$SWITCHED" -ne 1 ]; then
    return
  fi

  if [ -n "$OLD_RELEASE" ] && [ -d "$OLD_RELEASE" ]; then
    echo "Activation failed; atomically restoring $(basename "$OLD_RELEASE" | cut -c1-7)" >&2
    atomic_link "$OLD_RELEASE" "$CURRENT"
    install_runtime "$OLD_RELEASE" || true
    systemctl restart elite.service || true
    systemctl reload nginx || true
  else
    echo "Activation failed before any successful production release; clearing uncommitted current symlink" >&2
    rm -f "$CURRENT"
    systemctl stop elite.service >/dev/null 2>&1 || true
  fi
}
trap 'status=$?; if [ $status -ne 0 ]; then restore_old_release; fi; rm -rf -- "$TMP_DIR"; exit $status' EXIT

mkdir -p "$RELEASES" "$STATE_DIR" "$FALLBACK_DIR"
chown elite:elite "$RELEASES"

git_elite fetch --prune origin sitest
TARGET="$(git_elite rev-parse origin/sitest)"
RELEASE="$RELEASES/$TARGET"

DEPLOYED_SHA="$(cat "$STATE_DIR/deployed-sha" 2>/dev/null || true)"
if [ -n "$DEPLOYED_SHA" ] && [ -f "$RELEASES/$DEPLOYED_SHA/.prepared" ] && [ -d "$RELEASES/$DEPLOYED_SHA/site" ]; then
  OLD_RELEASE="$RELEASES/$DEPLOYED_SHA"
else
  DEPLOYED_SHA=""
  OLD_RELEASE=""
fi

CURRENT_REAL="$(readlink -f "$CURRENT" 2>/dev/null || true)"
if [ -n "$OLD_RELEASE" ] && [ "$CURRENT_REAL" != "$OLD_RELEASE" ]; then
  echo "Recovering current symlink to last successful release ${DEPLOYED_SHA:0:7}"
  atomic_link "$OLD_RELEASE" "$CURRENT"
elif [ -z "$OLD_RELEASE" ] && [ -L "$CURRENT" ]; then
  echo "Discarding uncommitted current symlink from an interrupted activation"
  rm -f "$CURRENT"
fi

if [ "$TARGET" = "$DEPLOYED_SHA" ]; then
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
else
  rm -f "$PREVIOUS"
fi
atomic_link "$RELEASE" "$CURRENT"
SWITCHED=1

install_runtime "$RELEASE"
systemctl enable --now elite.service
systemctl restart elite.service
systemctl reload nginx
curl --retry 12 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null

domain="$(sed -n 's/^SITE_DOMAIN=//p' /etc/elite/elite.env | tail -n 1)"
if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ] && [ -x /usr/local/sbin/elite-security-smoke ]; then
  /usr/local/sbin/elite-security-smoke "$domain"
fi

printf '%s\n' "$TARGET" >"$STATE_DIR/deployed-sha"
if [ -n "$DEPLOYED_SHA" ]; then
  printf '%s\n' "$DEPLOYED_SHA" >"$STATE_DIR/previous-sha"
else
  rm -f "$STATE_DIR/previous-sha"
fi
chown elite:www-data "$STATE_DIR"/*-sha 2>/dev/null || true
chmod 0640 "$STATE_DIR"/*-sha 2>/dev/null || true
SWITCHED=0

current_real="$(readlink -f "$CURRENT")"
previous_real="$(readlink -f "$PREVIOUS" 2>/dev/null || true)"
mapfile -t candidates < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
kept_extra=0
for dir in "${candidates[@]}"; do
  if [ "$dir" = "$current_real" ] || [ "$dir" = "$previous_real" ]; then continue; fi
  kept_extra=$((kept_extra + 1))
  if [ "$kept_extra" -gt 2 ]; then rm -rf -- "$dir"; fi
done

echo "ELITE activated ${TARGET:0:7}; previous ${DEPLOYED_SHA:0:7}; fallback, watchdog and rollback ready"
