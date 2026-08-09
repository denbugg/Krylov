# Infrastructure

Repository: `denbugg/Krylov`, branch `sitest`. Site scope: `site/`.

Production target:
`Internet -> DNS -> Nginx :80/:443 -> Gunicorn 127.0.0.1:8000 -> Flask`

Server checkout strategy:
```bash
git clone --filter=blob:none --no-checkout --branch sitest git@github.com:denbugg/Krylov.git /srv/elite/repo
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

Automatic deploy later: GitHub Actions can SSH to a dedicated deploy user and run a constrained update script; do not expose root credentials.
