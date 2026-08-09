# One-time visual payload import

The visual payload from `elite_site_payload.zip` was imported once before production deployment. The verified archive SHA-256 was `fbc941ce86d11ceb53098f230f43b677ff15f4142f20f1e91a9712d461b08e71`.

Only the current templates and their referenced optimized assets were imported. The newer infrastructure, deployment scripts, operating contract, and documentation already present on branch `sitest` were preserved.

The archive is not an update source. GitHub repository `denbugg/Krylov`, branch `sitest`, is the only source of truth for all future deployments and rollbacks.
