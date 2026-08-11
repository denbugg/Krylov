from __future__ import annotations

import os
import runpy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "migrate-bot-db.py"


class BotMigrationTests(unittest.TestCase):
    def test_legacy_not_null_reply_map_becomes_nullable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leads.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tg_admin_message_map (
                    admin_message_id INTEGER PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    lead_id INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO tg_admin_message_map VALUES(?,?,?,?)",
                (10, 20, 30, "2026-08-11T00:00:00+00:00"),
            )
            conn.commit()
            conn.close()

            with patch.dict(os.environ, {"LEADS_DB_PATH": str(db_path)}, clear=False):
                runpy.run_path(str(MIGRATION), run_name="__main__")

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            columns = conn.execute("PRAGMA table_info(tg_admin_message_map)").fetchall()
            user_column = next(row for row in columns if row["name"] == "telegram_user_id")
            self.assertEqual(user_column["notnull"], 0)
            preserved = conn.execute(
                "SELECT * FROM tg_admin_message_map WHERE admin_message_id=10"
            ).fetchone()
            self.assertEqual(preserved["telegram_user_id"], 20)
            self.assertEqual(preserved["lead_id"], 30)
            conn.execute(
                "INSERT INTO tg_admin_message_map VALUES(?,?,?,?)",
                (11, None, 31, "2026-08-11T00:00:01+00:00"),
            )
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
