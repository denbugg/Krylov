from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import get_settings
from app.data_loader import TaskRepository, VariantTask
from app.gemini_eval import evaluate_author_position
from app.keyboards import (
    BTN_CANCEL,
    BTN_NEW,
    BTN_STATS,
    BTN_VARIANT,
    BTN_VARIANTS,
    after_result_keyboard,
    main_menu_keyboard,
    main_reply_keyboard,
    task_keyboard,
    variant_picker_keyboard,
)
from app.states import TrainingStates
from app.storage import Storage


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()

settings = get_settings()
repo = TaskRepository(settings.dataset_path, settings.report_path, settings.out_dir)
storage = Storage(settings.db_path)


def user_id_from_message(message: Message) -> int:
    if not message.from_user:
        raise RuntimeError("No from_user in message")
    return int(message.from_user.id)


def user_id_from_callback(callback: CallbackQuery) -> int:
    if not callback.from_user:
        raise RuntimeError("No from_user in callback")
    return int(callback.from_user.id)


def escape(value: str) -> str:
    return html.escape(value or "")


def task_intro(task: VariantTask) -> str:
    title = f"\n<b>Источник:</b> {escape(task.title)}" if task.title else ""
    return (
        f"<b>Вариант {task.variant}</b>\n"
        f"<b>Тема:</b> {escape(task.topic)}\n"
        f"<b>Проблема:</b> {escape(task.problem)}"
        f"{title}\n\n"
        "Выбери удобный формат чтения, затем нажми «Писать авторскую позицию»."
    )


def split_long_text(text: str, limit: int = 3900) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


async def show_main_menu(message: Message) -> None:
    await message.answer(
        "<b>Меню тренажёра</b>\n\n"
        "Выбери действие на нижней панели или на кнопках ниже.",
        reply_markup=main_menu_keyboard(),
    )


async def send_task(message_or_callback, task: VariantTask, state: FSMContext | None = None) -> None:
    markup = task_keyboard(
        task.variant,
        has_text=repo.has_text(task),
        has_screen=repo.has_screenshot(task),
    )

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(task_intro(task), reply_markup=markup)
    else:
        await message_or_callback.answer(task_intro(task), reply_markup=markup)

    if state:
        await state.update_data(variant=task.variant)


async def choose_new_task(user_id: int) -> VariantTask:
    all_tasks = repo.all()
    done = await storage.get_done_variants(user_id)
    last_topic = await storage.get_last_topic(user_id)

    not_done = [task for task in all_tasks if task.variant not in done]
    if not_done:
        different_topic = [task for task in not_done if task.topic != last_topic]
        return (different_topic or not_done)[0]

    latest_scores = await storage.get_latest_scores(user_id)
    if latest_scores:
        weakest_variant = latest_scores[0].variant
        return repo.get(weakest_variant)

    return all_tasks[0]


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Тренажёр авторской позиции ЕГЭ</b>\n\n"
        "Я присылаю текст варианта, ты формулируешь авторскую позицию, "
        "а Gemini сравнивает её с эталоном по смыслу.\n\n"
        "Основное управление — кнопками на панели ниже.",
        reply_markup=main_reply_keyboard(),
    )
    await show_main_menu(message)


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущая отработка сброшена.", reply_markup=main_reply_keyboard())
    await show_main_menu(message)


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("Текущая отработка сброшена.", reply_markup=main_reply_keyboard())
    await show_main_menu(callback.message)


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer("Главное меню.", reply_markup=main_reply_keyboard())
    await show_main_menu(callback.message)


@router.message(Command("new"))
@router.message(F.text == BTN_NEW)
async def cmd_new(message: Message, state: FSMContext) -> None:
    task = await choose_new_task(user_id_from_message(message))
    await send_task(message, task, state)


@router.callback_query(F.data == "new")
async def cb_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    task = await choose_new_task(user_id_from_callback(callback))
    await send_task(callback, task, state)


@router.message(F.text == BTN_VARIANT)
async def msg_variant_panel(message: Message) -> None:
    await message.answer(
        "<b>Выбери вариант</b>\n\n"
        "Можно листать страницы вариантов стрелками.",
        reply_markup=variant_picker_keyboard(page=1, total=len(repo.all())),
    )


@router.callback_query(F.data.startswith("variant_panel:"))
async def cb_variant_panel(callback: CallbackQuery) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[1])
    await callback.message.answer(
        "<b>Выбери вариант</b>",
        reply_markup=variant_picker_keyboard(page=page, total=len(repo.all())),
    )


@router.callback_query(F.data.startswith("select_variant:"))
async def cb_select_variant(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    variant = int(callback.data.split(":")[1])
    task = repo.get(variant)
    await send_task(callback, task, state)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# Команды оставлены как запасной способ, но основной интерфейс — кнопочный.
@router.message(Command("variant"))
async def cmd_variant(message: Message, command: CommandObject, state: FSMContext) -> None:
    if not command.args:
        await message.answer(
            "Выбери вариант кнопками:",
            reply_markup=variant_picker_keyboard(page=1, total=len(repo.all())),
        )
        return

    try:
        number = int(command.args.strip())
        task = repo.get(number)
    except Exception:
        await message.answer("Не нашёл такой вариант. Доступны варианты 1–50.")
        return

    await send_task(message, task, state)


@router.callback_query(F.data.startswith("text:"))
async def cb_text(callback: CallbackQuery) -> None:
    await callback.answer()
    variant = int(callback.data.split(":")[1])
    task = repo.get(variant)
    path = repo.text_path(task)

    if not path.exists():
        await callback.message.answer("Текстовый файл не найден. Проверь папку <code>out/texts</code>.")
        return

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        await callback.message.answer("Текстовый файл пустой.")
        return

    await callback.message.answer(f"<b>Текст варианта {variant}</b>")
    for chunk in split_long_text(text):
        await callback.message.answer(escape(chunk))

    await callback.message.answer(
        "Когда прочитаешь, нажми кнопку:",
        reply_markup=task_keyboard(variant, has_text=repo.has_text(task), has_screen=repo.has_screenshot(task)),
    )


@router.callback_query(F.data.startswith("screen:"))
async def cb_screen(callback: CallbackQuery) -> None:
    await callback.answer()
    variant = int(callback.data.split(":")[1])
    task = repo.get(variant)
    path = repo.screenshot_path(task)

    if not path.exists():
        await callback.message.answer("Скриншот не найден. Проверь папку <code>out/screens</code>.")
        return

    await callback.message.answer_photo(
        FSInputFile(path),
        caption=f"Вариант {variant}: {task.problem}",
    )
    await callback.message.answer(
        "Когда прочитаешь, нажми кнопку:",
        reply_markup=task_keyboard(variant, has_text=repo.has_text(task), has_screen=repo.has_screenshot(task)),
    )


@router.callback_query(F.data.startswith("missing:"))
async def cb_missing(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Для этого варианта не найден текст или скрин.\n"
        "Проверь, что рядом с ботом есть папки:\n"
        "<code>out/texts</code>\n"
        "<code>out/screens</code>"
    )


@router.callback_query(F.data.startswith("answer:"))
async def cb_answer(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    variant = int(callback.data.split(":")[1])
    task = repo.get(variant)
    await state.set_state(TrainingStates.waiting_author_position)
    await state.update_data(variant=variant)

    await callback.message.answer(
        f"<b>Вариант {variant}</b>\n"
        f"<b>Проблема:</b> {escape(task.problem)}\n\n"
        "Напиши авторскую позицию одним-двумя предложениями."
    )


@router.message(TrainingStates.waiting_author_position)
async def handle_author_position(message: Message, state: FSMContext) -> None:
    user_id = user_id_from_message(message)
    data = await state.get_data()
    variant = int(data.get("variant"))
    task = repo.get(variant)
    student_answer = message.text or ""

    if student_answer in {BTN_NEW, BTN_VARIANT, BTN_STATS, BTN_VARIANTS, BTN_CANCEL}:
        await message.answer(
            "Сейчас я жду авторскую позицию текстом. Для выхода нажми «❌ Отмена».",
            reply_markup=main_reply_keyboard(),
        )
        return

    if len(student_answer.strip()) < 10:
        await message.answer("Ответ слишком короткий. Напиши авторскую позицию одним-двумя предложениями.")
        return

    status = await message.answer("Проверяю авторскую позицию через Gemini...")

    try:
        result = await evaluate_author_position(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            topic=task.topic,
            problem=task.problem,
            canonical_position=task.author_position,
            student_answer=student_answer,
        )
    except Exception as exc:
        logger.exception("Gemini evaluation failed")
        await status.edit_text(
            "Не удалось получить оценку от Gemini.\n\n"
            f"<code>{escape(str(exc)[:1500])}</code>"
        )
        return

    await storage.save_attempt(
        user_id=user_id,
        variant=variant,
        topic=task.topic,
        problem=task.problem,
        student_answer=student_answer,
        author_score=result.score,
        label=result.label,
        confidence=result.confidence,
        feedback=result.feedback,
        safe_revision=result.safe_revision,
        raw=result.raw,
    )

    matched = "\n".join(f"• {escape(x)}" for x in result.matched_points) or "—"
    missing = "\n".join(f"• {escape(x)}" for x in result.missing_points) or "—"
    wrong = "\n".join(f"• {escape(x)}" for x in result.wrong_points) or "—"

    answer = (
        f"<b>Вариант {variant}</b>\n"
        f"<b>Итог:</b> {result.score:.1f}/3\n"
        f"<b>Уверенность:</b> {result.confidence:.2f}\n\n"
        f"<b>Комментарий:</b>\n{escape(result.feedback) or '—'}\n\n"
        f"<b>Совпало:</b>\n{matched}\n\n"
        f"<b>Не хватает:</b>\n{missing}\n\n"
        f"<b>Ошибочные/лишние смыслы:</b>\n{wrong}\n\n"
        f"<b>Безопасная формулировка:</b>\n{escape(result.safe_revision) or escape(task.author_position)}"
    )

    await status.edit_text(answer[:4096])
    if len(answer) > 4096:
        await message.answer(answer[4096:8192])

    await state.clear()
    await message.answer(
        "Результат сохранён. Выбери следующее действие:",
        reply_markup=after_result_keyboard(),
    )


@router.message(Command("variants"))
@router.message(F.text == BTN_VARIANTS)
async def cmd_variants(message: Message) -> None:
    await send_variants(message, user_id_from_message(message))


@router.callback_query(F.data == "variants")
async def cb_variants(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_variants(callback.message, user_id_from_callback(callback))


async def send_variants(message: Message, user_id: int) -> None:
    scores = await storage.get_latest_scores(user_id)
    if not scores:
        await message.answer("Пока нет отработанных вариантов. Нажми «🆕 Новая проблема».")
        return

    lines = [
        "<b>Баллы по вариантам</b>",
        "Формат: авторская позиция / максимум.",
        "Сортировка: от слабых к сильным.\n",
    ]

    for item in scores:
        task = repo.get(item.variant)
        lines.append(
            f"<b>{item.variant}</b> — {item.author_score:.1f}/3 "
            f"· {escape(item.topic)}\n"
            f"Проблема: {escape(task.problem)}"
        )

    await message.answer("\n\n".join(lines)[:4096], reply_markup=main_menu_keyboard())


@router.message(Command("stats"))
@router.message(F.text == BTN_STATS)
async def cmd_stats(message: Message) -> None:
    await send_stats(message, user_id_from_message(message))


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_stats(callback.message, user_id_from_callback(callback))


async def send_stats(message: Message, user_id: int) -> None:
    attempt_count = await storage.get_attempt_count(user_id)
    latest = await storage.get_latest_scores(user_id)

    if not latest:
        await message.answer("Статистики пока нет. Нажми «🆕 Новая проблема».")
        return

    unique_count = len(latest)
    avg = sum(item.author_score for item in latest) / unique_count
    total_possible = unique_count * 3
    total_scored = sum(item.author_score for item in latest)
    progress = (total_scored / total_possible * 100) if total_possible else 0.0
    topic_stats = await storage.get_topic_stats(user_id)

    lines = [
        "<b>Статистика</b>",
        f"Всего попыток: <b>{attempt_count}</b>",
        f"Уникальных вариантов: <b>{unique_count}</b>",
        f"Средний балл: <b>{avg:.2f}/3</b>",
        f"Набрано: <b>{total_scored:.1f}/{total_possible}</b> ({progress:.0f}%)",
        "",
        "<b>Темы от слабых к сильным:</b>",
    ]

    for topic, count, avg_score in topic_stats:
        lines.append(f"• {escape(topic)} — {avg_score:.2f}/3 · вариантов: {count}")

    await message.answer("\n".join(lines)[:4096], reply_markup=main_menu_keyboard())


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(
        "Выбери действие на панели ниже.",
        reply_markup=main_reply_keyboard(),
    )
    await show_main_menu(message)


async def main() -> None:
    await storage.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Bot started with %d variants", len(repo.all()))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
