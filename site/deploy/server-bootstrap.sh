#!/usr/bin/env bash
set -euo pipefail

# Run as root on Ubuntu 24.04.
# Required env: DOMAIN. Optional values below may be exported before running.
: "${DOMAIN:?set DOMAIN}"
: "${GIT_REPO_SSH:=https://github.com/denbugg/Krylov.git}"
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

apt-get update
apt-get install -y git nginx python3-venv python3-pip ufw curl

id -u elite >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash elite
mkdir -p /srv/elite /etc/elite /var/lib/elite
chown -R elite:elite /srv/elite
chown elite:www-data /var/lib/elite
chmod 0750 /var/lib/elite

if [ ! -d /srv/elite/repo/.git ]; then
  sudo -u elite git clone --filter=blob:none --no-checkout --branch sitest "$GIT_REPO_SSH" /srv/elite/repo
  sudo -u elite git -C /srv/elite/repo sparse-checkout init --cone
  sudo -u elite git -C /srv/elite/repo sparse-checkout set site
  sudo -u elite git -C /srv/elite/repo checkout sitest
fi
chown -R elite:elite /srv/elite/repo
ln -sfn /srv/elite/repo/site /srv/elite/site

python3 -m venv /srv/elite/venv
/srv/elite/venv/bin/pip install --upgrade pip
/srv/elite/venv/bin/pip install -r /srv/elite/site/requirements.txt

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

sed "s/__DOMAIN__/$DOMAIN/g" /srv/elite/site/deploy/nginx.conf.template >/etc/nginx/sites-available/elite
ln -sfn /etc/nginx/sites-available/elite /etc/nginx/sites-enabled/elite
rm -f /etc/nginx/sites-enabled/default

install -m 0644 /srv/elite/site/deploy/elite.service /etc/systemd/system/elite.service
install -m 0644 /srv/elite/site/deploy/elite-bot.service /etc/systemd/system/elite-bot.service
install -m 0644 /srv/elite/site/deploy/elite-autodeploy.service /etc/systemd/system/elite-autodeploy.service
install -m 0644 /srv/elite/site/deploy/elite-autodeploy.timer /etc/systemd/system/elite-autodeploy.timer
install -m 0755 /srv/elite/site/deploy/update.sh /usr/local/sbin/elite-update
install -m 0755 /srv/elite/site/deploy/rollback.sh /usr/local/sbin/elite-rollback

systemctl daemon-reload
systemctl enable --now elite
systemctl enable --now elite-autodeploy.timer
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  systemctl enable --now elite-bot
fi
nginx -t
systemctl reload nginx

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

curl -fsS http://127.0.0.1:8000/healthz
echo
echo "Bootstrap OK. Next: point DNS A records, activate HTTPS, then verify https://$DOMAIN/healthz"
