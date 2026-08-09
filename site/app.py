from __future__ import annotations

import os
from flask import Flask, Response, render_template

app = Flask(__name__)


def _site_context(path: str = "") -> dict[str, str]:
    domain = os.getenv("SITE_DOMAIN", "").strip().rstrip("/")
    scheme = os.getenv("SITE_SCHEME", "https").strip() or "https"
    production = os.getenv("SITE_ENV", "development").lower() == "production" and bool(domain)
    indexable = production and os.getenv("SITE_INDEXABLE", "false").lower() in {"1", "true", "yes"}
    base_url = f"{scheme}://{domain}" if domain else "http://localhost:8000"
    canonical_url = f"{base_url}/{path.lstrip('/')}" if path else f"{base_url}/"
    return {
        "base_url": base_url,
        "canonical_url": canonical_url,
        "robots": "index,follow" if indexable else "noindex,nofollow,noarchive",
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


@app.get("/robots.txt")
def robots_txt():
    context = _site_context()
    if context["robots"] == "index,follow":
        body = f"User-agent: *\nAllow: /\nSitemap: {context['base_url']}/sitemap.xml\n"
    else:
        body = "User-agent: *\nDisallow: /\n"
    return Response(body, mimetype="text/plain")


@app.get("/sitemap.xml")
def sitemap_xml():
    base_url = _site_context()["base_url"]
    body = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base_url}/</loc></url>
  <url><loc>{base_url}/article/hudozhestvennaya-gimnastika-s-3-let</loc></url>
</urlset>
'''
    return Response(body, mimetype="application/xml")


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"},
    )
