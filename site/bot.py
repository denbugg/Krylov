from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USERNAME = os.getenv("TELEGRAM_ADMIN_USERNAME", "Undina_007").strip().lstrip("@").lower()
ADMIN_CHAT_ID_ENV = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
DB_PATH = Path(os.getenv("LEADS_DB_PATH", "/var/lib/elite/leads.sqlite3"))
API_BASE = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""
SESSION = requests.Session()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
    lead_columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
    additions = {
        "telegram_user_id": "INTEGER",
        "telegram_username": "TEXT",
        "telegram_first_name": "TEXT",
        "telegram_last_name": "TEXT",
        "child_age": "TEXT",
        "preferred_time": "TEXT",
        "question": "TEXT",
        "updated_at": "TEXT",
    }
    for column, sql_type in additions.items():
        if column not in lead_columns:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {column} {sql_type}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tg_sessions (
            telegram_user_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'new',
            source TEXT,
            lead_id INTEGER,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tg_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            telegram_user_id INTEGER NOT NULL,
            lead_id INTEGER,
            direction TEXT NOT NULL,
            text TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tg_admin_message_map (
            admin_message_id INTEGER PRIMARY KEY,
            telegram_user_id INTEGER NOT NULL,
            lead_id INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_tg_user ON leads(telegram_user_id, id DESC)")
    conn.commit()
    return conn


def api(method: str, payload: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    response = SESSION.post(f"{API_BASE}/{method}", json=payload or {}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API method {method} failed")
    return data


def send_message(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api("sendMessage", payload)["result"]


def answer_callback(callback_id: str, text: str = "") -> None:
    api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def contact_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [[{"text": "📱 Поделиться контактом", "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "input_field_placeholder": "Можно сразу задать вопрос",
    }


def age_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "3 года", "callback_data": "age:3"},
                {"text": "4 года", "callback_data": "age:4"},
                {"text": "5 лет", "callback_data": "age:5"},
            ],
            [
                {"text": "6–10 лет", "callback_data": "age:6-10"},
                {"text": "Уточнить позже", "callback_data": "age:later"},
            ],
        ]
    }


def time_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Будни днём", "callback_data": "time:weekday_day"},
                {"text": "Будни вечером", "callback_data": "time:weekday_evening"},
            ],
            [
                {"text": "Выходные", "callback_data": "time:weekend"},
                {"text": "Обсудить", "callback_data": "time:discuss"},
            ],
        ]
    }


def normalize_name(user: dict[str, Any]) -> str:
    parts = [str(user.get("first_name") or "").strip(), str(user.get("last_name") or "").strip()]
    return " ".join(part for part in parts if part)[:120]


def upsert_session(user: dict[str, Any], *, source: str | None = None, state: str | None = None, lead_id: int | None = None, reset_lead: bool = False) -> None:
    user_id = int(user["id"])
    conn = db()
    existing = conn.execute("SELECT * FROM tg_sessions WHERE telegram_user_id=?", (user_id,)).fetchone()
    source_value = (source if source is not None else (existing["source"] if existing else "telegram")) or "telegram"
    state_value = state if state is not None else (existing["state"] if existing else "new")
    if reset_lead:
        lead_value = None
    elif lead_id is not None:
        lead_value = lead_id
    else:
        lead_value = existing["lead_id"] if existing else None
    conn.execute(
        """
        INSERT INTO tg_sessions(telegram_user_id,state,source,lead_id,first_name,last_name,username,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
          state=excluded.state, source=excluded.source, lead_id=excluded.lead_id,
          first_name=excluded.first_name, last_name=excluded.last_name,
          username=excluded.username, updated_at=excluded.updated_at
        """,
        (
            user_id,
            state_value,
            source_value[:80],
            lead_value,
            str(user.get("first_name") or "")[:80] or None,
            str(user.get("last_name") or "")[:80] or None,
            str(user.get("username") or "")[:80] or None,
            now_iso(),
        ),
    )
    conn.commit()
    conn.close()


def get_session(user_id: int) -> sqlite3.Row | None:
    conn = db()
    row = conn.execute("SELECT * FROM tg_sessions WHERE telegram_user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def set_setting(key: str, value: str) -> None:
    conn = db()
    conn.execute(
        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
        (key, value, now_iso()),
    )
    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return str(row["value"]) if row else ""


def admin_chat_id() -> int | None:
    value = ADMIN_CHAT_ID_ENV or get_setting("telegram_admin_chat_id")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def is_admin_user(user: dict[str, Any], chat_id: int) -> bool:
    bound = admin_chat_id()
    if bound is not None:
        return bound == chat_id
    username = str(user.get("username") or "").lower()
    return bool(ADMIN_USERNAME and username == ADMIN_USERNAME)


def create_lead_from_contact(user: dict[str, Any], phone: str) -> int:
    session = get_session(int(user["id"]))
    source = session["source"] if session else "telegram"
    name = normalize_name(user)
    conn = db()
    cur = conn.execute(
        """
        INSERT INTO leads(
          created_at,name,phone,source,page,preferred_channel,referrer,utm_json,status,
          telegram_user_id,telegram_username,telegram_first_name,telegram_last_name,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            now_iso(),
            name or None,
            phone[:32],
            f"telegram_bot:{source}"[:80],
            "/bot",
            "telegram",
            None,
            "{}",
            "new",
            int(user["id"]),
            str(user.get("username") or "")[:80] or None,
            str(user.get("first_name") or "")[:80] or None,
            str(user.get("last_name") or "")[:80] or None,
            now_iso(),
        ),
    )
    lead_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    upsert_session(user, state="qualified", lead_id=lead_id)
    return lead_id


def update_lead(user_id: int, field: str, value: str) -> int | None:
    if field not in {"child_age", "preferred_time", "question"}:
        raise ValueError("unsupported field")
    session = get_session(user_id)
    if not session or not session["lead_id"]:
        return None
    lead_id = int(session["lead_id"])
    conn = db()
    conn.execute(f"UPDATE leads SET {field}=?, updated_at=? WHERE id=?", (value[:500], now_iso(), lead_id))
    conn.commit()
    conn.close()
    return lead_id


def log_message(user_id: int, direction: str, text: str, lead_id: int | None = None) -> None:
    conn = db()
    conn.execute(
        "INSERT INTO tg_messages(created_at,telegram_user_id,lead_id,direction,text) VALUES(?,?,?,?,?)",
        (now_iso(), user_id, lead_id, direction, text[:4000]),
    )
    conn.commit()
    conn.close()


def map_admin_message(admin_message_id: int, user_id: int, lead_id: int | None) -> None:
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO tg_admin_message_map(admin_message_id,telegram_user_id,lead_id,created_at) VALUES(?,?,?,?)",
        (admin_message_id, user_id, lead_id, now_iso()),
    )
    conn.commit()
    conn.close()


def mapped_user(admin_message_id: int) -> tuple[int, int | None] | None:
    conn = db()
    row = conn.execute(
        "SELECT telegram_user_id,lead_id FROM tg_admin_message_map WHERE admin_message_id=?",
        (admin_message_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return int(row["telegram_user_id"]), int(row["lead_id"]) if row["lead_id"] else None


def notify_admin(user: dict[str, Any], text: str, lead_id: int | None = None) -> None:
    admin_id = admin_chat_id()
    if admin_id is None:
        return
    username = str(user.get("username") or "")
    identity = normalize_name(user) or f"Telegram {user['id']}"
    if username:
        identity += f" (@{username})"
    message = send_message(
        admin_id,
        f"ELITE · {identity}\n{text}\n\nОтветьте на это сообщение в Telegram — бот передаст ответ родителю.",
    )
    map_admin_message(int(message["message_id"]), int(user["id"]), lead_id)


def handle_start(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    text = str(message.get("text") or "")
    parts = text.split(maxsplit=1)
    source = parts[1].strip()[:64] if len(parts) > 1 else "direct"
    upsert_session(user, source=source, state="await_contact", reset_lead=True)
    first_name = str(user.get("first_name") or "").strip()
    greeting = f"{first_name}, " if first_name else ""
    send_message(
        chat_id,
        greeting
        + "запись в ELITE займёт один шаг. Нажмите «Поделиться контактом» — Telegram сам передаст номер, а имя мы уже получили из вашего профиля. После этого можно выбрать возраст ребёнка или сразу задать вопрос.",
        reply_markup=contact_keyboard(),
    )


def handle_admin_registration(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    if not is_admin_user(user, chat_id):
        send_message(chat_id, "Команда недоступна.")
        return
    set_setting("telegram_admin_chat_id", str(chat_id))
    send_message(chat_id, "Админ-чат ELITE подключён. Новые контакты и вопросы будут приходить сюда; отвечайте через Reply на сообщение бота.")


def handle_contact(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    contact = message.get("contact") or {}
    contact_user_id = contact.get("user_id")
    if contact_user_id is not None and int(contact_user_id) != int(user["id"]):
        send_message(chat_id, "Нужен именно ваш контакт. Нажмите кнопку «Поделиться контактом» ниже.", reply_markup=contact_keyboard())
        return
    phone = str(contact.get("phone_number") or "").strip()
    if not phone:
        send_message(chat_id, "Не удалось получить номер. Нажмите кнопку ещё раз.", reply_markup=contact_keyboard())
        return
    lead_id = create_lead_from_contact(user, phone)
    log_message(int(user["id"]), "in", "[contact shared]", lead_id)
    notify_admin(user, f"Новая заявка #{lead_id}\nТелефон: {phone}\nИсточник: Telegram с сайта", lead_id)
    send_message(
        chat_id,
        "Готово — контакт получен, заявка уже создана. Если удобно, выберите возраст ребёнка. Это необязательно: можно сразу написать вопрос сообщением.",
        reply_markup={"remove_keyboard": True},
    )
    send_message(chat_id, "Возраст ребёнка:", reply_markup=age_keyboard())


def handle_callback(query: dict[str, Any]) -> None:
    user = query["from"]
    data = str(query.get("data") or "")
    chat = (query.get("message") or {}).get("chat") or {}
    chat_id = int(chat.get("id") or user["id"])
    user_id = int(user["id"])
    if data.startswith("age:"):
        value = data.split(":", 1)[1]
        label = {"3": "3 года", "4": "4 года", "5": "5 лет", "6-10": "6–10 лет", "later": "уточнить позже"}.get(value, value)
        lead_id = update_lead(user_id, "child_age", label)
        answer_callback(query["id"], "Сохранили")
        if lead_id:
            notify_admin(user, f"Заявка #{lead_id}: возраст ребёнка — {label}", lead_id)
        send_message(chat_id, "Когда обычно удобнее?", reply_markup=time_keyboard())
        return
    if data.startswith("time:"):
        value = data.split(":", 1)[1]
        label = {
            "weekday_day": "будни днём",
            "weekday_evening": "будни вечером",
            "weekend": "выходные",
            "discuss": "обсудить с администратором",
        }.get(value, value)
        lead_id = update_lead(user_id, "preferred_time", label)
        answer_callback(query["id"], "Сохранили")
        if lead_id:
            notify_admin(user, f"Заявка #{lead_id}: удобное время — {label}", lead_id)
        send_message(chat_id, "Спасибо. Администратор ELITE уже видит заявку. Можете написать сюда любой вопрос — ответ придёт в этот же чат.")
        return
    answer_callback(query["id"])


def handle_admin_reply(message: dict[str, Any]) -> bool:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    if not is_admin_user(user, chat_id):
        return False
    reply_to = message.get("reply_to_message") or {}
    mapped = mapped_user(int(reply_to.get("message_id") or 0)) if reply_to else None
    text = str(message.get("text") or "").strip()
    if not mapped or not text:
        return False
    target_user_id, lead_id = mapped
    send_message(target_user_id, "ELITE: " + text)
    log_message(target_user_id, "admin_out", text, lead_id)
    send_message(chat_id, "Ответ отправлен.")
    return True


def handle_text(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    text = str(message.get("text") or "").strip()
    if not text:
        return
    if text.startswith("/start"):
        handle_start(message)
        return
    if text.startswith("/admin"):
        handle_admin_registration(message)
        return
    if handle_admin_reply(message):
        return

    session = get_session(int(user["id"]))
    lead_id = int(session["lead_id"]) if session and session["lead_id"] else None
    log_message(int(user["id"]), "in", text, lead_id)
    if lead_id:
        update_lead(int(user["id"]), "question", text)
        notify_admin(user, f"Вопрос по заявке #{lead_id}:\n{text}", lead_id)
        send_message(chat_id, "Передал вопрос администратору. Ответ придёт сюда.")
    else:
        notify_admin(user, f"Вопрос до передачи контакта:\n{text}", None)
        send_message(
            chat_id,
            "Вопрос передан. Чтобы мы могли записать вас на пробное без ручного ввода номера, нажмите «Поделиться контактом».",
            reply_markup=contact_keyboard(),
        )


def process_update(update: dict[str, Any]) -> None:
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return
    message = update.get("message")
    if not message or message.get("chat", {}).get("type") != "private":
        return
    if message.get("contact"):
        handle_contact(message)
        return
    handle_text(message)


def main() -> None:
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")
    db().close()
    offset = 0
    while True:
        try:
            result = api(
                "getUpdates",
                {"offset": offset, "timeout": 50, "allowed_updates": ["message", "callback_query"]},
                timeout=60,
            )["result"]
            for update in result:
                offset = max(offset, int(update["update_id"]) + 1)
                try:
                    process_update(update)
                except Exception as exc:
                    print(f"update processing failed: {type(exc).__name__}", flush=True)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"telegram polling error: {type(exc).__name__}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
