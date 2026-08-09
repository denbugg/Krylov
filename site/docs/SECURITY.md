# Security

- No passwords, private keys, bot tokens, CRM tokens, or API keys in git/issues/chat.
- Use SSH keys. Disable password SSH after key access is confirmed.
- UFW: allow OpenSSH and Nginx Full only unless a future service requires more.
- Flask/Gunicorn binds to localhost; only Nginx is public.
- Production environment file is `/etc/elite/elite.env`, chmod 600.
- GitHub deployment should use least-privilege secrets and a dedicated deploy key/user.
- Do not expose Flask debug mode in production.
- Personal-data handling must be reviewed before enabling lead storage/integrations.
