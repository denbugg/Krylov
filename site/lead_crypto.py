from __future__ import annotations

import os
import sqlite3

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


def _fernet() -> Fernet | None:
    key = os.getenv("LEADS_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    return Fernet(key.encode("ascii"))


def encryption_required() -> bool:
    return os.getenv("SITE_ENV", "development").strip().lower() == "production"


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text or text.startswith(PREFIX):
        return text
    cipher = _fernet()
    if cipher is None:
        if encryption_required():
            raise RuntimeError("LEADS_ENCRYPTION_KEY is not configured")
        return text
    token = cipher.encrypt(text.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text.startswith(PREFIX):
        return text
    cipher = _fernet()
    if cipher is None:
        raise RuntimeError("LEADS_ENCRYPTION_KEY is not configured")
    try:
        return cipher.decrypt(text[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Could not decrypt lead PII") from exc


def migrate_lead_pii(conn: sqlite3.Connection) -> None:
    if _fernet() is None:
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
    protected = [name for name in ("name", "phone", "question", "note") if name in columns]
    if not protected:
        return
    rows = conn.execute("SELECT id, " + ", ".join(protected) + " FROM leads").fetchall()
    updates: list[tuple[list[str], list[str | int | None]]] = []
    for row in rows:
        assignments: list[str] = []
        values: list[str | int | None] = []
        for column in protected:
            value = row[column]
            if value and not str(value).startswith(PREFIX):
                assignments.append(f"{column}=?")
                values.append(encrypt_text(str(value)))
        if assignments:
            values.append(int(row["id"]))
            updates.append((assignments, values))
    for assignments, values in updates:
        conn.execute(
            "UPDATE leads SET " + ", ".join(assignments) + " WHERE id=?",
            tuple(values),
        )
    if updates:
        conn.commit()
