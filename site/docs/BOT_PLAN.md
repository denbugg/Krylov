# ELITE messenger bot plan

## Goal
Messenger is the preferred lead path because it removes repeated identity/contact entry. Callback remains fallback.

## Telegram MVP
- Entry CTA from site opens bot deep link with source parameter (`start=site_hero`, `site_sticky`, etc.).
- Bot asks only: child age, preferred days/time, optional question.
- Telegram user identity is captured by Telegram; do not ask phone unless operationally needed.
- Every new dialogue / qualified lead is forwarded to an admin chat.
- Admin can answer through a lightweight operator flow; keep a history tied to Telegram user id.
- FAQ shortcuts: age, price, trial, address/route, what to bring, 6–10 waitlist, Polechka.
- Secrets (`TELEGRAM_BOT_TOKEN`, admin ids) stay in `/etc/elite/bot.env`, never Git.
- Run as a separate systemd unit on the same VPS. Do not mix bot polling/webhook loop with Gunicorn web workers.

## MAX MVP
Mirror the same conversation fields and admin handoff once the MAX bot credentials/API are available. Keep a transport adapter so business logic can be reused.

## Data / CRM
- Website callback leads live in SQLite `/var/lib/elite/leads.sqlite3` for the interim stage.
- Bot conversations can use the same state directory but separate tables/database.
- Later sync both sources to CRM with one lead schema and source attribution.
- Do not commit real leads or conversation exports to Git.

## Admin
First version can notify a private Telegram admin chat and provide reply/mark-done actions. A web admin panel is optional later; if built, require authentication and HTTPS.
