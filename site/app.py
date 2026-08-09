from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, render_template, request

app = Flask(__name__)
PHONE_RE = re.compile(r"\d")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _db_path() -> Path:
    return Path(os.getenv("LEADS_DB_PATH", "/var/lib/elite/leads.sqlite3"))


def _db() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT,
            phone TEXT NOT NULL,
            source TEXT,
            page TEXT,
            preferred_channel TEXT,
            referrer TEXT,
            utm_json TEXT,
            status TEXT NOT NULL DEFAULT 'new'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC)")
    conn.commit()
    return conn


@app.after_request
def security_and_crawl_headers(response: Response) -> Response:
    if _site_context()["robots"] != "index,follow":
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


def _site_context(path: str = "") -> dict[str, str]:
    domain = os.getenv("SITE_DOMAIN", "").strip().rstrip("/")
    scheme = os.getenv("SITE_SCHEME", "https").strip() or "https"
    production = os.getenv("SITE_ENV", "development").lower() == "production" and bool(domain)
    indexable = production and _truthy(os.getenv("SITE_INDEXABLE", "false"))
    base_url = f"{scheme}://{domain}" if domain else "http://localhost:8000"
    canonical_url = f"{base_url}/{path.lstrip('/')}" if path else f"{base_url}/"
    address = os.getenv("SITE_ADDRESS", "Москва, Боровское шоссе, 43, этаж 3").strip()
    map_query = os.getenv("SITE_MAP_QUERY", "Москва, Боровское шоссе, 43").strip()
    telegram_bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@").replace(" ", "")
    telegram_direct_url = os.getenv("SITE_TELEGRAM_URL", "https://t.me/Undina_007").strip()
    telegram_url = (
        f"https://t.me/{telegram_bot_username}?start=site"
        if telegram_bot_username
        else telegram_direct_url
    )
    max_url = os.getenv("SITE_MAX_URL", "").strip()
    phone_display = os.getenv("SITE_PHONE_DISPLAY", "+7 (916) 965-35-13").strip()
    phone_e164 = os.getenv("SITE_PHONE_E164", "+79169653513").strip()
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
        "telegram_bot_username": telegram_bot_username,
        "max_url": max_url,
        "phone_display": phone_display,
        "phone_e164": phone_e164,
        "phone_href": f"tel:{phone_e164}" if phone_e164 else "",
        "same_as_json": json.dumps(social_links, ensure_ascii=False),
        "yandex_map_embed_url": "https://yandex.ru/map-widget/v1/?mode=search&z=17&text=" + quote(map_query),
        "yandex_route_url": "https://yandex.ru/maps/?mode=search&text=" + quote(map_query),
    }


@app.get("/")
def index():
    return render_template("index.html", **_site_context())


@app.get("/article/hudozhestvennaya-gimnastika-s-3-let")
def article():
    return render_template(
        "article.html", **_site_context("article/hudozhestvennaya-gimnastika-s-3-let")
    )


@app.get("/privacy")
def privacy():
    return render_template("privacy.html", **_site_context("privacy"))


@app.get("/consent")
def consent():
    return render_template("consent.html", **_site_context("consent"))


@app.post("/api/leads")
def create_lead():
    payload = request.get_json(silent=True) or request.form.to_dict(flat=True)
    if payload.get("website"):
        return jsonify({"ok": True}), 200

    name = str(payload.get("name", "")).strip()[:80]
    phone = str(payload.get("phone", "")).strip()[:32]
    digits = "".join(PHONE_RE.findall(phone))
    if len(digits) < 10:
        return jsonify({"ok": False, "error": "invalid_phone"}), 400

    source = str(payload.get("source", "website")).strip()[:80]
    page = str(payload.get("page", "/")).strip()[:200]
    preferred_channel = str(payload.get("preferred_channel", "callback")).strip()[:40]
    referrer = str(payload.get("referrer", "")).strip()[:500]
    utm = payload.get("utm", {})
    if not isinstance(utm, dict):
        utm = {}
    utm_json = json.dumps({str(k)[:60]: str(v)[:200] for k, v in utm.items()}, ensure_ascii=False)

    conn = _db()
    cur = conn.execute(
        """
        INSERT INTO leads(created_at, name, phone, source, page, preferred_channel, referrer, utm_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            name or None,
            phone,
            source,
            page,
            preferred_channel,
            referrer or None,
            utm_json,
        ),
    )
    conn.commit()
    lead_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "lead_id": lead_id}), 201


@app.get("/api/admin/leads")
def admin_leads():
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    supplied = request.headers.get("Authorization", "")
    if not expected or supplied != f"Bearer {expected}":
        return jsonify({"error": "unauthorized"}), 401
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    conn = _db()
    rows = conn.execute(
        "SELECT id, created_at, name, phone, source, page, preferred_channel, status FROM leads ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return jsonify({"leads": [dict(row) for row in rows]})


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
        "contacts": "/#location",
        "faq": "/#faq",
        "hall": "/#location",
        "prices": "/#groups",
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
  <url><loc>{base_url}/</loc><priority>1.0</priority></url>
  <url><loc>{base_url}/article/hudozhestvennaya-gimnastika-s-3-let</loc><priority>0.7</priority></url>
  <url><loc>{base_url}/privacy</loc><priority>0.2</priority></url>
  <url><loc>{base_url}/consent</loc><priority>0.2</priority></url>
</urlset>
'''
    return Response(body, mimetype="application/xml")


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8000")),
        debug=_truthy(os.getenv("FLASK_DEBUG", "false")),
    )
