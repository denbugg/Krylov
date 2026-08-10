#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
  echo "Usage: security-smoke.sh DOMAIN" >&2
  exit 2
fi

BASE="https://$DOMAIN"
TMP_HEADERS="$(mktemp)"
trap 'rm -f "$TMP_HEADERS"' EXIT

curl -fsS --max-time 15 "$BASE/healthz" | grep -q '"status":"ok"'
curl -fsSI --max-time 15 "$BASE/" >"$TMP_HEADERS"

grep -qi '^strict-transport-security:' "$TMP_HEADERS"
grep -qi '^x-content-type-options: nosniff' "$TMP_HEADERS"
grep -qi '^referrer-policy: strict-origin-when-cross-origin' "$TMP_HEADERS"
grep -qi '^x-frame-options: SAMEORIGIN' "$TMP_HEADERS"
grep -qi '^content-security-policy:' "$TMP_HEADERS"

# Admin endpoint must not be anonymously readable.
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$BASE/api/admin/leads")"
[ "$code" = "401" ]

# Production pages must not leak secret variable names.
body="$(curl -fsS --max-time 15 "$BASE/")"
! grep -q 'TELEGRAM_BOT_TOKEN' <<<"$body"
! grep -q 'ADMIN_TOKEN' <<<"$body"
! grep -qi 'pirouette\|пируэт' <<<"$body"

# robots/sitemap must be reachable; indexing policy itself remains environment-controlled.
curl -fsS --max-time 15 "$BASE/robots.txt" >/dev/null
curl -fsS --max-time 15 "$BASE/sitemap.xml" >/dev/null

echo "Security smoke OK for $DOMAIN"
