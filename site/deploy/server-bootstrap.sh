#!/usr/bin/env bash
set -euo pipefail

# Run as root on Ubuntu 24.04.
# Required env: DOMAIN. Optional: GIT_REPO_SSH, SITE_ENV, SITE_INDEXABLE.
: "${DOMAIN:?set DOMAIN}"
: "${GIT_REPO_SSH:=https://github.com/denbugg/Krylov.git}"
: "${SITE_ENV:=staging}"
: "${SITE_INDEXABLE:=false}"
: "${SITE_ADDRESS:=Москва, Боровское шоссе, 43, этаж 3}"
: "${SITE_MAP_QUERY:=Москва, Боровское шоссе, 43}"
: "${SITE_TELEGRAM_URL:=}"
: "${SITE_MAX_URL:=}"
: "${SITE_PHONE_DISPLAY:=}"
: "${SITE_PHONE_E164:=}"

apt-get update
apt-get install -y git nginx python3-venv python3-pip ufw curl

id -u elite >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash elite
mkdir -p /srv/elite /etc/elite
chown -R elite:elite /srv/elite

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
PORT=8000
EOF
chmod 600 /etc/elite/elite.env

sed "s/__DOMAIN__/$DOMAIN/g" /srv/elite/site/deploy/nginx.conf.template >/etc/nginx/sites-available/elite
ln -sfn /etc/nginx/sites-available/elite /etc/nginx/sites-enabled/elite
rm -f /etc/nginx/sites-enabled/default
cp /srv/elite/site/deploy/elite.service /etc/systemd/system/elite.service
install -m 0755 /srv/elite/site/deploy/update.sh /usr/local/sbin/elite-update
install -m 0755 /srv/elite/site/deploy/rollback.sh /usr/local/sbin/elite-rollback
mkdir -p /var/lib/elite

systemctl daemon-reload
systemctl enable --now elite
nginx -t
systemctl reload nginx

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

curl -fsS http://127.0.0.1:8000/healthz
echo
echo "Bootstrap OK. Next: point DNS A records to this server, activate/install SSL, then verify https://$DOMAIN/healthz"
