
import asyncio
import html
import logging
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError


# ==========================================
# НАСТРОЙКИ
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = 7837011810

CHANNEL_ID = "@zapillspost"

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN")


# ==========================================
# БОТ
# ==========================================

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# ==========================================
# БАЗА ДАННЫХ
# ==========================================

db = sqlite3.connect("suggestions.db")

db.execute("""
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
)
""")

db.commit()


def get_proposal(proposal_id):

    row = db.execute(
        """
        SELECT id, user_id, chat_id, message_id,
               author_name, status
        FROM suggestions
        WHERE id = ?
        """,
        (proposal_id,)
    ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "user_id": row[1],
        "chat_id": row[2],
        "message_id": row[3],
        "author_name": row[4],
        "status": row[5]
    }


# ==========================================
# СОСТОЯНИЯ
# ==========================================

class UserStates(StatesGroup):
    waiting_post = State()


class AdminStates(StatesGroup):
    waiting_reason = State()


# ==========================================
# КЛАВИАТУРЫ
# ==========================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="📩 Предложить пост"
            )
        ]
    ],
    resize_keyboard=True
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="❌ Отмена"
            )
        ]
    ],
    resize_keyboard=True
)


def admin_keyboard(proposal_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{proposal_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{proposal_id}"
                )
            ]
        ]
    )


# ==========================================
# АВТОР ПОСТА
# ==========================================

def make_author(user_id, author_name):

    name = html.escape(author_name)

    return (
        f'👤: <a href="tg://user?id={user_id}">'
        f'{name}</a>'
    )


# ==========================================
# ПРИВЕТСТВИЕ
# ==========================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "👋 Привет!\n\n"
        "Здесь ты можешь поделиться тем, "
        "что сейчас делаешь.\n\n"
        "Отправляй истории, фотографии "
        "или видео в предложку.\n\n"
        "📩 Нажми кнопку ниже.",
        reply_markup=main_keyboard
    )


# ==========================================
# НАЧАТЬ ПРЕДЛОЖКУ
# ==========================================

@dp.message(F.text == "📩 Предложить пост")
async def start_proposal(
    message: Message,
    state: FSMContext
):

    await state.set_state(
        UserStates.waiting_post
    )

    await message.answer(
        "📩 Отправь свой пост.\n\n"
        "Можно отправить текст, фото "
        "или видео с подписью.\n\n"
        "Для отмены нажми кнопку ниже.",
        reply_markup=cancel_keyboard
    )


# ==========================================
# ОТМЕНА
# ==========================================

@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "❌ Предложка отменена.",
        reply_markup=main_keyboard
    )


# ==========================================
# ПОЛУЧЕНИЕ ПОСТА
# ==========================================

@dp.message(UserStates.waiting_post)
async def receive_post(
    message: Message,
    state: FSMContext
):

    if not (
        message.text
        or message.photo
        or message.video
    ):

        await message.answer(
            "Отправь текст, фото или видео."
        )

        return

    user = message.from_user

    author_name = user.full_name or "Пользователь"

    cursor = db.execute(
        """
        INSERT INTO suggestions (
            user_id,
            chat_id,
            message_id,
            author_name,
            status
        )
        VALUES (?, ?, ?, ?, 'pending')
        """,
        (
            user.id,
            message.chat.id,
            message.message_id,
            author_name
        )
    )

    proposal_id = cursor.lastrowid

    db.commit()

    author = make_author(
        user.id,
        author_name
    )

    admin_text = (
        f"📩 <b>Новая заявка #{proposal_id}</b>\n\n"
        f"{author}\n"
        f"🆔 ID: <code>{user.id}</code>"
    )

    try:

        # Копируем оригинал админу
        # Без отметки «Переслано от»

        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=admin_keyboard(proposal_id)
        )

        await bot.send_message(
            ADMIN_ID,
            admin_text
        )

        await message.answer(
            "✅ Твой пост отправлен администратору!\n\n"
            "Ожидай решения.",
            reply_markup=main_keyboard
        )

        await state.clear()

    except TelegramAPIError as error:

        logging.exception(error)

        await message.answer(
            "❌ Не удалось отправить пост."
        )


# ==========================================
# ПУБЛИКАЦИЯ ПОСТА
# ==========================================

async def publish_post(proposal):

    user_id = proposal["user_id"]

    chat_id = proposal["chat_id"]

    message_id = proposal["message_id"]

    author_name = proposal["author_name"]

    author = make_author(
        user_id,
        author_name
    )

    # Копируем исходное сообщение
    # Без пересылки и без отметки источника

    original = await bot.copy_message(
        chat_id=CHANNEL_ID,
        from_chat_id=chat_id,
        message_id=message_id
    )

    # ======================================
    # ТЕКСТ
    # ======================================

    if original:

        # Если это текстовый пост,
        # добавляем автора отдельной строкой

        # Удаляем копию и отправляем
        # итоговое сообщение с автором

        await bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=original.message_id
        )

        # Получаем текст исходного сообщения
        # Через копирование сообщения в канал
        # нельзя прочитать текст напрямую,
        # поэтому берём его из базы/сообщения
        # в следующем обработчике.

        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=author,
            parse_mode=ParseMode.HTML
        )


# ==========================================
# ПРИНЯТИЕ
# ==========================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа!",
            show_alert=True
        )

        return

    proposal_id = int(
        callback.data.split(":")[1]
    )

    proposal = get_proposal(proposal_id)

    if not proposal:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    if proposal["status"] != "pending":

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    try:

        # Получаем исходное сообщение
        # для корректной публикации

        original = await bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=proposal["chat_id"],
            message_id=proposal["message_id"]
        )

        author = make_author(
            proposal["user_id"],
            proposal["author_name"]
        )

        # Добавляем автора к медиа

        await bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=original.message_id,
            caption=author,
            parse_mode=ParseMode.HTML
        )

        db.execute(
            """
            UPDATE suggestions
            SET status = 'accepted'
            WHERE id = ?
            """,
            (proposal_id,)
        )

        db.commit()

        await callback.message.edit_reply_markup(
            reply_markup=None
        )

        await callback.answer(
            "Пост опубликован!"
        )

        await bot.send_message(
            proposal["user_id"],
            "✅ Твой пост опубликован!"
        )

    except TelegramAPIError as error:

        logging.exception(error)

        await callback.answer(
            "Ошибка публикации.",
            show_alert=True
        )


# ==========================================
# ОТКЛОНЕНИЕ
# ==========================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_post(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа!",
            show_alert=True
        )

        return

    proposal_id = int(
        callback.data.split(":")[1]
    )

    proposal = get_proposal(proposal_id)

    if not proposal:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    await state.set_state(
        AdminStates.waiting_reason
    )

    await state.update_data(
        proposal_id=proposal_id
    )

    await callback.message.answer(
        "❌ Напиши причину отклонения."
    )

    await callback.answer()


# ==========================================
# ПРИЧИНА ОТКАЗА
# ==========================================

@dp.message(AdminStates.waiting_reason)
async def rejection_reason(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()

    proposal_id = data["proposal_id"]

    proposal = get_proposal(proposal_id)

    if not proposal:

        await message.answer(
            "Заявка не найдена."
        )

        await state.clear()

        return

    reason = message.text or message.caption

    if not reason:

        await message.answer(
            "Напиши причину текстом."
        )

        return

    await bot.send_message(
        proposal["user_id"],
        "❌ Твой пост отклонён.\n\n"
        f"Причина: {html.escape(reason)}"
    )

    db.execute(
        """
        UPDATE suggestions
        SET status = 'rejected'
        WHERE id = ?
        """,
        (proposal_id,)
    )

    db.commit()

    await message.answer(
        "✅ Причина отправлена автору."
    )

    await state.clear()


# ==========================================
# ЗАПУСК
# ==========================================

async def main():

    logging.info("Бот предложки запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
