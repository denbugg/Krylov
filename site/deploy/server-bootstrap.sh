#!/usr/bin/env bash
set -euo pipefail

# Clean-server bootstrap for Ubuntu 24.04. Run as root.
# Required env: DOMAIN. Optional values below may be exported before running.
if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

: "${DOMAIN:?set DOMAIN}"
: "${GIT_REPO_URL:=https://github.com/denbugg/Krylov.git}"
: "${SITE_ENV:=staging}"
: "${SITE_INDEXABLE:=false}"
: "${SITE_ADDRESS:=Москва, Боровское шоссе, 43, этаж 3}"
: "${SITE_MAP_QUERY:=Москва, Боровское шоссе, 43}"
: "${SITE_TELEGRAM_URL:=https://t.me/Undina_007}"
: "${TELEGRAM_BOT_USERNAME:=}"
: "${TELEGRAM_BOT_TOKEN:=}"
: "${TELEGRAM_ADMIN_USERNAME:=Undina_007}"
: "${TELEGRAM_ADMIN_CHAT_ID:=}"
: "${SITE_MAX_URL:=}"
: "${SITE_PHONE_DISPLAY:=+7 (916) 965-35-13}"
: "${SITE_PHONE_E164:=+79169653513}"
: "${ADMIN_TOKEN:=}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git nginx python3-venv python3-pip ufw curl ca-certificates certbot python3-certbot-nginx

id -u elite >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash elite
mkdir -p /srv/elite /etc/elite /var/lib/elite
chown -R elite:elite /srv/elite
chown elite:www-data /var/lib/elite
chmod 0750 /var/lib/elite

if [ ! -d /srv/elite/repo/.git ]; then
  runuser -u elite -- git clone --filter=blob:none --no-checkout --branch sitest "$GIT_REPO_URL" /srv/elite/repo
  runuser -u elite -- git -C /srv/elite/repo sparse-checkout init --cone
  runuser -u elite -- git -C /srv/elite/repo sparse-checkout set site
  runuser -u elite -- git -C /srv/elite/repo checkout sitest
else
  runuser -u elite -- git -C /srv/elite/repo fetch --prune origin sitest
  runuser -u elite -- git -C /srv/elite/repo reset --hard origin/sitest
  runuser -u elite -- git -C /srv/elite/repo sparse-checkout set site
fi
chown -R elite:elite /srv/elite/repo
ln -sfn /srv/elite/repo/site /srv/elite/site

python3 -m venv /srv/elite/venv
/srv/elite/venv/bin/pip install --upgrade pip
/srv/elite/venv/bin/pip install -r /srv/elite/site/requirements.txt

# Fail before exposing the first release if tests do not pass.
(
  cd /srv/elite/site
  PYTHONPATH=/srv/elite/site /srv/elite/venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
)

if [ -z "$ADMIN_TOKEN" ]; then
  ADMIN_TOKEN="$(/srv/elite/venv/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
)"
fi

cat >/etc/elite/elite.env <<EOF
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
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_BOT_USERNAME=$TELEGRAM_BOT_USERNAME
TELEGRAM_ADMIN_USERNAME=$TELEGRAM_ADMIN_USERNAME
TELEGRAM_ADMIN_CHAT_ID=$TELEGRAM_ADMIN_CHAT_ID
PORT=8000
EOF
chmod 600 /etc/elite/elite.env
chown root:root /etc/elite/elite.env

sed "s/__DOMAIN__/$DOMAIN/g" /srv/elite/site/deploy/nginx.conf.template >/etc/nginx/sites-available/elite
ln -sfn /etc/nginx/sites-available/elite /etc/nginx/sites-enabled/elite
rm -f /etc/nginx/sites-enabled/default

install -m 0644 /srv/elite/site/deploy/elite.service /etc/systemd/system/elite.service
install -m 0644 /srv/elite/site/deploy/elite-bot.service /etc/systemd/system/elite-bot.service
install -m 0644 /srv/elite/site/deploy/elite-autodeploy.service /etc/systemd/system/elite-autodeploy.service
install -m 0644 /srv/elite/site/deploy/elite-autodeploy.timer /etc/systemd/system/elite-autodeploy.timer
install -m 0755 /srv/elite/site/deploy/update.sh /usr/local/sbin/elite-update
install -m 0755 /srv/elite/site/deploy/rollback.sh /usr/local/sbin/elite-rollback
install -m 0755 /srv/elite/site/deploy/configure-telegram.sh /usr/local/sbin/elite-configure-telegram
install -m 0755 /srv/elite/site/deploy/security-smoke.sh /usr/local/sbin/elite-security-smoke

systemctl daemon-reload
nginx -t
systemctl enable --now elite.service
systemctl enable --now elite-autodeploy.timer
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  systemctl enable --now elite-bot.service
fi
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

curl --retry 8 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null
systemctl is-active --quiet elite.service
systemctl is-active --quiet elite-autodeploy.timer

runuser -u elite -- git -C /srv/elite/repo rev-parse HEAD >/var/lib/elite/deployed-sha
chown elite:www-data /var/lib/elite/deployed-sha
chmod 0640 /var/lib/elite/deployed-sha

echo "Bootstrap OK"
echo "Commit: $(runuser -u elite -- git -C /srv/elite/repo rev-parse --short HEAD)"
echo "Autodeploy timer: active"
echo "Indexing: $SITE_INDEXABLE"
echo "Next: issue/verify HTTPS for $DOMAIN, then enable indexing only after production QA."
