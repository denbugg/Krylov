# ELITE deployment runbook

Production domain: `rgelite.ru`. Repository: `denbugg/Krylov`, branch `sitest`, site scope `site/` only.

## Runtime
- Ubuntu 24.04 LTS
- Nginx -> Gunicorn -> Flask
- systemd
- UFW
- Git sparse-checkout materializes only `site/`
- persistent state: `/var/lib/elite`
- server-only environment: `/etc/elite/elite.env`

## Manual safe update

```bash
sudo /usr/local/sbin/elite-update
```

The updater fetches `origin/sitest`, compares the current and remote SHA, and exits without restarting anything when there is no new revision. On a new revision it:
- resets the sparse checkout to the new `sitest` commit;
- compiles the Python entrypoints;
- installs requirements;
- installs current systemd/deploy units;
- validates Nginx;
- restarts the website and, when configured, the Telegram bot;
- checks `/healthz`;
- records the previous SHA;
- automatically restores the previous version if deployment fails.

Manual rollback:

```bash
sudo /usr/local/sbin/elite-rollback
```

or pass a known-good commit SHA.

## Automatic deploy after Git push

GitHub Actions is deliberately not required. Production uses a server-side systemd timer:

- `elite-autodeploy.timer`
- approximately every 2 minutes (plus a small randomized delay)
- runs `elite-autodeploy.service`
- which invokes `/usr/local/sbin/elite-update`

This avoids storing a production SSH private key in GitHub Actions secrets and reuses the repository credentials already configured on the VPS.

### One-time migration from the pre-autodeploy server
The existing production server was created before the timer files existed. After the autodeploy release is merged to `sitest`, run:

```bash
sudo /usr/local/sbin/elite-update
sudo /usr/local/sbin/elite-update
```

The first call is executed by the old updater and pulls the release/new updater. The second call uses the new updater and installs/enables the timer and optional bot unit even though Git is already current. After this one-time step, future pushes to `sitest` are pulled automatically.

Verify:

```bash
systemctl status elite-autodeploy.timer
systemctl list-timers elite-autodeploy.timer
cat /var/lib/elite/deployed-sha
```

## Telegram bot
`elite-bot.service` runs independently of Gunicorn. It stays disabled until `TELEGRAM_BOT_TOKEN` is present in `/etc/elite/elite.env`; once configured, the updater enables/restarts it. See `docs/BOT_PLAN.md`.

## Lead storage
Website callback and Telegram leads use SQLite at `/var/lib/elite/leads.sqlite3`. Real lead data must not enter Git. The `elite` service user has write permission only to the state directory required for this data.

## HTTPS / security
The repository's HTTPS Nginx template currently expects Let's Encrypt material under `/etc/letsencrypt/live/<domain>/`. Before changing certificates, inspect the certificate actually served by production and renewal status. A free REG.RU DomainSSL may exist in the account but should not replace a working automatically renewed certificate without a concrete benefit. Avoid accidental paid DomainSSL renewal.

Validate after deploy:

```bash
nginx -t
systemctl status elite
curl -fsS http://127.0.0.1:8000/healthz
curl -I https://rgelite.ru/
```

Also verify certificate SAN/expiry/issuer, HSTS, CSP, HTTP->HTTPS, `www` redirect, UFW, and that Flask debug is disabled.

## Indexing / local search
Keep `SITE_INDEXABLE=false` until the production release is correct. Then set it true, restart `elite`, confirm `/robots.txt` and `/sitemap.xml`, and submit the site in Yandex Webmaster. The iframe map alone does not create an ELITE organization pin: claim/create the real organization in Yandex Business and connect its verified location/profile.

## QA gate
Before considering a release healthy, test at least:
- iPhone-class viewport around 390px;
- desktop 1440px;
- no horizontal overflow;
- no broken assets or console errors;
- sticky CTA absent on hero and visible after hero;
- Telegram primary CTA and callback fallback;
- `/healthz`;
- lead write/read path;
- Yandex map/route;
- article contains ELITE branding only;
- canonical/robots/sitemap match production.
