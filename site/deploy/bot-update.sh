#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

UPDATE_LOCK=/run/elite-bot-update.lock
exec 9>"$UPDATE_LOCK"
if ! flock -n 9; then
  echo "Another ELITE bot deploy is already running; skipping."
  exit 0
fi

REPO=/srv/elite-bot/repo
RELEASES=/srv/elite-bot/releases
CURRENT=/srv/elite-bot/current
PREVIOUS=/srv/elite-bot/previous
STATE_DIR=/var/lib/elite
ENV_FILE=/etc/elite/elite.env
TMP_DIR="$(mktemp -d /tmp/elite-bot-update.XXXXXX)"
SWITCHED=0
OLD_RELEASE=""
DEPLOYED_SHA=""

chown elite:elite "$TMP_DIR"
chmod 0700 "$TMP_DIR"

bot_git() {
  runuser -u elite -- git -C "$REPO" "$@"
}

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" 2>/dev/null | tail -n 1
}

run_bot_check() {
  local release="$1"
  local token
  local encryption_key
  local db_path
  token="$(env_value TELEGRAM_BOT_TOKEN)"
  encryption_key="$(env_value LEADS_ENCRYPTION_KEY)"
  db_path="$(env_value LEADS_DB_PATH)"
  db_path="${db_path:-/var/lib/elite/leads.sqlite3}"
  runuser -u elite -- env \
    TELEGRAM_BOT_TOKEN="$token" \
    LEADS_ENCRYPTION_KEY="$encryption_key" \
    LEADS_DB_PATH="$db_path" \
    SITE_ENV=production \
    PYTHONPATH="$release/site" \
    "$release/venv/bin/python" "$release/site/bot.py" --check
}

run_db_migration() {
  local release="$1"
  local db_path
  db_path="$(env_value LEADS_DB_PATH)"
  db_path="${db_path:-/var/lib/elite/leads.sqlite3}"
  runuser -u elite -- env LEADS_DB_PATH="$db_path" \
    "$release/venv/bin/python" "$release/site/deploy/migrate-bot-db.py"
}

atomic_link() {
  local target="$1"
  local link="$2"
  local tmp="${link}.new"
  ln -sfn "$target" "$tmp"
  mv -Tf "$tmp" "$link"
}

install_runtime() {
  local release="$1"
  local site="${release}/site"
  install -m 0755 "$site/deploy/bot-update.sh" /usr/local/sbin/elite-bot-update
  install -m 0755 "$site/deploy/configure-telegram.sh" /usr/local/sbin/elite-configure-telegram
  install -m 0644 "$site/deploy/elite-bot.service" /etc/systemd/system/elite-bot.service
  install -m 0644 "$site/deploy/elite-bot-autodeploy.service" /etc/systemd/system/elite-bot-autodeploy.service
  install -m 0644 "$site/deploy/elite-bot-autodeploy.timer" /etc/systemd/system/elite-bot-autodeploy.timer
  systemctl daemon-reload
  systemctl enable --now elite-bot-autodeploy.timer >/dev/null 2>&1 || true
}

build_release() {
  local target="$1"
  local release="$2"
  if [ -f "$release/.prepared" ] && [ -x "$release/venv/bin/python" ]; then
    echo "Bot release ${target:0:7} already prepared"
    return
  fi

  rm -rf "$release"
  install -d -o elite -g elite "$release"
  echo "Materializing bot candidate ${target:0:7}..."
  runuser -u elite -- bash -c "git -C '$REPO' archive '$target' site | tar -x -C '$release'"
  runuser -u elite -- python3 -m venv "$release/venv"
  runuser -u elite -- "$release/venv/bin/pip" install --upgrade pip
  runuser -u elite -- "$release/venv/bin/pip" install -r "$release/site/requirements.txt"
  "$release/venv/bin/python" -m py_compile "$release/site/bot.py"

  echo "Running bot/site regression tests..."
  (
    cd "$release/site"
    PYTHONPATH="$release/site" "$release/venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
  )

  touch "$release/.prepared"
  chown elite:elite "$release/.prepared"
}

restore_old_release() {
  if [ "$SWITCHED" -ne 1 ]; then
    return
  fi
  if [ -n "$OLD_RELEASE" ] && [ -d "$OLD_RELEASE" ]; then
    echo "Bot activation failed; restoring $(basename "$OLD_RELEASE" | cut -c1-7)" >&2
    atomic_link "$OLD_RELEASE" "$CURRENT"
    install_runtime "$OLD_RELEASE" || true
    token="$(env_value TELEGRAM_BOT_TOKEN)"
    [ -n "$token" ] && systemctl restart elite-bot.service >/dev/null 2>&1 || true
  else
    rm -f "$CURRENT"
    systemctl stop elite-bot.service >/dev/null 2>&1 || true
  fi
}
trap 'status=$?; if [ $status -ne 0 ]; then restore_old_release; fi; rm -rf -- "$TMP_DIR"; exit $status' EXIT

mkdir -p "$RELEASES" "$STATE_DIR"
chown elite:elite "$RELEASES"

bot_git fetch --prune origin elite-bot
TARGET="$(bot_git rev-parse origin/elite-bot)"
RELEASE="$RELEASES/$TARGET"
DEPLOYED_SHA="$(cat "$STATE_DIR/bot-deployed-sha" 2>/dev/null || true)"
if [ -n "$DEPLOYED_SHA" ] && [ -f "$RELEASES/$DEPLOYED_SHA/.prepared" ]; then
  OLD_RELEASE="$RELEASES/$DEPLOYED_SHA"
fi

if [ "$TARGET" = "$DEPLOYED_SHA" ] && [ -n "$OLD_RELEASE" ]; then
  echo "ELITE bot already on ${TARGET:0:7}; verifying"
  (
    cd "$CURRENT/site"
    PYTHONPATH="$CURRENT/site" "$CURRENT/venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
  )
  install_runtime "$CURRENT"
  run_db_migration "$CURRENT"
  token="$(env_value TELEGRAM_BOT_TOKEN)"
  if [ -n "$token" ]; then
    systemctl enable --now elite-bot.service >/dev/null 2>&1
    systemctl restart elite-bot.service
    run_bot_check "$CURRENT"
    systemctl is-active --quiet elite-bot.service
  fi
  exit 0
fi

build_release "$TARGET" "$RELEASE"
if [ -n "$OLD_RELEASE" ]; then
  atomic_link "$OLD_RELEASE" "$PREVIOUS"
else
  rm -f "$PREVIOUS"
fi
atomic_link "$RELEASE" "$CURRENT"
SWITCHED=1
install_runtime "$RELEASE"
run_db_migration "$RELEASE"

token="$(env_value TELEGRAM_BOT_TOKEN)"
if [ -n "$token" ]; then
  systemctl enable --now elite-bot.service >/dev/null 2>&1
  systemctl restart elite-bot.service
  run_bot_check "$CURRENT"
  systemctl is-active --quiet elite-bot.service
else
  echo "Telegram token is not configured yet; bot code deployed but service remains stopped."
  systemctl stop elite-bot.service >/dev/null 2>&1 || true
fi

printf '%s\n' "$TARGET" >"$STATE_DIR/bot-deployed-sha"
if [ -n "$DEPLOYED_SHA" ]; then
  printf '%s\n' "$DEPLOYED_SHA" >"$STATE_DIR/bot-previous-sha"
else
  rm -f "$STATE_DIR/bot-previous-sha"
fi
chown elite:www-data "$STATE_DIR"/bot-*-sha 2>/dev/null || true
chmod 0640 "$STATE_DIR"/bot-*-sha 2>/dev/null || true
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

echo "ELITE bot activated ${TARGET:0:7}; previous ${DEPLOYED_SHA:0:7}"
