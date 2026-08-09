from __future__ import annotations

import json
import os
from urllib.parse import quote

from flask import Flask, Response, redirect, render_template

app = Flask(__name__)


def _site_context(path: str = "") -> dict[str, str]:
    domain = os.getenv("SITE_DOMAIN", "").strip().rstrip("/")
    scheme = os.getenv("SITE_SCHEME", "https").strip() or "https"
    production = os.getenv("SITE_ENV", "development").lower() == "production" and bool(domain)
    indexable = production and os.getenv("SITE_INDEXABLE", "false").lower() in {"1", "true", "yes"}
    base_url = f"{scheme}://{domain}" if domain else "http://localhost:8000"
    canonical_url = f"{base_url}/{path.lstrip('/')}" if path else f"{base_url}/"
    address = os.getenv("SITE_ADDRESS", "Москва, Боровское шоссе, 43, этаж 3").strip()
    telegram_url = os.getenv("SITE_TELEGRAM_URL", "").strip()
    max_url = os.getenv("SITE_MAX_URL", "").strip()
    phone_display = os.getenv("SITE_PHONE_DISPLAY", "").strip()
    phone_e164 = os.getenv("SITE_PHONE_E164", "").strip()
    social_links = [
        link
        for link in (
            telegram_url,
            max_url,
            "https://mypolechka.ru/",
            "https://www.youtube.com/channel/UCONm9-FBKX-27uhrf647ZCQ",
        )
        if link
    ]
    return {
        "base_url": base_url,
        "canonical_url": canonical_url,
        "robots": "index,follow" if indexable else "noindex,nofollow,noarchive",
        "site_address": address,
        "telegram_url": telegram_url,
        "max_url": max_url,
        "phone_display": phone_display,
        "phone_e164": phone_e164,
        "phone_href": f"tel:{phone_e164}" if phone_e164 else "",
        "same_as_json": json.dumps(social_links, ensure_ascii=False),
        "yandex_map_embed_url": (
            "https://yandex.ru/map-widget/v1/?mode=search&z=16&text=" + quote(address)
        ),
        "yandex_route_url": (
            "https://yandex.ru/maps/?mode=search&text=" + quote(address)
        ),
    }


@app.get("/")
def index():
    return render_template("index.html", **_site_context())


@app.get("/article/hudozhestvennaya-gimnastika-s-3-let")
def article():
    return render_template("article.html", **_site_context("article/hudozhestvennaya-gimnastika-s-3-let"))


@app.get("/index.html")
def legacy_index():
    return redirect("/", code=301)


@app.get("/article-hudozhestvennaya-gimnastika-s-3-let.html")
def legacy_article():
    return redirect("/article/hudozhestvennaya-gimnastika-s-3-let", code=301)


@app.get("/<path:legacy_page>.html")
def legacy_page(legacy_page: str):
    destinations = {
        "about": "/#about",
        "blog": "/article/hudozhestvennaya-gimnastika-s-3-let",
        "contacts": "/#contacts",
        "faq": "/#faq",
        "hall": "/#contacts",
        "prices": "/#price",
        "program-rhythmic-gymnastics": "/#groups",
        "programs": "/#groups",
        "team": "/#about",
    }
    destination = destinations.get(legacy_page)
    if destination is None:
        return {"error": "not found"}, 404
    return redirect(destination, code=301)


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
