
import asyncio
import logging
import os
import sqlite3
import urllib.request
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest


# ==================================================
# НАСТРОЙКИ
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 7837011810
CHANNEL_ID = "@zapillspost"

SITE_URL = "https://iris-store-bot-eqkf.onrender.com/"

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN")


# ==================================================
# ЛОГИ
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ==================================================
# БОТ
# ==================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==================================================
# БАЗА ДАННЫХ
# ==================================================

db = sqlite3.connect("suggestions.db")
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    reason TEXT
)
""")

db.commit()


# ==================================================
# СОСТОЯНИЯ
# ==================================================

waiting_post = set()
waiting_reason = {}


# ==================================================
# КЛАВИАТУРЫ
# ==================================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📩 Предложить пост")]
    ],
    resize_keyboard=True
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❌ Отмена")]
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
# ССЫЛКА НА ПРОФИЛЬ АВТОРА
# ==================================================

def author_link(user_id, author_name):

    safe_name = escape(author_name)

    return (
        f'<a href="tg://user?id={user_id}">'
        f'{safe_name}</a>'
    )


# ==================================================
# СТАРТ
# ==================================================

@dp.message(CommandStart())
async def start(message: Message):

    waiting_post.discard(message.from_user.id)

    await message.answer(
        "👋 Добро пожаловать в предложку!\n\n"
        "Хочешь поделиться тем, что сейчас делаешь?\n\n"
        "📸 Отправляй фото\n"
        "🎥 Отправляй видео\n"
        "📝 Пиши текст\n\n"
        "Твой пост может попасть в наш канал!\n\n"
        "👇 Нажми кнопку ниже.",
        reply_markup=main_keyboard
    )


# ==================================================
# НАЧАТЬ ПРЕДЛОЖКУ
# ==================================================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_button(message: Message):

    waiting_post.add(message.from_user.id)

    await message.answer(
        "📨 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить текст, фото или видео "
        "с подписью.\n\n"
        "Если передумал — нажми «❌ Отмена».",
        reply_markup=cancel_keyboard
    )


# ==================================================
# ОТМЕНА
# ==================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_post(message: Message):

    waiting_post.discard(message.from_user.id)

    await message.answer(
        "❌ Отправка предложки отменена.",
        reply_markup=main_keyboard
    )


# ==================================================
# ПРИЁМ ПОСТА
# ==================================================

@dp.message()
async def receive_post(message: Message):

    user_id = message.from_user.id

    # ----------------------------------------------
    # ПРИЧИНА ОТКАЗА
    # ----------------------------------------------

    if user_id == ADMIN_ID and ADMIN_ID in waiting_reason:

        request_id = waiting_reason[ADMIN_ID]

        if not message.text:

            await message.answer(
                "✍️ Напиши причину отказа текстом."
            )

            return

        reason = message.text.strip()

        if not reason:

            await message.answer(
                "Причина не может быть пустой."
            )

            return

        request = db.execute(
            "SELECT * FROM suggestions WHERE id = ?",
            (request_id,)
        ).fetchone()

        waiting_reason.pop(ADMIN_ID, None)

        if not request or request["status"] != "pending":

            await message.answer(
                "⚠️ Заявка уже обработана."
            )

            return

        db.execute(
            """
            UPDATE suggestions
            SET status = 'rejected', reason = ?
            WHERE id = ?
            """,
            (reason, request_id)
        )

        db.commit()

        try:

            await bot.send_message(
                request["user_id"],
                "❌ Твоя предложка отклонена.\n\n"
                f"📝 Причина: {escape(reason)}",
                parse_mode="HTML"
            )

        except Exception as error:

            logger.error(
                "Ошибка отправки отказа: %s",
                error
            )

        await message.answer(
            f"❌ Заявка #{request_id} отклонена."
        )

        return

    # ----------------------------------------------
    # ПРОВЕРКА РЕЖИМА ПРЕДЛОЖКИ
    # ----------------------------------------------

    if user_id not in waiting_post:
        return

    # ----------------------------------------------
    # ПРОВЕРКА ТИПА СООБЩЕНИЯ
    # ----------------------------------------------

    if not (
        message.text
        or message.photo
        or message.video
    ):

        await message.answer(
            "⚠️ Отправь текст, фото или видео."
        )

        return

    # ----------------------------------------------
    # СОЗДАЁМ ЗАЯВКУ
    # ----------------------------------------------

    author_name = message.from_user.full_name

    cursor = db.execute(
        """
        INSERT INTO suggestions (
            user_id,
            message_id,
            chat_id,
            author_name
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            message.message_id,
            message.chat.id,
            author_name
        )
    )

    request_id = cursor.lastrowid

    db.commit()

    waiting_post.discard(user_id)

    # ----------------------------------------------
    # ОТПРАВЛЯЕМ АДМИНУ
    # ----------------------------------------------

    try:

        copied = await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=admin_keyboard(request_id)
        )

        await bot.send_message(
            ADMIN_ID,
            f"📩 НОВАЯ ПРЕДЛОЖКА #{request_id}\n\n"
            f"👤 Автор: {escape(author_name)}\n"
            f"🆔 ID: {user_id}",
            reply_to_message_id=copied.message_id,
            parse_mode="HTML"
        )

    except Exception as error:

        logger.error(
            "Ошибка отправки заявки: %s",
            error
        )

        db.execute(
            "UPDATE suggestions SET status = 'error' WHERE id = ?",
            (request_id,)
        )

        db.commit()

        await message.answer(
            "⚠️ Не удалось отправить заявку.",
            reply_markup=main_keyboard
        )

        return

    # ----------------------------------------------
    # ПОДТВЕРЖДЕНИЕ
    # ----------------------------------------------

    await message.answer(
        "✅ Твоя предложка отправлена администратору!\n\n"
        "Ожидай решения.",
        reply_markup=main_keyboard
    )


# ==================================================
# ПРИНЯТЬ ПОСТ
# ==================================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    request_id = int(callback.data.split(":")[1])

    request = db.execute(
        "SELECT * FROM suggestions WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not request or request["status"] != "pending":

        await callback.answer(
            "⚠️ Заявка уже обработана.",
            show_alert=True
        )

        return

    user_id = request["user_id"]
    author_name = request["author_name"]

    # Ссылка на профиль автора
    author = author_link(
        user_id,
        author_name
    )

    # ----------------------------------------------
    # ПУБЛИКАЦИЯ
    # ----------------------------------------------

    try:

        original = await bot.forward_message(
            chat_id=CHANNEL_ID,
            from_chat_id=request["chat_id"],
            message_id=request["message_id"]
        )

        # Подпись для текста
        # Если исходное сообщение было текстом,
        # добавляем имя автора отдельным сообщением.

        if original.text:

            await bot.send_message(
                CHANNEL_ID,
                f"{escape(original.text)}\n\n"
                f"👤 {author}",
                parse_mode="HTML",
                reply_to_message_id=original.message_id
            )

        else:

            # Фото или видео — добавляем подпись
            # к самому медиа

            await bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=original.message_id,
                caption=f"👤 {author}",
                parse_mode="HTML"
            )

        db.execute(
            """
            UPDATE suggestions
            SET status = 'accepted'
            WHERE id = ?
            """,
            (request_id,)
        )

        db.commit()

        try:

            await callback.message.edit_reply_markup(
                reply_markup=None
            )

        except TelegramBadRequest:
            pass

        await callback.answer(
            "✅ Пост опубликован!"
        )

        await bot.send_message(
            user_id,
            "✅ Твоя предложка опубликована в канале!"
        )

        await bot.send_message(
            ADMIN_ID,
            f"✅ Заявка #{request_id} опубликована."
        )

    except Exception as error:

        logger.error(
            "Ошибка публикации: %s",
            error
        )

        await callback.answer(
            "⚠️ Ошибка публикации.",
            show_alert=True
        )


# ==================================================
# ОТКЛОНИТЬ ПОСТ
# ==================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_post(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    request_id = int(callback.data.split(":")[1])

    request = db.execute(
        "SELECT * FROM suggestions WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not request or request["status"] != "pending":

        await callback.answer(
            "⚠️ Заявка уже обработана.",
            show_alert=True
        )

        return

    waiting_reason[ADMIN_ID] = request_id

    try:

        await callback.message.edit_reply_markup(
            reply_markup=None
        )

    except TelegramBadRequest:
        pass

    await callback.answer()

    await bot.send_message(
        ADMIN_ID,
        f"✍️ Напиши причину отказа заявки #{request_id}.\n\n"
        "Причина будет отправлена пользователю."
    )


# ==================================================
# ПИНГ САЙТА
# ==================================================

def ping_site():

    request = urllib.request.Request(
        SITE_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        return response.status


async def keep_site_alive():

    while True:

        try:

            status = await asyncio.to_thread(
                ping_site
            )

            logger.info(
                "Сайт отвечает: %s",
                status
            )

            await asyncio.sleep(300)

        except Exception as error:

            logger.error(
                "Ошибка пинга: %s",
                error
            )

            await asyncio.sleep(30)


# ==================================================
# ЗАПУСК
# ==================================================

async def main():

    logger.info("Бот запущен!")

    asyncio.create_task(
        keep_site_alive()
    )

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
