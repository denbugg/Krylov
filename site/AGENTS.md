# ELITE site — agent operating contract

Scope: ONLY `site/` on branch `sitest` of `denbugg/Krylov`. Do not modify Krylov application files outside `site/` unless the user explicitly authorizes a root-level GitHub Actions workflow.

Source of truth: this repository/branch. Production server deploys branch `sitest` with Git sparse-checkout of `site/`.

Read first: `docs/PRODUCT.md`, `docs/DESIGN.md`, `docs/SEO_GEO.md`, `docs/INFRASTRUCTURE.md`, `docs/DEPLOYMENT.md`, `docs/SECURITY.md`.

Rules:
- Preserve the current cinematic ELITE landing unless the task explicitly asks for product/design changes.
- Mobile 390px and desktop 1440px must both be checked after visual changes.
- No secrets in git. `.env` is ignored; production secrets live in `/etc/elite/elite.env` or GitHub Actions secrets.
- Never request the user's root password in chat. Prefer SSH keys.
- Do not enable `index,follow` until the real domain resolves, HTTPS works, and the user says production is ready.
- Do not use fake reviews, fake addresses, unsupported medical claims, or remnants of the Pirouette brand.
- Keep one-hall scope.
- Before deployment-changing work, state the exact command/action and rollback.

Current infrastructure target: REG.RU VPS, Ubuntu 24.04 LTS, Nginx -> Gunicorn -> Flask.
