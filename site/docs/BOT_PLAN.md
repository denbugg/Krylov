# ELITE messenger bot — current implementation

## Conversion model
Messenger is the preferred lead path because it removes repeated manual identity/contact entry. The callback form remains fallback.

## Telegram MVP — implemented in `site/bot.py`
- Primary site CTAs open a Telegram bot deep link. The CTA source is preserved in the `start` payload (`hero`, `sticky`, `group_3_5`, etc.).
- Telegram already supplies profile `first_name`, optional `last_name`, and optional `username`; the bot does not ask the parent to type those again.
- Immediately after `/start`, the bot shows Telegram's native `request_contact` button. One tap shares the user's own phone number. This is the preferred lead-creation point.
- Important: Telegram profile first/last name is convenient lead identity, not a guaranteed legal full name/patronymic.
- After contact is received, the lead is saved and the parent may optionally choose child age and preferred time or just type a question.
- Every new lead/question is delivered to the admin Telegram chat.
- The admin can answer by using Telegram Reply on the bot notification; the bot relays that answer back to the parent.
- `/admin` from the configured `TELEGRAM_ADMIN_USERNAME` binds that private chat as the operator chat. Prefer setting a fixed `TELEGRAM_ADMIN_CHAT_ID` after first binding.
- Long polling is used for the MVP, so no public webhook endpoint or bot port is exposed.
- Bot and website share SQLite lead storage at `/var/lib/elite/leads.sqlite3` but run as separate systemd processes.

## Required server-only environment
Store only in `/etc/elite/elite.env`, never Git:

```text
TELEGRAM_BOT_TOKEN=<BotFather token>
TELEGRAM_BOT_USERNAME=<bot username without @>
TELEGRAM_ADMIN_USERNAME=Undina_007
TELEGRAM_ADMIN_CHAT_ID=
```

When `TELEGRAM_BOT_USERNAME` is populated, the website automatically prefers `https://t.me/<bot>?start=...` over the direct administrator Telegram URL.

## Telegram activation
1. Create a dedicated ELITE bot in `@BotFather` and obtain username/token.
2. Put username/token directly into `/etc/elite/elite.env` on the VPS.
3. Run `sudo /usr/local/sbin/elite-update` (or restart `elite` and enable/restart `elite-bot`).
4. From `@Undina_007`, open the bot and send `/admin` once.
5. Test site CTA → `/start` → native contact button → DB lead → admin notification → admin Reply → parent response.

## MAX MVP
Build the same UX once official MAX bot credentials/API are available: identity from messenger where supported, one-tap contact/data consent where supported, age/time shortcuts, admin handoff, shared lead schema. Do not invent API behavior: verify against current official MAX documentation before implementation.

## Data / CRM
- Website callback leads and Telegram leads use `/var/lib/elite/leads.sqlite3` during the interim stage.
- Real leads/conversations must never be committed to Git.
- Later sync Telegram, MAX, and callback sources to one CRM lead schema with source attribution.

## Security
- Bot token, admin token, CRM secrets and messenger credentials stay server-side only.
- Bot runs under the unprivileged `elite` user as `elite-bot.service` with systemd hardening.
- No Telegram webhook is exposed in the MVP; outbound HTTPS long polling is sufficient.
