# Deployment handoff — mobile/conversion rebuild

Target feature branch: `site-mobile-conversion-fix`.
Production branch after approval: `sitest`.
Authorized scope: `site/` plus server runtime configuration. Do not touch Krylov application code outside `site/`.

## What is already implemented
- Landing rebuilt mobile-first; no home header and no cinematic/video scroll animation.
- Sticky enrollment CTA appears only after the hero leaves the viewport.
- Official `Elite` script wordmark was converted from the supplied `Логотип_мой.cdr` into `site/static/assets/elite-wordmark.svg`.
- Pirouette branding removed from the article template.
- Polechka block is compact and mobile-safe, with paths to cartoons, warm-up/home activities, games/coloring and children's drawings. Do not invent product imagery; real owned sticker/album/drawing files can be added later.
- Callback form POSTs to `/api/leads`; leads persist in SQLite at `/var/lib/elite/leads.sqlite3`.
- `/api/admin/leads` is protected by `Authorization: Bearer <ADMIN_TOKEN>` and is an interim inspection endpoint until CRM/bot admin is ready.
- Privacy/consent pages added.
- Telegram default contact: `https://t.me/Undina_007`; phone: `+7 (916) 965-35-13`.
- Telegram/MAX bot architecture is in `site/docs/BOT_PLAN.md`.

## Deployment sequence
1. Review `git diff sitest...site-mobile-conversion-fix`. Do not redesign it during deployment.
2. Run Python syntax/Jinja/template checks and verify every referenced static asset exists.
3. Merge the feature branch into `sitest` only after those checks pass.
4. On VPS update `/etc/elite/elite.env` without putting secrets into Git:
   - `SITE_ENV=production`
   - `SITE_DOMAIN=rgelite.ru`
   - `SITE_SCHEME=https`
   - `SITE_ADDRESS=Москва, Боровское шоссе, 43, этаж 3`
   - `SITE_MAP_QUERY` must be adjusted to the exact Yandex Maps entity/address that produces a visible pin.
   - `SITE_TELEGRAM_URL=https://t.me/Undina_007` until Telegram bot replaces it.
   - `SITE_PHONE_DISPLAY=+7 (916) 965-35-13`
   - `SITE_PHONE_E164=+79169653513`
   - `LEADS_DB_PATH=/var/lib/elite/leads.sqlite3`
   - generate a high-entropy `ADMIN_TOKEN`; never paste it into Git.
   - leave `SITE_MAX_URL` blank until the real MAX bot/contact URL exists.
5. Run `sudo /usr/local/sbin/elite-update`. Confirm the systemd unit now owns a writable `/var/lib/elite` state directory.
6. Submit a test callback lead from the public site; verify it is saved in SQLite and retrievable only with the admin token.
7. Verify Telegram and phone links on iPhone-sized viewport. MAX should not show as an active external link until configured.

## SSL/security
- Inspect the certificate actually served by `rgelite.ru` and `www.rgelite.ru`: issuer, SANs, expiry and full chain.
- If a valid auto-renewing Let's Encrypt certificate is already installed, do not replace it merely because a REG.RU DomainSSL email exists. If the user wants to use the free DomainSSL, first verify its issued status and installation requirements, then migrate without downtime.
- Confirm automatic renewal for the certificate that remains in production and make sure paid DomainSSL auto-renewal is not accidentally enabled.
- Verify HTTPS redirect, TLS config, HSTS only after HTTPS is stable, CSP, no Flask debug, UFW, service permissions and `/healthz`.

## Yandex Maps / local discovery
The current generic map search is not enough if it does not show a visible ELITE marker.
1. In Yandex Business, search for the organization. If absent, create ELITE; if present, claim/verify ownership.
2. Set exact public address, phone, `https://rgelite.ru`, category/activity, hours and real club photos. The organization profile is what should create the real Maps/Search entity and pin.
3. After moderation, use the exact organization/coordinates in the site map embed and verify a visible marker on mobile.
4. Do not fake coordinates or another organization's marker.

## Yandex Webmaster / indexing
1. Add/verify `https://rgelite.ru` in Yandex Webmaster.
2. Confirm public production returns indexable HTML: no `noindex`, no `X-Robots-Tag: noindex`, and `robots.txt` allows crawling.
3. Submit `https://rgelite.ru/sitemap.xml`.
4. Send the homepage and article for reindexing and inspect their URL status.
5. Connect/complete Yandex Business because local Maps/Search visibility is separate from ordinary technical SEO.
6. Do not promise immediate ranking for `художественная гимнастика в Переделкино`; report indexed/not-indexed status and observed search position separately.

## QA gates
Minimum viewports: 390x844 (iPhone 13 class) and 1440x1000.
- `document.documentElement.scrollWidth === clientWidth`.
- No clipped H1 or section headings.
- No header on home landing.
- No cinematic/wow animation.
- Sticky CTA invisible over the initial hero; visible after hero exit.
- Polechka horizontal cards do not overflow the page itself (internal horizontal scroll is intentional on mobile).
- Contact sheet fits inside `100svh` and scrolls internally if needed.
- Callback form succeeds and failure state points to Telegram.
- Article has only ELITE branding; no Pirouette references/assets.
- Map has a visible, correct ELITE marker after Yandex Business/entity setup.
- No console errors, broken images or 404 assets.
- HTTPS/healthcheck/rollback all pass.

## After this release
Build the Telegram bot first, then MAX using `site/docs/BOT_PLAN.md`. Replace the website Telegram direct link with a bot deep link when the bot MVP is ready. CRM integration comes after both website and messenger lead flows are stable.
