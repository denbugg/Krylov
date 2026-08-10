#!/usr/bin/env bash
set -euo pipefail

# Clean-server bootstrap for supported Ubuntu LTS releases. Run as root.
# Required env: DOMAIN. The script prepares only the ELITE site stack.
if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

: "${DOMAIN:?set DOMAIN}"
: "${GIT_REPO_URL:=https://github.com/denbugg/Krylov.git}"
: "${SITE_ENV:=production}"
: "${SITE_INDEXABLE:=false}"
: "${SITE_ADDRESS:=Москва, Боровское шоссе, 43, этаж 3}"
: "${SITE_MAP_QUERY:=Москва, Боровское шоссе, 43}"
: "${SITE_TELEGRAM_URL:=https://t.me/Undina_007}"
: "${SITE_MAX_URL:=}"
: "${SITE_PHONE_DISPLAY:=+7 (916) 965-35-13}"
: "${SITE_PHONE_E164:=+79169653513}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git nginx python3-venv python3-pip ufw curl ca-certificates certbot python3-certbot-nginx

id -u elite >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash elite
mkdir -p /srv/elite/repo /srv/elite/releases /srv/elite/fallback /etc/elite /var/lib/elite /var/backups/elite
chown -R elite:elite /srv/elite/repo /srv/elite/releases
chown elite:www-data /var/lib/elite
chmod 0750 /var/lib/elite
chmod 0700 /var/backups/elite

if [ ! -d /srv/elite/repo/.git ]; then
  rm -rf /srv/elite/repo
  runuser -u elite -- git clone --no-checkout --branch sitest "$GIT_REPO_URL" /srv/elite/repo
  runuser -u elite -- git -C /srv/elite/repo sparse-checkout init --cone
  runuser -u elite -- git -C /srv/elite/repo sparse-checkout set site
  runuser -u elite -- git -C /srv/elite/repo checkout sitest
else
  runuser -u elite -- git -C /srv/elite/repo fetch --prune origin sitest
  runuser -u elite -- git -C /srv/elite/repo reset --hard origin/sitest
  runuser -u elite -- git -C /srv/elite/repo sparse-checkout set site
fi

ENV_FILE=/etc/elite/elite.env
if [ -f "$ENV_FILE" ]; then
  echo "Preserving existing $ENV_FILE (including server-only secrets)."
else
  ADMIN_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
)"

  cat >"$ENV_FILE" <<EOF
SITE_ENV=$SITE_ENV
SITE_DOMAIN=$DOMAIN
SITE_SCHEME=https
SITE_INDEXABLE=$SITE_INDEXABLE
SITE_ADDRESS=$SITE_ADDRESS
SITE_MAP_QUERY=$SITE_MAP_QUERY
SITE_TELEGRAM_URL=$SITE_TELEGRAM_URL
SITE_MAX_URL=$SITE_MAX_URL
SITE_PHONE_DISPLAY=$SITE_PHONE_DISPLAY
SITE_PHONE_E164=$SITE_PHONE_E164
LEADS_DB_PATH=/var/lib/elite/leads.sqlite3
ADMIN_TOKEN=$ADMIN_TOKEN
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_ADMIN_USERNAME=Undina_007
TELEGRAM_ADMIN_CHAT_ID=
PORT=8000
EOF
fi
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

# Put the emergency page in place before starting the application stack.
install -m 0644 /srv/elite/repo/site/deploy/fallback.html /srv/elite/fallback/index.html

# The updater builds an isolated versioned release, runs tests and candidate
# health checks, atomically activates it, installs Nginx/systemd units, and
# enables the autodeploy/backup/watchdog timers.
bash /srv/elite/repo/site/deploy/update.sh

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

systemctl is-active --quiet elite.service
systemctl is-active --quiet elite-autodeploy.timer
systemctl is-active --quiet elite-watchdog.timer
curl --retry 10 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null

echo
echo "Bootstrap OK"
echo "Current release: $(basename "$(readlink -f /srv/elite/current)")"
echo "Autodeploy timer: $(systemctl is-active elite-autodeploy.timer)"
echo "Watchdog timer: $(systemctl is-active elite-watchdog.timer)"
echo "Backup timer: $(systemctl is-active elite-backup.timer 2>/dev/null || echo inactive)"
echo "Indexing: $(sed -n 's/^SITE_INDEXABLE=//p' "$ENV_FILE" | tail -n 1)"
echo "Next: issue/verify HTTPS for $DOMAIN, run security smoke, then enable indexing after production QA."
