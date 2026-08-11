from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("LEADS_DB_PATH", "/var/lib/elite/leads.sqlite3"))


def main() -> None:
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        columns = conn.execute("PRAGMA table_info(tg_admin_message_map)").fetchall()
        if not columns:
            return
        telegram_user = next((row for row in columns if row["name"] == "telegram_user_id"), None)
        if telegram_user is None or not int(telegram_user["notnull"]):
            return

        conn.execute("ALTER TABLE tg_admin_message_map RENAME TO tg_admin_message_map_legacy")
        conn.execute(
            """
            CREATE TABLE tg_admin_message_map (
                admin_message_id INTEGER PRIMARY KEY,
                telegram_user_id INTEGER,
                lead_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tg_admin_message_map(admin_message_id,telegram_user_id,lead_id,created_at)
            SELECT admin_message_id,telegram_user_id,lead_id,created_at
            FROM tg_admin_message_map_legacy
            """
        )
        conn.execute("DROP TABLE tg_admin_message_map_legacy")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
