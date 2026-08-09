# Infrastructure

Repository: `denbugg/Krylov`, branch `sitest`. Site scope: `site/`.

Production target:
`Internet -> DNS -> Nginx :80/:443 -> Gunicorn 127.0.0.1:8000 -> Flask`

Current production target: `rgelite.ru` / `195.19.144.40`, REG Cloud, Ubuntu 24.04.

Server checkout strategy:
```bash
git clone --filter=blob:none --no-checkout --branch sitest https://github.com/denbugg/Krylov.git /srv/elite/repo
git -C /srv/elite/repo sparse-checkout init --cone
git -C /srv/elite/repo sparse-checkout set site
git -C /srv/elite/repo checkout sitest
```
Only `site/` is materialized in the working tree.

Recommended production filesystem:
- `/srv/elite/repo` git checkout
- `/srv/elite/site` symlink to repo/site
- `/srv/elite/venv` Python venv
- `/etc/elite/elite.env` secrets/config, mode 600
- systemd service `elite.service`
- `/usr/local/sbin/elite-update` health-checked Git update
- `/usr/local/sbin/elite-rollback` rollback to the recorded previous commit

The `eliteops` SSH account is key-only and may run only the update and rollback wrappers through sudo. Root/password SSH must remain disabled after key access is verified.
