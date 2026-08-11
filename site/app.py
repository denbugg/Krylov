from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, render_template, request

from lead_crypto import decrypt_text, encrypt_text, migrate_lead_pii

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
PHONE_RE = re.compile(r"\d")
RATE_WINDOW_SECONDS = 10 * 60
RATE_MAX_ATTEMPTS = 5


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _db_path() -> Path:
    return Path(os.getenv("LEADS_DB_PATH", "/var/lib/elite/leads.sqlite3"))


def _db() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
    additions = {
        "telegram_user_id": "INTEGER",
        "telegram_username": "TEXT",
        "telegram_first_name": "TEXT",
        "telegram_last_name": "TEXT",
        "child_age": "TEXT",
        "preferred_time": "TEXT",
        "question": "TEXT",
        "lead_type": "TEXT",
        "note": "TEXT",
        "next_follow_up_at": "TEXT",
        "admin_notified_at": "TEXT",
        "updated_at": "TEXT",
    }
    for column, sql_type in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {column} {sql_type}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts INTEGER NOT NULL,
            ip_hash TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lead_attempts ON lead_attempts(ip_hash, created_ts)")
    migrate_lead_pii(conn)
    conn.commit()
    return conn


def _client_ip_hash() -> str:
    address = (request.headers.get("X-Real-IP") or request.remote_addr or "unknown").strip()
    secret = (
        os.getenv("IP_HASH_SALT", "").strip()
        or os.getenv("LEADS_ENCRYPTION_KEY", "").strip()
        or "elite-development-only"
    )
    return hmac.new(secret.encode("utf-8"), address.encode("utf-8"), hashlib.sha256).hexdigest()


def _consume_lead_attempt(conn: sqlite3.Connection) -> bool:
    now = int(time.time())
    cutoff = now - RATE_WINDOW_SECONDS
    ip_hash = _client_ip_hash()
    conn.execute("DELETE FROM lead_attempts WHERE created_ts < ?", (cutoff,))
    count = conn.execute(
        "SELECT COUNT(*) FROM lead_attempts WHERE ip_hash=? AND created_ts>=?",
        (ip_hash, cutoff),
    ).fetchone()[0]
    if int(count) >= RATE_MAX_ATTEMPTS:
        conn.commit()
        return False
    conn.execute("INSERT INTO lead_attempts(created_ts,ip_hash) VALUES(?,?)", (now, ip_hash))
    conn.commit()
    return True


@app.after_request
def security_and_crawl_headers(response: Response) -> Response:
    if _site_context()["robots"] != "index,follow":
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-src https://yandex.ru https://*.yandex.ru; "
        "connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
    )
    if request.path.startswith("/api/admin/"):
        response.headers["Cache-Control"] = "no-store"
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
            "https://www.youtube.com/channel/UCONm9-FBKX-27uhrf647ZCQ",
            "https://rutube.ru/channel/15975173/",
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
    if len(digits) < 10 or len(digits) > 15:
        return jsonify({"ok": False, "error": "invalid_phone"}), 400

    source = str(payload.get("source", "callback_block")).strip()[:80]
    page = str(payload.get("page", "/")).strip()[:200]
    preferred_channel = str(payload.get("preferred_channel", "callback")).strip()[:40]
    referrer = str(payload.get("referrer", "")).strip()[:500]
    lead_type = str(payload.get("lead_type", "trial_now")).strip()[:40]
    if lead_type not in {"trial_now", "future_group"}:
        lead_type = "trial_now"
    utm = payload.get("utm", {})
    if not isinstance(utm, dict):
        utm = {}
    utm_json = json.dumps(
        {str(k)[:60]: str(v)[:200] for k, v in utm.items()}, ensure_ascii=False
    )

    conn = _db()
    try:
        if not _consume_lead_attempt(conn):
            return jsonify({"ok": False, "error": "rate_limited"}), 429
        encrypted_name = encrypt_text(name or None)
        encrypted_phone = encrypt_text(phone)
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO leads(
                created_at,name,phone,source,page,preferred_channel,referrer,utm_json,
                status,lead_type,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now,
                encrypted_name,
                encrypted_phone,
                source,
                page,
                preferred_channel,
                referrer or None,
                utm_json,
                "new",
                lead_type,
                now,
            ),
        )
        conn.commit()
        lead_id = cur.lastrowid
    except RuntimeError:
        conn.rollback()
        return jsonify({"ok": False, "error": "lead_storage_unavailable"}), 503
    finally:
        conn.close()
    return jsonify({"ok": True, "lead_id": lead_id}), 201


@app.get("/api/admin/leads")
def admin_leads():
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    supplied = request.headers.get("Authorization", "")
    expected_header = f"Bearer {expected}"
    if not expected or not hmac.compare_digest(supplied, expected_header):
        return jsonify({"error": "unauthorized"}), 401
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    conn = _db()
    rows = conn.execute(
        """
        SELECT id,created_at,name,phone,source,page,preferred_channel,status,lead_type,
               child_age,preferred_time
        FROM leads ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    leads = []
    for row in rows:
        item = dict(row)
        item["name"] = decrypt_text(item.get("name"))
        item["phone"] = decrypt_text(item.get("phone"))
        leads.append(item)
    response = jsonify({"leads": leads})
    response.headers["Cache-Control"] = "no-store"
    return response


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
