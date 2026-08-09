from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

SITE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SITE_ROOT))

os.environ.update(
    SITE_DOMAIN="rgelite.ru",
    SITE_ENV="staging",
    SITE_INDEXABLE="false",
    SITE_TELEGRAM_URL="https://t.me/example",
    SITE_MAX_URL="https://max.ru/u/example",
    SITE_PHONE_DISPLAY="+7 (999) 000-00-00",
    SITE_PHONE_E164="+79990000000",
)

from app import app  # noqa: E402


class SiteSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_pages_metadata_and_jsonld(self) -> None:
        for path in ("/", "/article/hudozhestvennaya-gimnastika-s-3-let"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers["X-Robots-Tag"], "noindex, nofollow, noarchive"
            )
            html = response.get_data(as_text=True)
            self.assertIn('content="noindex,nofollow,noarchive"', html)
            self.assertNotIn("[АДРЕС", html)
            self.assertNotIn("точный адрес зала будет добавлен", html)
            self.assertNotIn("Здесь будет ваше", html)
            self.assertNotIn("Для рекламного лендинга", html)
            self.assertNotIn("контент-экосистему", html)
            for payload in re.findall(
                r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S
            ):
                json.loads(payload)

    def test_all_internal_assets_and_links_resolve(self) -> None:
        refs: set[str] = set()
        for path in ("/", "/article/hudozhestvennaya-gimnastika-s-3-let"):
            html = self.client.get(path).get_data(as_text=True)
            refs.update(re.findall(r'(?:href|src)="([^"]+)"', html))

        internal_paths = {
            urlsplit(ref).path
            for ref in refs
            if ref.startswith("/") and not ref.startswith("//")
        }
        failures = {}
        for path in sorted(internal_paths):
            response = self.client.get(path)
            try:
                if response.status_code >= 400:
                    failures[path] = response.status_code
            finally:
                response.close()
        self.assertEqual(failures, {})

    def test_no_unconfigured_lead_collection(self) -> None:
        html = "".join(
            self.client.get(path).get_data(as_text=True)
            for path in ("/", "/article/hudozhestvennaya-gimnastika-s-3-let")
        )
        self.assertNotIn("data-lead-form", html)
        self.assertNotIn('action="/api/lead"', html)

    def test_crawl_controls(self) -> None:
        self.assertEqual(self.client.get("/healthz").json, {"status": "ok"})
        self.assertIn("Disallow: /", self.client.get("/robots.txt").get_data(as_text=True))
        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("https://rgelite.ru/", sitemap)

        old_environment = os.environ["SITE_ENV"]
        old_indexable = os.environ["SITE_INDEXABLE"]
        try:
            os.environ["SITE_ENV"] = "production"
            os.environ["SITE_INDEXABLE"] = "true"
            self.assertIn(
                'content="index,follow"',
                self.client.get("/article/hudozhestvennaya-gimnastika-s-3-let").get_data(
                    as_text=True
                ),
            )
            robots = self.client.get("/robots.txt").get_data(as_text=True)
            self.assertIn("Allow: /", robots)
            self.assertIn("Sitemap: https://rgelite.ru/sitemap.xml", robots)
        finally:
            os.environ["SITE_ENV"] = old_environment
            os.environ["SITE_INDEXABLE"] = old_indexable

    def test_legacy_redirects(self) -> None:
        expected = {
            "/index.html": "/",
            "/article-hudozhestvennaya-gimnastika-s-3-let.html": (
                "/article/hudozhestvennaya-gimnastika-s-3-let"
            ),
            "/contacts.html": "/#contacts",
            "/prices.html": "/#price",
        }
        for path, destination in expected.items():
            response = self.client.get(path)
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response.headers["Location"], destination)


if __name__ == "__main__":
    unittest.main()
