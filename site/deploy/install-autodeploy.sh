#!/usr/bin/env bash
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi
SITE=/srv/elite/site
install -m 0644 "$SITE/deploy/elite-autodeploy.service" /etc/systemd/system/elite-autodeploy.service
install -m 0644 "$SITE/deploy/elite-autodeploy.timer" /etc/systemd/system/elite-autodeploy.timer
systemctl daemon-reload
systemctl enable --now elite-autodeploy.timer
systemctl start elite-autodeploy.service
systemctl --no-pager status elite-autodeploy.timer || true
