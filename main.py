
import asyncio
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest


# ================= НАСТРОЙКИ =================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 7837011810

CHANNEL_ID = "@zapillspost"

if not BOT_TOKEN:
    raise RuntimeError("Не указан BOT_TOKEN в переменных окружения")


# ================= БАЗА ДАННЫХ =================

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


# ================= БОТ =================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Здесь хранится заявка, для которой администратор пишет причину отказа
waiting_reason = {}


# ================= КЛАВИАТУРЫ =================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📩 Предложить пост")]
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


# ================= СТАРТ =================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Здесь ты можешь предложить свой пост "
        "для публикации в нашем канале.\n\n"
        "Отправь текст, фото или видео.\n"
        "После проверки администратор решит, "
        "публиковать его или нет.\n\n"
        "👇 Нажми кнопку, чтобы предложить пост.",
        reply_markup=main_keyboard
    )


# ================= ПРЕДЛОЖИТЬ ПОСТ =================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_button(message: Message):
    await message.answer(
        "📨 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить текст, фото или видео "
        "с подписью.\n\n"
        "После отправки заявка попадёт администратору."
    )


# ================= ПРИЁМ ЗАЯВКИ =================

@dp.message()
async def receive_post(message: Message):

    # Администратор пишет причину отказа
    if message.from_user.id == ADMIN_ID:
        if ADMIN_ID in waiting_reason:

            if not message.text:
                await message.answer(
                    "Пожалуйста, отправь причину отказа текстом."
                )
                return

            request_id = waiting_reason.pop(ADMIN_ID)

            request = db.execute(
                "SELECT * FROM suggestions WHERE id = ?",
                (request_id,)
            ).fetchone()

            if not request:
                await message.answer("Заявка не найдена.")
                return

            reason = message.text.strip()

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
                    f"Причина: {reason}"
                )
            except Exception:
                pass

            await message.answer(
                f"❌ Заявка #{request_id} отклонена.\n"
                "Пользователь получил причину."
            )

        return

    # Принимаем только текст, фото и видео
    if not (
        message.text
        or message.photo
        or message.video
    ):
        await message.answer(
            "⚠️ Можно отправить только текст, фото или видео."
        )
        return

    # Создаём заявку
    cursor = db.execute(
        """
        INSERT INTO suggestions (user_id, message_id)
        VALUES (?, ?)
        """,
        (message.from_user.id, message.message_id)
    )

    request_id = cursor.lastrowid
    db.commit()

    # Отправляем заявку администратору
    try:
        admin_message = await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=admin_keyboard(request_id)
        )

        await bot.send_message(
            ADMIN_ID,
            f"📩 Новая предложка #{request_id}\n"
            f"От пользователя: {message.from_user.id}",
            reply_to_message_id=admin_message.message_id
        )

    except Exception as e:
        print("Ошибка отправки админу:", e)

        await message.answer(
            "⚠️ Не удалось отправить заявку администратору."
        )
        return

    await message.answer(
        "✅ Твоя предложка отправлена на проверку!\n\n"
        "Ожидай решения администратора."
    )


# ================= ПРИНЯТЬ ЗАЯВКУ =================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])

    request = db.execute(
        "SELECT * FROM suggestions WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not request or request["status"] != "pending":
        await callback.answer(
            "Эта заявка уже обработана.",
            show_alert=True
        )
        return

    try:
        await bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=request["user_id"],
            message_id=request["message_id"]
        )

        db.execute(
            "UPDATE suggestions SET status = 'accepted' WHERE id = ?",
            (request_id,)
        )
        db.commit()

        await bot.send_message(
            request["user_id"],
            "✅ Твоя предложка принята и опубликована в канале!"
        )

        await callback.message.edit_reply_markup(
            reply_markup=None
        )

        await callback.answer("Пост опубликован!")

        await bot.send_message(
            ADMIN_ID,
            f"✅ Заявка #{request_id} опубликована."
        )

    except Exception as e:
        print("Ошибка публикации:", e)

        await callback.answer(
            "Ошибка публикации. Проверь права бота в канале.",
            show_alert=True
        )


# ================= ОТКЛОНИТЬ ЗАЯВКУ =================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_post(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])

    request = db.execute(
        "SELECT * FROM suggestions WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not request or request["status"] != "pending":
        await callback.answer(
            "Эта заявка уже обработана.",
            show_alert=True
        )
        return

    waiting_reason[ADMIN_ID] = request_id

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.answer()

    await bot.send_message(
        ADMIN_ID,
        f"✍️ Напиши причину отклонения заявки #{request_id}.\n\n"
        "Причина будет отправлена пользователю."
    )


# ================= ЗАПУСК =================

async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
