from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


BTN_NEW = "🆕 Новая проблема"
BTN_VARIANT = "🎯 Конкретный вариант"
BTN_STATS = "📊 Статистика"
BTN_VARIANTS = "📉 Баллы по вариантам"
BTN_CANCEL = "❌ Отмена"


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW), KeyboardButton(text=BTN_VARIANT)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_VARIANTS)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Новая проблема", callback_data="new")],
            [InlineKeyboardButton(text="🎯 Конкретный вариант", callback_data="variant_panel:1")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="📉 Баллы по вариантам", callback_data="variants")],
        ]
    )


def variant_picker_keyboard(page: int = 1, per_page: int = 10, total: int = 50) -> InlineKeyboardMarkup:
    page = max(1, page)
    max_page = (total + per_page - 1) // per_page
    page = min(page, max_page)

    start = (page - 1) * per_page + 1
    end = min(total, start + per_page - 1)

    rows = []
    current = start
    while current <= end:
        row = []
        for _ in range(5):
            if current <= end:
                row.append(InlineKeyboardButton(text=str(current), callback_data=f"select_variant:{current}"))
                current += 1
        rows.append(row)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"variant_panel:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"variant_panel:{page + 1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text="Вернуться в меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_keyboard(variant: int, has_text: bool, has_screen: bool) -> InlineKeyboardMarkup:
    rows = []

    view_row = []
    if has_text:
        view_row.append(InlineKeyboardButton(text="📖 Читать текст", callback_data=f"text:{variant}"))
    if has_screen:
        view_row.append(InlineKeyboardButton(text="🖼 Смотреть скрин", callback_data=f"screen:{variant}"))
    if view_row:
        rows.append(view_row)
    else:
        rows.append([InlineKeyboardButton(text="Текст/скрин не найдены", callback_data=f"missing:{variant}")])

    rows.append([InlineKeyboardButton(text="✍️ Писать авторскую позицию", callback_data=f"answer:{variant}")])
    rows.append([
        InlineKeyboardButton(text="🎯 Другой вариант", callback_data="variant_panel:1"),
        InlineKeyboardButton(text="🆕 Новая проблема", callback_data="new"),
    ])
    rows.append([InlineKeyboardButton(text="Вернуться в меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Новая проблема", callback_data="new")],
            [InlineKeyboardButton(text="🎯 Конкретный вариант", callback_data="variant_panel:1")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="📉 Баллы по вариантам", callback_data="variants")],
        ]
    )
