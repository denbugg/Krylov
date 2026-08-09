from __future__ import annotations

import os
from flask import Flask, render_template

app = Flask(__name__)


def _site_context(path: str = "") -> dict[str, str]:
    domain = os.getenv("SITE_DOMAIN", "").strip().rstrip("/")
    scheme = os.getenv("SITE_SCHEME", "https").strip() or "https"
    production = os.getenv("SITE_ENV", "development").lower() == "production" and bool(domain)
    base_url = f"{scheme}://{domain}" if domain else "http://localhost:8000"
    canonical_url = f"{base_url}/{path.lstrip('/')}" if path else f"{base_url}/"
    return {
        "base_url": base_url,
        "canonical_url": canonical_url,
        "robots": "index,follow" if production else "noindex,nofollow,noarchive",
    }


@app.get("/")
def index():
    return render_template("index.html", **_site_context())


@app.get("/article/hudozhestvennaya-gimnastika-s-3-let")
def article():
    return render_template("article.html", **_site_context("article/hudozhestvennaya-gimnastika-s-3-let"))


@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=True)
