#!/usr/bin/env bash
set -euo pipefail

DB=/var/lib/elite/leads.sqlite3
BACKUPS=/var/backups/elite
KEEP_DAYS=30

mkdir -p "$BACKUPS"
chmod 0700 "$BACKUPS"

if [ ! -f "$DB" ]; then
  echo "No leads database yet; nothing to back up."
  exit 0
fi

ts="$(date -u +%Y%m%dT%H%M%SZ)"
python3 - "$DB" "$BACKUPS/leads-$ts.sqlite3" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
chmod 0600 "$BACKUPS/leads-$ts.sqlite3"
find "$BACKUPS" -type f -name 'leads-*.sqlite3' -mtime +"$KEEP_DAYS" -delete
sha256sum "$BACKUPS/leads-$ts.sqlite3" > "$BACKUPS/leads-$ts.sqlite3.sha256"
chmod 0600 "$BACKUPS/leads-$ts.sqlite3.sha256"
echo "Lead DB backup created: leads-$ts.sqlite3"
