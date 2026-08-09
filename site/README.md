# ELITE site

Production candidate for the ELITE single-hall rhythmic-gymnastics landing.

This folder is intentionally self-contained so `denbugg/Krylov:sitest` can be deployed with Git sparse-checkout of `site/` only.

The current visual payload is committed in this directory. GitHub branch `sitest` is the only source of truth for deployment and updates.

## Local run
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app run --port 8000
```

Open `http://127.0.0.1:8000/`. Health endpoint: `/healthz`.

## Agent handoff
Use `docs/BOOTSTRAP_AGENT_PROMPT.md` as the initial instruction and require the agent to read `AGENTS.md` plus `docs/*` first.

## Production
See `docs/DEPLOYMENT.md`. Production indexing remains gated until the real domain, HTTPS, address, and contacts pass production QA.
