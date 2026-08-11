from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USERNAME = os.getenv("TELEGRAM_ADMIN_USERNAME", "Undina_007").strip().lstrip("@").lower()
ADMIN_CHAT_ID_ENV = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
DB_PATH = Path(os.getenv("LEADS_DB_PATH", "/var/lib/elite/leads.sqlite3"))
API_BASE = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""
SESSION = requests.Session()

STATUSES = {
    "new": "Новая",
    "contacted": "Связались",
    "trial_booked": "Пробное назначено",
    "trial_done": "Пробное прошло",
    "paid": "Оплачено",
    "follow_up": "Вернуться позже",
    "lost": "Неактуально",
}


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
            telegram_user_id INTEGER,
            lead_id INTEGER NOT NULL,
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status, id DESC)")
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


def send_message(
    chat_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api("sendMessage", payload)["result"]


def edit_message(
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    api("editMessageText", payload)


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


def status_keyboard(lead_id: int, status: str) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    compact = [
        ("contacted", "Связались"),
        ("trial_booked", "Пробное"),
        ("paid", "Оплачено"),
        ("follow_up", "Позже"),
        ("lost", "Неактуально"),
    ]
    current_row: list[dict[str, str]] = []
    for key, label in compact:
        prefix = "✓ " if key == status else ""
        current_row.append(
            {"text": prefix + label, "callback_data": f"leadstatus:{lead_id}:{key}"}
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([{"text": "Карточка заявки", "callback_data": f"leadshow:{lead_id}"}])
    return {"inline_keyboard": rows}


def normalize_name(user: dict[str, Any]) -> str:
    parts = [
        str(user.get("first_name") or "").strip(),
        str(user.get("last_name") or "").strip(),
    ]
    return " ".join(part for part in parts if part)[:120]


def get_setting(key: str) -> str:
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return str(row["value"]) if row else ""


def set_setting(key: str, value: str) -> None:
    conn = db()
    conn.execute(
        """
        INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
        """,
        (key, value, now_iso()),
    )
    conn.commit()
    conn.close()


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


def upsert_session(
    user: dict[str, Any],
    *,
    source: str | None = None,
    state: str | None = None,
    lead_id: int | None = None,
    reset_lead: bool = False,
) -> None:
    user_id = int(user["id"])
    conn = db()
    existing = conn.execute(
        "SELECT * FROM tg_sessions WHERE telegram_user_id=?", (user_id,)
    ).fetchone()
    source_value = (
        source if source is not None else (existing["source"] if existing else "telegram")
    ) or "telegram"
    state_value = state if state is not None else (existing["state"] if existing else "new")
    if reset_lead:
        lead_value = None
    elif lead_id is not None:
        lead_value = lead_id
    else:
        lead_value = existing["lead_id"] if existing else None
    conn.execute(
        """
        INSERT INTO tg_sessions(
            telegram_user_id,state,source,lead_id,first_name,last_name,username,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
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
    row = conn.execute(
        "SELECT * FROM tg_sessions WHERE telegram_user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def create_lead_from_contact(user: dict[str, Any], phone: str) -> int:
    session = get_session(int(user["id"]))
    source = session["source"] if session else "telegram"
    name = normalize_name(user)
    conn = db()
    cur = conn.execute(
        """
        INSERT INTO leads(
          created_at,name,phone,source,page,preferred_channel,referrer,utm_json,status,
          telegram_user_id,telegram_username,telegram_first_name,telegram_last_name,
          lead_type,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            "trial_now",
            now_iso(),
        ),
    )
    lead_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    upsert_session(user, state="qualified", lead_id=lead_id)
    return lead_id


def get_lead(lead_id: int) -> sqlite3.Row | None:
    conn = db()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    return row


def update_lead(user_id: int, field: str, value: str) -> int | None:
    if field not in {"child_age", "preferred_time", "question"}:
        raise ValueError("unsupported field")
    session = get_session(user_id)
    if not session or not session["lead_id"]:
        return None
    lead_id = int(session["lead_id"])
    conn = db()
    conn.execute(
        f"UPDATE leads SET {field}=?, updated_at=? WHERE id=?",
        (value[:500], now_iso(), lead_id),
    )
    conn.commit()
    conn.close()
    return lead_id


def set_lead_status(lead_id: int, status: str) -> bool:
    if status not in STATUSES:
        return False
    conn = db()
    cur = conn.execute(
        "UPDATE leads SET status=?, updated_at=? WHERE id=?",
        (status, now_iso(), lead_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def set_lead_note(lead_id: int, note: str) -> bool:
    conn = db()
    cur = conn.execute(
        "UPDATE leads SET note=?, updated_at=? WHERE id=?",
        (note[:1000] or None, now_iso(), lead_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def log_message(
    user_id: int, direction: str, text: str, lead_id: int | None = None
) -> None:
    conn = db()
    conn.execute(
        """
        INSERT INTO tg_messages(created_at,telegram_user_id,lead_id,direction,text)
        VALUES(?,?,?,?,?)
        """,
        (now_iso(), user_id, lead_id, direction, text[:4000]),
    )
    conn.commit()
    conn.close()


def map_admin_message(
    admin_message_id: int, user_id: int | None, lead_id: int
) -> None:
    conn = db()
    conn.execute(
        """
        INSERT OR REPLACE INTO tg_admin_message_map(
            admin_message_id,telegram_user_id,lead_id,created_at
        ) VALUES(?,?,?,?)
        """,
        (admin_message_id, user_id, lead_id, now_iso()),
    )
    conn.commit()
    conn.close()


def mapped_lead(admin_message_id: int) -> tuple[int | None, int] | None:
    conn = db()
    row = conn.execute(
        """
        SELECT telegram_user_id,lead_id
        FROM tg_admin_message_map
        WHERE admin_message_id=?
        """,
        (admin_message_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    user_id = int(row["telegram_user_id"]) if row["telegram_user_id"] else None
    return user_id, int(row["lead_id"])


def safe_utm(row: sqlite3.Row) -> dict[str, str]:
    try:
        raw = json.loads(row["utm_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def lead_text(row: sqlite3.Row, *, detailed: bool = True) -> str:
    status = STATUSES.get(str(row["status"] or "new"), str(row["status"] or "new"))
    lines = [f"ELITE · заявка #{row['id']} · {status}"]
    if row["name"]:
        lines.append(f"Имя: {row['name']}")
    lines.append(f"Телефон: {row['phone']}")
    if row["child_age"]:
        lines.append(f"Возраст: {row['child_age']}")
    if row["preferred_time"]:
        lines.append(f"Когда удобно: {row['preferred_time']}")
    source = str(row["source"] or "website")
    lines.append(f"Источник: {source}")
    if detailed:
        if row["page"]:
            lines.append(f"Страница: {row['page']}")
        utm = safe_utm(row)
        useful = [
            f"{key}={utm[key]}"
            for key in ("utm_source", "utm_campaign", "utm_content", "utm_term")
            if utm.get(key)
        ]
        if useful:
            lines.append("UTM: " + " · ".join(useful))
        if row["question"]:
            lines.append(f"Вопрос: {row['question']}")
        if row["note"]:
            lines.append(f"Заметка: {row['note']}")
        if row["next_follow_up_at"]:
            lines.append(f"Вернуться: {row['next_follow_up_at']}")
    return "\n".join(lines)


def send_admin_lead(row: sqlite3.Row, *, mark_notified: bool = False) -> None:
    admin_id = admin_chat_id()
    if admin_id is None:
        return
    message = send_message(
        admin_id,
        lead_text(row),
        reply_markup=status_keyboard(int(row["id"]), str(row["status"] or "new")),
    )
    map_admin_message(
        int(message["message_id"]),
        int(row["telegram_user_id"]) if row["telegram_user_id"] else None,
        int(row["id"]),
    )
    if mark_notified:
        conn = db()
        conn.execute(
            "UPDATE leads SET admin_notified_at=?, updated_at=? WHERE id=?",
            (now_iso(), now_iso(), int(row["id"])),
        )
        conn.commit()
        conn.close()


def notify_pending_website_leads(limit: int = 20) -> None:
    admin_id = admin_chat_id()
    if admin_id is None:
        return
    conn = db()
    rows = conn.execute(
        """
        SELECT * FROM leads
        WHERE admin_notified_at IS NULL
          AND telegram_user_id IS NULL
        ORDER BY id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    for row in rows:
        send_admin_lead(row, mark_notified=True)


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
        + "запись в ELITE займёт один шаг. Нажмите «Поделиться контактом» — "
        "Telegram передаст ваш номер, а имя уже есть в профиле. После этого можно "
        "уточнить возраст ребёнка или сразу написать вопрос.",
        reply_markup=contact_keyboard(),
    )


def handle_admin_registration(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    if not is_admin_user(user, chat_id):
        send_message(chat_id, "Команда недоступна.")
        return
    set_setting("telegram_admin_chat_id", str(chat_id))
    send_message(
        chat_id,
        "Elite менеджер подключён. Сюда будут приходить заявки с сайта и из Telegram.\n\n"
        "Команды: /leads — последние заявки, /stats — сводка, /lead 12 — карточка, "
        "/note 12 текст — заметка. Статус меняется кнопками под заявкой.",
    )
    notify_pending_website_leads()


def handle_contact(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    contact = message.get("contact") or {}
    contact_user_id = contact.get("user_id")
    if contact_user_id is not None and int(contact_user_id) != int(user["id"]):
        send_message(
            chat_id,
            "Нужен именно ваш контакт. Нажмите кнопку «Поделиться контактом» ниже.",
            reply_markup=contact_keyboard(),
        )
        return
    phone = str(contact.get("phone_number") or "").strip()
    if not phone:
        send_message(
            chat_id,
            "Не удалось получить номер. Нажмите кнопку ещё раз.",
            reply_markup=contact_keyboard(),
        )
        return
    lead_id = create_lead_from_contact(user, phone)
    log_message(int(user["id"]), "in", "[contact shared]", lead_id)
    row = get_lead(lead_id)
    if row:
        send_admin_lead(row, mark_notified=True)
    send_message(
        chat_id,
        "Готово — заявка создана. Если удобно, выберите возраст ребёнка. "
        "Это необязательно: можно сразу написать вопрос.",
        reply_markup={"remove_keyboard": True},
    )
    send_message(chat_id, "Возраст ребёнка:", reply_markup=age_keyboard())


def handle_user_callback(query: dict[str, Any]) -> bool:
    user = query["from"]
    data = str(query.get("data") or "")
    chat = (query.get("message") or {}).get("chat") or {}
    chat_id = int(chat.get("id") or user["id"])
    user_id = int(user["id"])
    if data.startswith("age:"):
        value = data.split(":", 1)[1]
        label = {
            "3": "3 года",
            "4": "4 года",
            "5": "5 лет",
            "6-10": "6–10 лет",
            "later": "уточнить позже",
        }.get(value, value)
        lead_id = update_lead(user_id, "child_age", label)
        answer_callback(query["id"], "Сохранили")
        if lead_id:
            admin_id = admin_chat_id()
            if admin_id:
                send_message(admin_id, f"Заявка #{lead_id}: возраст — {label}")
        send_message(chat_id, "Когда обычно удобнее?", reply_markup=time_keyboard())
        return True
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
            admin_id = admin_chat_id()
            if admin_id:
                send_message(admin_id, f"Заявка #{lead_id}: удобное время — {label}")
        send_message(
            chat_id,
            "Спасибо. Администратор ELITE уже видит заявку. "
            "Можете написать сюда любой вопрос — ответ придёт в этот же чат.",
        )
        return True
    return False


def handle_admin_callback(query: dict[str, Any]) -> bool:
    user = query["from"]
    chat = (query.get("message") or {}).get("chat") or {}
    chat_id = int(chat.get("id") or user["id"])
    if not is_admin_user(user, chat_id):
        return False
    data = str(query.get("data") or "")
    if data.startswith("leadstatus:"):
        _, lead_id_raw, status = data.split(":", 2)
        try:
            lead_id = int(lead_id_raw)
        except ValueError:
            answer_callback(query["id"], "Некорректная заявка")
            return True
        if not set_lead_status(lead_id, status):
            answer_callback(query["id"], "Не удалось обновить")
            return True
        row = get_lead(lead_id)
        answer_callback(query["id"], STATUSES.get(status, status))
        message = query.get("message") or {}
        if row and message.get("message_id"):
            edit_message(
                chat_id,
                int(message["message_id"]),
                lead_text(row),
                reply_markup=status_keyboard(lead_id, status),
            )
        return True
    if data.startswith("leadshow:"):
        try:
            lead_id = int(data.split(":", 1)[1])
        except ValueError:
            answer_callback(query["id"])
            return True
        row = get_lead(lead_id)
        answer_callback(query["id"])
        if row:
            send_message(chat_id, lead_text(row))
        return True
    return False


def handle_callback(query: dict[str, Any]) -> None:
    if handle_admin_callback(query):
        return
    if handle_user_callback(query):
        return
    answer_callback(query["id"])


def handle_admin_reply(message: dict[str, Any]) -> bool:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    if not is_admin_user(user, chat_id):
        return False
    reply_to = message.get("reply_to_message") or {}
    if not reply_to:
        return False
    mapped = mapped_lead(int(reply_to.get("message_id") or 0))
    text = str(message.get("text") or "").strip()
    if not mapped or not text:
        return False
    target_user_id, lead_id = mapped
    if target_user_id is None:
        send_message(
            chat_id,
            f"Заявка #{lead_id} пришла через форму сайта. Ответить в Telegram нельзя — "
            "свяжитесь по телефону из карточки.",
        )
        return True
    send_message(target_user_id, "ELITE: " + text)
    log_message(target_user_id, "admin_out", text, lead_id)
    send_message(chat_id, "Ответ отправлен.")
    return True


def admin_list(chat_id: int, limit: int = 10) -> None:
    conn = db()
    rows = conn.execute(
        "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 30),)
    ).fetchall()
    conn.close()
    if not rows:
        send_message(chat_id, "Заявок пока нет.")
        return
    text = ["Последние заявки:"]
    for row in rows:
        status = STATUSES.get(str(row["status"] or "new"), str(row["status"] or "new"))
        name = row["name"] or "без имени"
        text.append(f"#{row['id']} · {status} · {name} · {row['phone']} · {row['source'] or 'website'}")
    text.append("\nКарточка: /lead НОМЕР")
    send_message(chat_id, "\n".join(text))


def admin_stats(chat_id: int) -> None:
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = db()
    rows = conn.execute("SELECT status,source,created_at FROM leads WHERE created_at>=?", (since,)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    conn.close()
    status_counts = Counter(str(row["status"] or "new") for row in rows)
    source_counts = Counter(str(row["source"] or "website") for row in rows)
    lines = [f"ELITE · лиды\nВсего в базе: {total}\nЗа 30 дней: {len(rows)}"]
    if status_counts:
        lines.append("\nПо стадиям:")
        for key, count in status_counts.most_common():
            lines.append(f"• {STATUSES.get(key, key)}: {count}")
    if source_counts:
        lines.append("\nИсточники:")
        for key, count in source_counts.most_common(6):
            lines.append(f"• {key}: {count}")
    send_message(chat_id, "\n".join(lines))


def handle_admin_command(message: dict[str, Any]) -> bool:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    text = str(message.get("text") or "").strip()
    if not is_admin_user(user, chat_id):
        return False
    if text == "/leads" or text.startswith("/leads "):
        parts = text.split(maxsplit=1)
        try:
            limit = int(parts[1]) if len(parts) > 1 else 10
        except ValueError:
            limit = 10
        admin_list(chat_id, limit)
        return True
    if text == "/stats":
        admin_stats(chat_id)
        return True
    if text.startswith("/lead "):
        try:
            lead_id = int(text.split(maxsplit=1)[1])
        except ValueError:
            send_message(chat_id, "Формат: /lead 12")
            return True
        row = get_lead(lead_id)
        if not row:
            send_message(chat_id, "Заявка не найдена.")
        else:
            message_out = send_message(
                chat_id,
                lead_text(row),
                reply_markup=status_keyboard(lead_id, str(row["status"] or "new")),
            )
            map_admin_message(
                int(message_out["message_id"]),
                int(row["telegram_user_id"]) if row["telegram_user_id"] else None,
                lead_id,
            )
        return True
    if text.startswith("/note "):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            send_message(chat_id, "Формат: /note 12 текст заметки")
            return True
        try:
            lead_id = int(parts[1])
        except ValueError:
            send_message(chat_id, "Формат: /note 12 текст заметки")
            return True
        if set_lead_note(lead_id, parts[2]):
            send_message(chat_id, f"Заметка к заявке #{lead_id} сохранена.")
        else:
            send_message(chat_id, "Заявка не найдена.")
        return True
    if text == "/help":
        send_message(
            chat_id,
            "Elite менеджер:\n"
            "/leads — последние заявки\n"
            "/stats — статистика за 30 дней\n"
            "/lead 12 — карточка\n"
            "/note 12 текст — заметка\n"
            "Статусы меняются кнопками под карточкой.\n"
            "На сообщения от родителей в боте отвечайте через Reply.",
        )
        return True
    return False


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
    if handle_admin_command(message):
        return

    session = get_session(int(user["id"]))
    lead_id = int(session["lead_id"]) if session and session["lead_id"] else None
    log_message(int(user["id"]), "in", text, lead_id)
    admin_id = admin_chat_id()
    if lead_id:
        update_lead(int(user["id"]), "question", text)
        if admin_id:
            send_message(admin_id, f"Вопрос по заявке #{lead_id}:\n{text}")
        send_message(chat_id, "Передал вопрос администратору. Ответ придёт сюда.")
    else:
        if admin_id:
            identity = normalize_name(user) or f"Telegram {user['id']}"
            send_message(admin_id, f"Вопрос до передачи контакта · {identity}:\n{text}")
        send_message(
            chat_id,
            "Вопрос передан. Чтобы записать вас на пробное без ручного ввода номера, "
            "нажмите «Поделиться контактом».",
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


def check_configuration() -> int:
    db().close()
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN is not configured", file=sys.stderr)
        return 2
    try:
        result = api("getMe", timeout=12).get("result") or {}
    except (requests.RequestException, RuntimeError):
        print("Telegram token validation failed", file=sys.stderr)
        return 3
    username = result.get("username") or "<unknown>"
    print(f"Telegram bot OK: @{username}")
    return 0


def main() -> None:
    if "--check" in sys.argv:
        raise SystemExit(check_configuration())
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")
    db().close()
    offset = 0
    while True:
        try:
            notify_pending_website_leads()
            result = api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=35,
            )["result"]
            for update in result:
                offset = max(offset, int(update["update_id"]) + 1)
                try:
                    process_update(update)
                except Exception as exc:
                    print(
                        f"update processing failed: {type(exc).__name__}",
                        flush=True,
                    )
        except (requests.RequestException, RuntimeError, sqlite3.Error) as exc:
            print(f"bot loop error: {type(exc).__name__}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
