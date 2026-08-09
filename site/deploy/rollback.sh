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
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  TARGET="$(cat "$STATE_DIR/previous-sha")"
fi

runuser -u elite -- git -C "$REPO" cat-file -e "$TARGET^{commit}"
CURRENT="$(runuser -u elite -- git -C "$REPO" rev-parse HEAD)"
runuser -u elite -- git -C "$REPO" reset --hard "$TARGET"
runuser -u elite -- git -C "$REPO" sparse-checkout set site
"$VENV/bin/python" -m py_compile "$SITE/app.py" "$SITE/wsgi.py"
"$VENV/bin/pip" install -r "$SITE/requirements.txt"

domain="$(sed -n 's/^SITE_DOMAIN=//p' /etc/elite/elite.env | tail -n 1)"
[ -n "$domain" ]
nginx_template="$SITE/deploy/nginx.conf.template"
if [ -f "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
  nginx_template="$SITE/deploy/nginx.https.conf.template"
fi
sed "s/__DOMAIN__/$domain/g" "$nginx_template" >/etc/nginx/sites-available/elite
install -m 0644 "$SITE/deploy/elite.service" /etc/systemd/system/elite.service
systemctl daemon-reload
nginx -t
systemctl restart elite
systemctl reload nginx
curl --retry 8 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/healthz >/dev/null

printf '%s\n' "$CURRENT" >"$STATE_DIR/previous-sha"
printf '%s\n' "$TARGET" >"$STATE_DIR/deployed-sha"
echo "ELITE rolled back to $(runuser -u elite -- git -C "$REPO" rev-parse --short HEAD)"
