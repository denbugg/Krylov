# Claude Code instructions for ELITE

Read `AGENTS.md` and all files under `docs/` before changing anything.

Work only inside `site/` on branch `sitest` unless the user explicitly authorizes a root-level GitHub Actions workflow. GitHub is source of truth; production deploys `sitest` using sparse-checkout of `site/`.

Execute independently where safe. Pause only for user authentication/2FA, DNS control-panel actions that cannot be automated, secrets that must be supplied interactively, or a required change outside `site/`.

Never request passwords/private keys in chat. Prefer SSH keys and least privilege. Preserve the current ELITE visual/product direction during infrastructure work.
