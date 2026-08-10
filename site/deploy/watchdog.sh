#!/usr/bin/env bash
set -euo pipefail

HEALTH=http://127.0.0.1:8000/healthz
LOCK=/run/elite-watchdog.lock

exec 9>"$LOCK"
flock -n 9 || exit 0

if curl -fsS --max-time 3 "$HEALTH" >/dev/null 2>&1; then
  exit 0
fi

echo "ELITE watchdog: healthcheck failed; restarting application" >&2
systemctl restart elite.service
sleep 4

if curl -fsS --max-time 3 "$HEALTH" >/dev/null 2>&1; then
  echo "ELITE watchdog: application recovered after restart"
  exit 0
fi

if [ -L /srv/elite/previous ] && [ -d "$(readlink -f /srv/elite/previous)" ]; then
  echo "ELITE watchdog: restart failed; rolling back to prepared previous release" >&2
  /usr/local/sbin/elite-rollback
  exit 0
fi

echo "ELITE watchdog: no previous release available; Nginx fallback remains active" >&2
exit 1
