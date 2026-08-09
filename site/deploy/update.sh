#!/usr/bin/env bash
set -euo pipefail
cd /srv/elite/repo
PREV="$(git rev-parse HEAD)"
git fetch origin sitest
git reset --hard origin/sitest
git sparse-checkout set site
/srv/elite/venv/bin/pip install -r /srv/elite/site/requirements.txt
systemctl restart elite
if ! curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
  echo "Healthcheck failed; rolling back to $PREV" >&2
  git reset --hard "$PREV"
  /srv/elite/venv/bin/pip install -r /srv/elite/site/requirements.txt
  systemctl restart elite
  exit 1
fi
echo "ELITE updated to $(git rev-parse --short HEAD)"
