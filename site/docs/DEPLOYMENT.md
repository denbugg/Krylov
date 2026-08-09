# Deployment runbook

Agent must first ask user for: real domain, public VPS IPv4, and whether DNS is managed in REG.RU. Never ask for passwords in chat.

1. Confirm Ubuntu 24.04 and server public IP.
2. Establish SSH-key access. Create/use non-root deploy path where practical.
3. Point DNS A records for root and `www` to VPS. Do not remove unrelated DNS records.
4. Clone branch `sitest` and sparse-checkout `site/`.
5. Run/adapt `deploy/server-bootstrap.sh`.
6. Validate local `/healthz` and HTTP through Nginx.
7. Activate HTTPS. User currently has a free REG.RU DomainSSL for six months; install it if convenient/already issued. Let’s Encrypt is an acceptable later zero-cost replacement. Avoid accidental paid auto-renewal.
8. Verify redirects/canonical/OG and only then enable production indexing.
9. Set up automated deployment with rollback. Preferred: GitHub Actions -> SSH deploy key/user -> `deploy/update.sh` or release-based equivalent.
10. Verify desktop 1440 and mobile 390, no horizontal overflow, JS errors, health endpoint, SSL chain.

Rollback minimum: record current commit SHA before update; `git reset --hard <known-good-sha>`, reinstall requirements if changed, restart service, run healthcheck.
