# Bootstrap prompt for the deployment agent

You are taking over deployment and infrastructure for the ELITE website.

Repository: `denbugg/Krylov`
Branch: `sitest`
Authorized project scope: `site/` only. Do not edit the Krylov application outside `site/` unless the user explicitly approves a root-level GitHub Actions workflow.

First read, in order:
1. `site/AGENTS.md`
2. `site/CLAUDE.md`
3. `site/docs/PRODUCT.md`
4. `site/docs/DESIGN.md`
5. `site/docs/SEO_GEO.md`
6. `site/docs/INFRASTRUCTURE.md`
7. `site/docs/DEPLOYMENT.md`
8. `site/docs/SECURITY.md`
9. `site/docs/ASSET_IMPORT.md`

Goal: take the current ELITE site from repository state to a maintainable production deployment on the user's REG.RU VPS, with the real domain, HTTPS, health checking, and a safe update path from GitHub. GitHub branch `sitest` is the source of truth. The VPS must use sparse-checkout so only `site/` is materialized.

At the beginning ask the user only for values actually needed now: DOMAIN and SERVER_IP. Then inspect the environment and proceed autonomously. For authentication/2FA/browser confirmations, instruct the user exactly what to click or enter, then continue. Never request passwords/private keys in chat.

Preferred stack: Ubuntu 24.04 LTS; Nginx; Gunicorn; Flask; systemd; UFW. Use the prepared files under `site/deploy/`, modifying them only when required by the real server/domain.

SSL: the user currently has a free 6-month REG.RU DomainSSL. Use it if practical and already issued; otherwise explain the exact activation/install step. Avoid paid auto-renewal. Let's Encrypt is acceptable as a zero-cost replacement.

Deployment automation target: after first successful manual deployment, create a safe GitHub-based update flow. Prefer a dedicated deploy user/key with least privilege. If adding `.github/workflows/...` at repository root is necessary, STOP and ask explicit permission because authorized scope is currently `site/`.

Before deployment, confirm that the current visual payload has been imported into `site/templates/` and `site/static/`. If it is missing, the user will attach `elite_site_payload.zip` to this Work/Codex session. Its SHA-256 must be `fbc941ce86d11ceb53098f230f43b677ff15f4142f20f1e91a9712d461b08e71`. Verify the hash when possible, extract it to a temporary directory, compare its contents against the existing `site/`, and import only the current visual/templates/assets and any clearly newer site files. Do not blindly overwrite the infrastructure documentation already in the branch. Review `git diff`, then commit the import to `sitest` before deployment.

After the visual payload is committed, do not use ZIP files for routine updates. GitHub branch `sitest` becomes the only source of truth for the site.

Before declaring success verify: DNS; HTTPS; `/healthz`; service survives reboot; Nginx config test; no debug mode; desktop 1440px; mobile 390px; no horizontal overflow; no console errors; correct canonical/robots; actual production domain; rollback procedure tested or documented.

Do not redesign the product while doing infrastructure work.
