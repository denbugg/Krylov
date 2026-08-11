from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ENCRYPTION_KEY = "6FaL9VZumMZFCkvyB_SwIbZm02c2YhI2Lftc6NJaNz0="


class SiteSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "leads.sqlite3")
        self.env = patch.dict(
            os.environ,
            {
                "SITE_ENV": "production",
                "SITE_DOMAIN": "rgelite.ru",
                "SITE_SCHEME": "https",
                "SITE_INDEXABLE": "true",
                "LEADS_DB_PATH": self.db_path,
                "LEADS_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "ADMIN_TOKEN": "test-admin-token-0123456789",
                "TELEGRAM_BOT_USERNAME": "elite_test_bot",
                "SITE_TELEGRAM_URL": "https://t.me/Undina_007",
            },
            clear=False,
        )
        self.env.start()
        import app as app_module

        self.app_module = app_module
        self.client = app_module.app.test_client()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_security_headers_present(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("camera=()", response.headers.get("Permissions-Policy", ""))
        self.assertIn("default-src 'self'", response.headers.get("Content-Security-Policy", ""))

    def test_admin_api_requires_bearer_token_and_is_no_store(self) -> None:
        denied = self.client.get("/api/admin/leads")
        self.assertEqual(denied.status_code, 401)
        allowed = self.client.get(
            "/api/admin/leads",
            headers={"Authorization": "Bearer test-admin-token-0123456789"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers.get("Cache-Control"), "no-store")

    def test_invalid_phone_is_rejected(self) -> None:
        response = self.client.post("/api/leads", json={"phone": "123", "name": "Test"})
        self.assertEqual(response.status_code, 400)

    def test_honeypot_does_not_create_lead(self) -> None:
        response = self.client.post(
            "/api/leads",
            json={"phone": "+7 916 111-22-33", "website": "spam.example"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Path(self.db_path).exists())

    def test_valid_lead_is_encrypted_at_rest_and_decrypted_for_admin(self) -> None:
        response = self.client.post(
            "/api/leads",
            json={"phone": "+7 916 111-22-33", "name": "Иван", "source": "test"},
        )
        self.assertEqual(response.status_code, 201)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT name,phone FROM leads LIMIT 1").fetchone()
        conn.close()
        self.assertTrue(row[0].startswith("enc:v1:"))
        self.assertTrue(row[1].startswith("enc:v1:"))
        self.assertNotIn("Иван", row[0])
        self.assertNotIn("916", row[1])

        admin = self.client.get(
            "/api/admin/leads",
            headers={"Authorization": "Bearer test-admin-token-0123456789"},
        )
        lead = admin.json["leads"][0]
        self.assertEqual(lead["name"], "Иван")
        self.assertEqual(lead["phone"], "+7 916 111-22-33")

    def test_rate_limit_caps_repeated_submissions(self) -> None:
        for index in range(5):
            response = self.client.post(
                "/api/leads",
                json={"phone": f"+7 916 111-2{index}-33", "source": "rate-test"},
                headers={"X-Real-IP": "203.0.113.10"},
            )
            self.assertEqual(response.status_code, 201)
        blocked = self.client.post(
            "/api/leads",
            json={"phone": "+7 916 111-99-33", "source": "rate-test"},
            headers={"X-Real-IP": "203.0.113.10"},
        )
        self.assertEqual(blocked.status_code, 429)

    def test_telegram_deep_link_is_rendered_without_secret_leak(self) -> None:
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertIn("https://t.me/elite_test_bot?start=site", body)
        self.assertNotIn("test-admin-token-0123456789", body)
        self.assertNotIn(TEST_ENCRYPTION_KEY, body)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", body)

    def test_production_robots_and_sitemap(self) -> None:
        robots = self.client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("Allow: /", robots.get_data(as_text=True))
        self.assertIn("https://rgelite.ru/sitemap.xml", robots.get_data(as_text=True))
        sitemap = self.client.get("/sitemap.xml")
        self.assertIn("https://rgelite.ru/", sitemap.get_data(as_text=True))

    def test_no_piruette_brand_in_homepage(self) -> None:
        body = self.client.get("/").get_data(as_text=True).lower()
        self.assertNotIn("pirouette", body)
        self.assertNotIn("пируэт", body)


if __name__ == "__main__":
    unittest.main()
