from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import bot as core


LEAD_TYPE_LABELS = {
    "trial_now": "Пробное · группа 3–6 лет",
    "future_group": "Будущая старшая группа",
}
DISCOVERY_LABELS = {
    "search": "Яндекс / поиск",
    "maps": "Яндекс Карты",
    "local_chat": "Районный чат",
    "recommendation": "Рекомендация",
    "social": "Соцсети",
    "other": "Другое",
    "skip": "Не указано",
}


def ensure_extensions() -> None:
    conn = core.db()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
    if "discovery_source" not in columns:
        conn.execute("ALTER TABLE leads ADD COLUMN discovery_source TEXT")
    conn.commit()
    conn.close()


def age_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [
        [{"text": "3 года", "callback_data": "age:3"}, {"text": "4 года", "callback_data": "age:4"}],
        [{"text": "5 лет", "callback_data": "age:5"}, {"text": "6 лет", "callback_data": "age:6"}],
        [{"text": "Старше · будущая группа", "callback_data": "age:older"}, {"text": "Уточнить позже", "callback_data": "age:later"}],
    ]}


def discovery_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [
        [{"text": "Яндекс / поиск", "callback_data": "discover:search"}, {"text": "Яндекс Карты", "callback_data": "discover:maps"}],
        [{"text": "Районный чат", "callback_data": "discover:local_chat"}, {"text": "Рекомендация", "callback_data": "discover:recommendation"}],
        [{"text": "Соцсети", "callback_data": "discover:social"}, {"text": "Другое", "callback_data": "discover:other"}],
        [{"text": "Пропустить", "callback_data": "discover:skip"}],
    ]}


def handle_start(message: dict[str, Any]) -> None:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    parts = str(message.get("text") or "").split(maxsplit=1)
    source = parts[1].strip()[:64] if len(parts) > 1 else "direct"
    core.upsert_session(user, source=source, state="await_contact", reset_lead=True)
    first_name = str(user.get("first_name") or "").strip()
    greeting = f"{first_name}, " if first_name else ""
    core.send_message(
        chat_id,
        greeting + "запишем вас на бесплатное пробное занятие ELITE. Нажмите «Поделиться контактом» — Telegram передаст ваш номер, и заявка сразу попадёт администратору.",
        reply_markup=core.contact_keyboard(),
    )


def set_discovery(user_id: int, value: str) -> int | None:
    session = core.get_session(user_id)
    if not session or not session["lead_id"]:
        return None
    lead_id = int(session["lead_id"])
    conn = core.db()
    conn.execute("UPDATE leads SET discovery_source=?,updated_at=? WHERE id=?", (value[:60], core.now_iso(), lead_id))
    conn.commit()
    conn.close()
    return lead_id


def set_lead_type(lead_id: int, value: str) -> None:
    conn = core.db()
    conn.execute("UPDATE leads SET lead_type=?,updated_at=? WHERE id=?", (value, core.now_iso(), lead_id))
    conn.commit()
    conn.close()


_original_lead_text = core.lead_text


def lead_text(row) -> str:
    base = _original_lead_text(row)
    keys = set(row.keys())
    lead_type = str(row["lead_type"] or "trial_now") if "lead_type" in keys else "trial_now"
    extra = ["Цель: " + LEAD_TYPE_LABELS.get(lead_type, lead_type)]
    if "discovery_source" in keys and row["discovery_source"]:
        extra.append("Узнали о клубе: " + DISCOVERY_LABELS.get(str(row["discovery_source"]), str(row["discovery_source"])))
    return base + "\n" + "\n".join(extra)


_original_callback = core.handle_callback


def handle_callback(query: dict[str, Any]) -> None:
    user = query["from"]
    chat_id = int(((query.get("message") or {}).get("chat") or {}).get("id") or user["id"])
    data = str(query.get("data") or "")

    if data in {"age:6", "age:older"}:
        label = "6 лет" if data == "age:6" else "старше 6 лет"
        lead_id = core.update_lead(int(user["id"]), "child_age", label)
        if lead_id and data == "age:older":
            set_lead_type(lead_id, "future_group")
        core.answer_callback(query["id"], "Сохранили")
        if lead_id and core.admin_chat_id():
            suffix = " · будущая старшая группа" if data == "age:older" else ""
            core.send_message(core.admin_chat_id(), f"Заявка #{lead_id}: возраст — {label}{suffix}")
        core.send_message(chat_id, "Когда обычно удобнее?", reply_markup=core.time_keyboard())
        return

    if data.startswith("discover:"):
        value = data.split(":", 1)[1]
        if value not in DISCOVERY_LABELS:
            value = "other"
        lead_id = set_discovery(int(user["id"]), value)
        core.answer_callback(query["id"], "Спасибо")
        if lead_id and value != "skip" and core.admin_chat_id():
            core.send_message(core.admin_chat_id(), f"Заявка #{lead_id}: откуда узнали — {DISCOVERY_LABELS[value]}")
        core.send_message(chat_id, "Спасибо. Всё записали — администратор свяжется с вами.")
        return

    was_time = data.startswith("time:")
    _original_callback(query)
    if was_time:
        core.send_message(chat_id, "Если несложно, откуда вы узнали об ELITE? Это необязательно.", reply_markup=discovery_keyboard())


def filtered_leads(chat_id: int, lead_type: str, limit: int = 20) -> None:
    conn = core.db()
    rows = conn.execute(
        "SELECT * FROM leads WHERE lead_type=? ORDER BY id DESC LIMIT ?",
        (lead_type, min(max(limit, 1), 30)),
    ).fetchall()
    conn.close()
    if not rows:
        core.send_message(chat_id, "Заявок этой категории пока нет.")
        return
    lines = [LEAD_TYPE_LABELS[lead_type] + ":"]
    for row in rows:
        status = core.STATUSES.get(str(row["status"] or "new"), str(row["status"] or "new"))
        lines.append(f"#{row['id']} · {status} · {core.decrypt_text(row['name']) or 'без имени'} · {core.decrypt_text(row['phone'])}")
    lines.append("\nКарточка: /lead НОМЕР")
    core.send_message(chat_id, "\n".join(lines))


_original_admin_command = core.handle_admin_command


def handle_admin_command(message: dict[str, Any]) -> bool:
    user = message["from"]
    chat_id = int(message["chat"]["id"])
    text = str(message.get("text") or "").strip().lower()
    if not core.is_admin_user(user, chat_id):
        return False
    if text in {"/leads trial", "/leads current"}:
        filtered_leads(chat_id, "trial_now")
        return True
    if text in {"/leads future", "/leads senior"}:
        filtered_leads(chat_id, "future_group")
        return True
    return _original_admin_command(message)


_original_stats = core.admin_stats


def admin_stats(chat_id: int) -> None:
    _original_stats(chat_id)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = core.db()
    rows = conn.execute("SELECT lead_type FROM leads WHERE created_at>=?", (since,)).fetchall()
    conn.close()
    counts = Counter(str(row["lead_type"] or "trial_now") for row in rows)
    if counts:
        core.send_message(chat_id, "По цели за 30 дней:\n" + "\n".join(f"• {LEAD_TYPE_LABELS.get(key, key)}: {value}" for key, value in counts.items()))


ensure_extensions()
core.age_keyboard = age_keyboard
core.handle_start = handle_start
core.handle_callback = handle_callback
core.lead_text = lead_text
core.handle_admin_command = handle_admin_command
core.admin_stats = admin_stats

if __name__ == "__main__":
    core.main()
