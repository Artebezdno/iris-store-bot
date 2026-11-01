
import asyncio
import logging
import os
import html
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.exceptions import TelegramAPIError


# ==================================================
# НАСТРОЙКИ
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = 7837011810

CHANNEL_ID = "@zapillspost"

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. Добавь токен в Environment Render."
    )


# ==================================================
# ЗАПУСК БОТА
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# ==================================================
# БАЗА ДАННЫХ
# ==================================================

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


# ==================================================
# СОСТОЯНИЯ
# ==================================================

class SuggestionStates(StatesGroup):
    waiting_post = State()
    waiting_reason = State()


# ==================================================
# КЛАВИАТУРЫ
# ==================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📩 Предложить пост"
                )
            ]
        ],
        resize_keyboard=True
    )


def cancel_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="❌ Отмена"
                )
            ]
        ],
        resize_keyboard=True
    )


def admin_keyboard(request_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{request_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{request_id}"
                )
            ]
        ]
    )


# ==================================================
# ССЫЛКА НА АВТОРА
# ==================================================

def author_link(user_id, name):

    safe_name = html.escape(name)

    return (
        f'<a href="tg://user?id={user_id}">'
        f'{safe_name}</a>'
    )


# ==================================================
# ПОЛУЧЕНИЕ ЗАЯВКИ
# ==================================================

def get_request(request_id):

    row = db.execute(
        """
        SELECT
            id,
            user_id,
            chat_id,
            message_id,
            author_name,
            status
        FROM suggestions
        WHERE id = ?
        """,
        (request_id,)
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


# ==================================================
# ПРИВЕТСТВИЕ
# ==================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "👋 Привет!\n\n"
        "Хочешь, чтобы другие люди узнали, "
        "как проходит твоя жизнь?\n\n"
        "Здесь можно поделиться историей, "
        "фотографией, видео или просто написать, "
        "что ты сейчас делаешь.\n\n"
        "📩 Нажми кнопку ниже, чтобы предложить пост.",
        reply_markup=main_keyboard()
    )


# ==================================================
# НАЧАЛО ПРЕДЛОЖКИ
# ==================================================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_post(message: Message, state: FSMContext):

    await state.set_state(
        SuggestionStates.waiting_post
    )

    await message.answer(
        "📩 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить:\n"
        "📝 Текст\n"
        "📸 Фото с подписью\n"
        "🎥 Видео с подписью\n\n"
        "После отправки заявка попадёт администратору.\n\n"
        "Если передумал, нажми «❌ Отмена».",
        reply_markup=cancel_keyboard()
    )


# ==================================================
# ОТМЕНА ПРЕДЛОЖКИ
# ==================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_suggestion(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "❌ Предложка отменена.",
        reply_markup=main_keyboard()
    )


# ==================================================
# ПОЛУЧЕНИЕ ПОСТА ОТ ПОЛЬЗОВАТЕЛЯ
# ==================================================

@dp.message(SuggestionStates.waiting_post)
async def receive_post(
    message: Message,
    state: FSMContext
):

    # Разрешаем только текст, фото и видео

    if not (
        message.text
        or message.photo
        or message.video
    ):

        await message.answer(
            "❌ Отправь текст, фото или видео."
        )

        return

    if message.text and message.text.startswith("/"):

        await message.answer(
            "Отправь обычный текст, фото или видео."
        )

        return

    user = message.from_user

    author_name = (
        user.full_name
        or user.username
        or "Автор"
    )

    # Сохраняем заявку

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

    request_id = cursor.lastrowid

    db.commit()

    try:

        # КОПИРУЕМ пост администратору
        # Никакого forward_message здесь нет!

        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=admin_keyboard(request_id)
        )

        # Информация о заявке

        await bot.send_message(
            ADMIN_ID,
            f"📩 Новая заявка №{request_id}\n\n"
            f"👤 Автор: {html.escape(author_name)}\n"
            f"🆔 ID: <code>{user.id}</code>"
        )

        await message.answer(
            "✅ Твой пост отправлен администратору!\n\n"
            "Ожидай решения.",
            reply_markup=main_keyboard()
        )

        await state.clear()

    except TelegramAPIError as error:

        logging.exception(
            "Ошибка отправки заявки: %s",
            error
        )

        await message.answer(
            "❌ Не удалось отправить заявку.\n"
            "Попробуй ещё раз."
        )


# ==================================================
# ПУБЛИКАЦИЯ ПОСТА В КАНАЛ
# ==================================================

async def publish_post(request):

    user_id = request["user_id"]

    chat_id = request["chat_id"]

    message_id = request["message_id"]

    author_name = request["author_name"]

    author = author_link(
        user_id,
        author_name
    )

    # Получаем оригинальное сообщение

    original = await bot.copy_message(
        chat_id=CHANNEL_ID,
        from_chat_id=chat_id,
        message_id=message_id
    )

    # ==============================================
    # ТЕКСТОВЫЙ ПОСТ
    # ==============================================

    if original.text:

        text = original.text

        # Оставляем место для подписи автора

        if len(text) > 3900:
            text = text[:3900] + "..."

        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                f"{html.escape(text)}\n\n"
                f"👤: {author}"
            ),
            parse_mode=ParseMode.HTML
        )

        # Удаляем временную копию

        await bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=original.message_id
        )

    # ==============================================
    # ФОТО ИЛИ ВИДЕО
    # ==============================================

    else:

        caption = original.caption or ""

        # Оставляем место для автора

        if len(caption) > 900:
            caption = caption[:900] + "..."

        new_caption = (
            f"{html.escape(caption)}\n\n"
            f"👤: {author}"
        )

        # Редактируем подпись скопированного медиа

        await bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=original.message_id,
            caption=new_caption,
            parse_mode=ParseMode.HTML
        )


# ==================================================
# ПРИНЯТИЕ ЗАЯВКИ
# ==================================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа!",
            show_alert=True
        )

        return

    request_id = int(
        callback.data.split(":")[1]
    )

    request = get_request(request_id)

    if not request:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    if request["status"] != "pending":

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    try:

        # Публикуем пост

        await publish_post(request)

        # Обновляем статус

        db.execute(
            """
            UPDATE suggestions
            SET status = 'accepted'
            WHERE id = ?
            """,
            (request_id,)
        )

        db.commit()

        # Убираем кнопки

        await callback.message.edit_reply_markup(
            reply_markup=None
        )

        await callback.answer(
            "✅ Пост опубликован!"
        )

        # Сообщаем автору

        await bot.send_message(
            request["user_id"],
            "✅ Твой пост опубликован в канале!\n\n"
            "Спасибо за предложку.",
            reply_markup=main_keyboard()
        )

    except TelegramAPIError as error:

        logging.exception(
            "Ошибка публикации: %s",
            error
        )

        await callback.answer(
            "❌ Ошибка публикации. "
            "Проверь права бота в канале.",
            show_alert=True
        )


# ==================================================
# ОТКЛОНЕНИЕ ЗАЯВКИ
# ==================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_post(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа!",
            show_alert=True
        )

        return

    request_id = int(
        callback.data.split(":")[1]
    )

    request = get_request(request_id)

    if not request:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    if request["status"] != "pending":

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    # Запоминаем заявку для администратора

    await state.set_state(
        SuggestionStates.waiting_reason
    )

    await state.update_data(
        request_id=request_id,
        user_id=request["user_id"]
    )

    await callback.message.answer(
        f"❌ Отклонение заявки №{request_id}\n\n"
        "Напиши причину отклонения.\n"
        "Она будет отправлена автору."
    )

    await callback.answer(
        "Ожидаю причину."
    )


# ==================================================
# ОТПРАВКА ПРИЧИНЫ ОТКАЗА
# ==================================================

@dp.message(SuggestionStates.waiting_reason)
async def reject_reason(
    message: Message,
    state: FSMContext
):

    reason = message.text or message.caption

    if not reason:

        await message.answer(
            "❌ Напиши причину обычным текстом."
        )

        return

    data = await state.get_data()

    request_id = data["request_id"]

    user_id = data["user_id"]

    request = get_request(request_id)

    if not request or request["status"] != "pending":

        await message.answer(
            "Заявка уже обработана."
        )

        await state.clear()

        return

    try:

        # Отправляем причину автору

        await bot.send_message(
            user_id,
            "❌ Твой пост отклонён.\n\n"
            f"Причина: {html.escape(reason)}",
            reply_markup=main_keyboard()
        )

        # Обновляем статус

        db.execute(
            """
            UPDATE suggestions
            SET status = 'rejected'
            WHERE id = ?
            """,
            (request_id,)
        )

        db.commit()

        await message.answer(
            "✅ Причина отправлена автору.",
            reply_markup=ReplyKeyboardRemove()
        )

    except TelegramAPIError as error:

        logging.exception(
            "Ошибка отправки причины: %s",
            error
        )

        await message.answer(
            "❌ Не удалось отправить причину."
        )

    await state.clear()


# ==================================================
# ЗАПУСК
# ==================================================

async def main():

    logging.info("Бот предложки запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
