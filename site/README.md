# ELITE site

Production candidate for the ELITE single-hall rhythmic-gymnastics landing.

This folder is intentionally self-contained so `denbugg/Krylov:sitest` can be deployed with Git sparse-checkout of `site/` only.

## Important
The full visual payload is prepared separately as `elite_site_payload.tar.gz` (SHA-256 `4d5b1be172126f4cc7bc280688d4a2fada36dea19314fd098a83cf85b199f5c7`). It contains the current ELITE landing templates and optimized media assets. Import it into this `site/` directory before production deployment.

## Local run
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app run --port 8000
```

Health endpoint: `/healthz`.

## Agent handoff
Use `docs/BOOTSTRAP_AGENT_PROMPT.md` as the initial instruction and require the agent to read `AGENTS.md` plus `docs/*` first.
