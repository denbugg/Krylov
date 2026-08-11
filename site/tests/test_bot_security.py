from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BotSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "bot.sqlite3")
        self.env = patch.dict(
            os.environ,
            {
                "LEADS_DB_PATH": self.db_path,
                "TELEGRAM_BOT_TOKEN": "dummy-token",
                "TELEGRAM_ADMIN_USERNAME": "undina_007",
                "TELEGRAM_ADMIN_CHAT_ID": "",
            },
            clear=False,
        )
        self.env.start()
        import bot as bot_module

        self.bot = bot_module
        self.bot.DB_PATH = Path(self.db_path)
        self.bot.ADMIN_CHAT_ID_ENV = ""

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_contact_keyboard_requests_own_contact(self) -> None:
        keyboard = self.bot.contact_keyboard()
        button = keyboard["keyboard"][0][0]
        self.assertTrue(button.get("request_contact"))

    def test_foreign_contact_is_rejected(self) -> None:
        message = {
            "from": {"id": 100, "first_name": "A"},
            "chat": {"id": 100, "type": "private"},
            "contact": {"user_id": 200, "phone_number": "+79990000000"},
        }
        with patch.object(self.bot, "send_message") as send:
            self.bot.handle_contact(message)
        send.assert_called_once()
        self.assertFalse(Path(self.db_path).exists())

    def test_only_configured_admin_can_bind_initial_admin_chat(self) -> None:
        self.assertTrue(self.bot.is_admin_user({"username": "Undina_007"}, 777))
        self.assertFalse(self.bot.is_admin_user({"username": "someone_else"}, 777))

    def test_telegram_lead_copies_profile_identity_and_contact(self) -> None:
        user = {
            "id": 123,
            "username": "parent_user",
            "first_name": "Анна",
            "last_name": "Иванова",
        }
        self.bot.upsert_session(user, source="site_hero", state="await_contact", reset_lead=True)
        lead_id = self.bot.create_lead_from_contact(user, "+79161234567")
        conn = self.bot.db()
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        conn.close()
        self.assertEqual(row["phone"], "+79161234567")
        self.assertEqual(row["name"], "Анна Иванова")
        self.assertEqual(row["telegram_user_id"], 123)
        self.assertEqual(row["telegram_username"], "parent_user")
        self.assertEqual(row["source"], "telegram_bot:site_hero")

    def test_manager_can_update_lead_status_and_note(self) -> None:
        user = {"id": 123, "first_name": "Анна"}
        self.bot.upsert_session(user, source="test", state="await_contact", reset_lead=True)
        lead_id = self.bot.create_lead_from_contact(user, "+79161234567")
        self.assertTrue(self.bot.set_lead_status(lead_id, "trial_booked"))
        self.assertTrue(self.bot.set_lead_note(lead_id, "Перезвонить после 18:00"))
        row = self.bot.get_lead(lead_id)
        self.assertEqual(row["status"], "trial_booked")
        self.assertEqual(row["note"], "Перезвонить после 18:00")

    def test_status_keyboard_never_contains_phone_or_secret(self) -> None:
        keyboard = self.bot.status_keyboard(42, "new")
        payload = str(keyboard)
        self.assertIn("leadstatus:42:contacted", payload)
        self.assertNotIn("dummy-token", payload)

    def test_website_lead_is_marked_after_admin_notification(self) -> None:
        conn = self.bot.db()
        cur = conn.execute(
            """
            INSERT INTO leads(created_at,name,phone,source,page,preferred_channel,referrer,utm_json,status)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                self.bot.now_iso(),
                "Мария",
                "+79160000000",
                "callback_block",
                "/",
                "callback",
                None,
                "{}",
                "new",
            ),
        )
        lead_id = int(cur.lastrowid)
        conn.commit()
        conn.close()
        self.bot.set_setting("telegram_admin_chat_id", "777")
        with patch.object(self.bot, "send_message", return_value={"message_id": 55}) as send:
            self.bot.notify_pending_website_leads()
        send.assert_called_once()
        row = self.bot.get_lead(lead_id)
        self.assertIsNotNone(row["admin_notified_at"])


if __name__ == "__main__":
    unittest.main()
