
import asyncio
import logging
import os
import sqlite3
import urllib.request

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
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
    raise RuntimeError("Добавь BOT_TOKEN в переменные окружения Render")


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
    status TEXT DEFAULT 'pending',
    reason TEXT
)
""")

db.commit()


# ==================================================
# СОСТОЯНИЯ
# ==================================================

# Пользователи, которые сейчас отправляют предложку
waiting_post = set()

# Администратор, который пишет причину отказа
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
# СТАРТ
# ==================================================

@dp.message(CommandStart())
async def start(message: Message):

    waiting_post.discard(message.from_user.id)

    await message.answer(
        "👋 Добро пожаловать в предложку!\n\n"
        "Здесь ты можешь предложить свой пост "
        "для публикации в нашем канале.\n\n"
        "📸 Можно отправить фото.\n"
        "🎥 Можно отправить видео.\n"
        "📝 Можно отправить текст.\n\n"
        "После проверки администратор решит, "
        "публиковать его или нет.\n\n"
        "👇 Нажми кнопку ниже.",
        reply_markup=main_keyboard
    )


# ==================================================
# НАЧАТЬ ПРЕДЛОЖКУ
# ==================================================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_button(message: Message):

    user_id = message.from_user.id

    waiting_post.add(user_id)

    await message.answer(
        "📨 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить:\n"
        "📝 Текст\n"
        "📸 Фото с подписью\n"
        "🎥 Видео с подписью\n\n"
        "После отправки заявка попадёт администратору.\n\n"
        "Если передумал — нажми «❌ Отмена».",
        reply_markup=cancel_keyboard
    )


# ==================================================
# ОТМЕНА
# ==================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_post(message: Message):

    user_id = message.from_user.id

    if user_id in waiting_post:

        waiting_post.discard(user_id)

        await message.answer(
            "❌ Отправка предложки отменена.\n\n"
            "Если захочешь предложить пост, "
            "нажми кнопку ниже.",
            reply_markup=main_keyboard
        )

    else:

        await message.answer(
            "Ты сейчас не отправляешь предложку.",
            reply_markup=main_keyboard
        )


# ==================================================
# ПРИЁМ ПОСТА
# ==================================================

@dp.message()
async def receive_post(message: Message):

    user_id = message.from_user.id

    # ----------------------------------------------
    # АДМИНИСТРАТОР ПИШЕТ ПРИЧИНУ ОТКАЗА
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

        if not request:

            await message.answer(
                "⚠️ Заявка не найдена."
            )

            return

        if request["status"] != "pending":

            await message.answer(
                "⚠️ Эта заявка уже обработана."
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
                f"📝 Причина: {reason}"
            )

        except Exception as error:

            logger.error(
                "Не удалось отправить отказ пользователю: %s",
                error
            )

        await message.answer(
            f"❌ Заявка #{request_id} отклонена.\n\n"
            "Причина отправлена пользователю."
        )

        return

    # ----------------------------------------------
    # ПРОВЕРЯЕМ, ОТПРАВЛЯЕТ ЛИ ПОЛЬЗОВАТЕЛЬ ПОСТ
    # ----------------------------------------------

    if user_id not in waiting_post:
        return

    # ----------------------------------------------
    # ПРОВЕРЯЕМ ТИП ПОСТА
    # ----------------------------------------------

    if not (
        message.text
        or message.photo
        or message.video
    ):

        await message.answer(
            "⚠️ Можно отправить только текст, фото или видео.\n\n"
            "Попробуй ещё раз или нажми «❌ Отмена»."
        )

        return

    # ----------------------------------------------
    # СОЗДАЁМ ЗАЯВКУ
    # ----------------------------------------------

    cursor = db.execute(
        """
        INSERT INTO suggestions (user_id, message_id)
        VALUES (?, ?)
        """,
        (user_id, message.message_id)
    )

    request_id = cursor.lastrowid

    db.commit()

    # Сразу завершаем режим отправки
    waiting_post.discard(user_id)

    # ----------------------------------------------
    # ОТПРАВЛЯЕМ АДМИНУ
    # ----------------------------------------------

    try:

        copied_message = await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=admin_keyboard(request_id)
        )

        await bot.send_message(
            ADMIN_ID,
            f"📩 НОВАЯ ПРЕДЛОЖКА #{request_id}\n\n"
            f"👤 Пользователь: {user_id}",
            reply_to_message_id=copied_message.message_id
        )

    except Exception as error:

        logger.error(
            "Ошибка отправки заявки админу: %s",
            error
        )

        db.execute(
            """
            UPDATE suggestions
            SET status = 'error'
            WHERE id = ?
            """,
            (request_id,)
        )

        db.commit()

        await message.answer(
            "⚠️ Не удалось отправить заявку.\n\n"
            "Попробуй ещё раз позже.",
            reply_markup=main_keyboard
        )

        return

    # ----------------------------------------------
    # ПОДТВЕРЖДЕНИЕ ПОЛЬЗОВАТЕЛЮ
    # ----------------------------------------------

    await message.answer(
        "✅ Твоя предложка успешно отправлена!\n\n"
        "Ожидай решения администратора.",
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

    # ----------------------------------------------
    # ПУБЛИКУЕМ ПОСТ
    # ----------------------------------------------

    try:

        await bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=request["user_id"],
            message_id=request["message_id"]
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

        # Убираем кнопки администратора
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
            request["user_id"],
            "✅ Твоя предложка принята!\n\n"
            "Пост автоматически опубликован "
            "в нашем канале."
        )

        await bot.send_message(
            ADMIN_ID,
            f"✅ Заявка #{request_id} опубликована."
        )

    except Exception as error:

        logger.error(
            "Ошибка публикации поста: %s",
            error
        )

        await callback.answer(
            "⚠️ Ошибка публикации. "
            "Проверь права бота в канале.",
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
# АВТОПИНГ САЙТА
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

            # Успешный запрос — ждём 5 минут
            await asyncio.sleep(300)

        except Exception as error:

            logger.error(
                "Ошибка пинга сайта: %s",
                error
            )

            # Ошибка — повторяем через 30 секунд
            await asyncio.sleep(30)


# ==================================================
# ЗАПУСК
# ==================================================

async def main():

    logger.info("Бот запущен!")

    # Запускаем автоматический пинг
    asyncio.create_task(
        keep_site_alive()
    )

    # Запускаем Telegram-бота
    await dp.start_polling(bot)


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info("Бот остановлен.")

    finally:

        db.close()
