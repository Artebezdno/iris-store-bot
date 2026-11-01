import asyncio
import logging
import os
import html
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

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
# ЛОГИ
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ==================================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER (ЧТОБЫ БОТ НЕ ЗАСЫПАЛ)
# ==================================================

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        # Отключаем лишние логи запросов сервера в консоли
        pass

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    logging.info(f"Веб-сервер запущен на порту {port}")
    server.serve_forever()

# Запускаем веб-сервер в отдельном потоке, чтобы он держал Render бодрым
Thread(target=run_web_server, daemon=True).start()


# ==================================================
# БОТ
# ==================================================

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

db = sqlite3.connect("suggestions.db", check_same_thread=False)

db.execute("""
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    post_text TEXT DEFAULT '',
    post_caption TEXT DEFAULT '',
    post_type TEXT DEFAULT 'text',
    file_id TEXT DEFAULT ''
)
""")

columns = [
    row[1]
    for row in db.execute(
        "PRAGMA table_info(suggestions)"
    ).fetchall()
]

if "post_text" not in columns:
    db.execute(
        "ALTER TABLE suggestions ADD COLUMN post_text TEXT DEFAULT ''"
    )

if "post_caption" not in columns:
    db.execute(
        "ALTER TABLE suggestions ADD COLUMN post_caption TEXT DEFAULT ''"
    )

if "post_type" not in columns:
    db.execute(
        "ALTER TABLE suggestions ADD COLUMN post_type TEXT DEFAULT 'text'"
    )

if "file_id" not in columns:
    db.execute(
        "ALTER TABLE suggestions ADD COLUMN file_id TEXT DEFAULT ''"
    )

db.commit()


# ==================================================
# СОСТОЯНИЯ
# ==================================================

class SuggestionStates(StatesGroup):
    waiting_post = State()


class AdminStates(StatesGroup):
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
            author_name,
            status,
            post_text,
            post_caption,
            post_type,
            file_id
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
        "author_name": row[2],
        "status": row[3],
        "post_text": row[4] or "",
        "post_caption": row[5] or "",
        "post_type": row[6] or "text",
        "file_id": row[7] or ""
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
        "📸 Фото с подписью или без неё\n"
        "🎥 Видео с подписью или без неё\n\n"
        "После отправки заявка попадёт администратору.\n\n"
        "Если передумал, нажми «❌ Отмена».",
        reply_markup=cancel_keyboard()
    )


# ==================================================
# ОТМЕНА
# ==================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_suggestion(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Предложка отменена.",
        reply_markup=main_keyboard()
    )


# ==================================================
# ПОЛУЧЕНИЕ ПОСТА
# ==================================================

@dp.message(SuggestionStates.waiting_post)
async def receive_post(message: Message, state: FSMContext):
    post_text = ""
    post_caption = ""
    file_id = ""

    if message.text and not message.text.startswith("/"):
        post_type = "text"
        post_text = message.text
    elif message.photo:
        post_type = "photo"
        file_id = message.photo[-1].file_id
        post_caption = message.caption or ""
    elif message.video:
        post_type = "video"
        file_id = message.video.file_id
        post_caption = message.caption or ""
    else:
        await message.answer(
            "❌ Пожалуйста, отправь текст, фото или видео."
        )
        return

    user = message.from_user
    author_name = (
        user.full_name
        or user.username
        or "Автор"
    )

    cursor = db.execute(
        """
        INSERT INTO suggestions (
            user_id,
            author_name,
            status,
            post_text,
            post_caption,
            post_type,
            file_id
        )
        VALUES (?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            user.id,
            author_name,
            post_text,
            post_caption,
            post_type,
            file_id
        )
    )

    request_id = cursor.lastrowid
    db.commit()

    try:
        if post_type == "text":
            await bot.send_message(
                ADMIN_ID,
                f"📩 Новая заявка №{request_id}\n\n"
                f"📝 Текст:\n{post_text}\n\n"
                f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)",
                reply_markup=admin_keyboard(request_id)
            )
        elif post_type == "photo":
            await bot.send_photo(
                ADMIN_ID,
                photo=file_id,
                caption=f"📩 Новая заявка №{request_id}\n"
                        f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)"
                        f"{f'\n\nПодпись: {post_caption}' if post_caption else ''}",
                reply_markup=admin_keyboard(request_id)
            )
        elif post_type == "video":
            await bot.send_video(
                ADMIN_ID,
                video=file_id,
                caption=f"📩 Новая заявка №{request_id}\n"
                        f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)"
                        f"{f'\n\nПодпись: {post_caption}' if post_caption else ''}",
                reply_markup=admin_keyboard(request_id)
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
    author_name = request["author_name"]
    post_type = request["post_type"]
    post_text = request["post_text"]
    post_caption = request["post_caption"]
    file_id = request["file_id"]

    author = author_link(user_id, author_name)

    if post_type == "text":
        text = html.escape(post_text)
        final_text = (
            f"{text}\n\n"
            f"👤: {author}"
        )
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=final_text,
            parse_mode=ParseMode.HTML
        )

    elif post_type == "photo":
        caption = html.escape(post_caption)
        if caption:
            final_caption = f"{caption}\n\n👤: {author}"
        else:
            final_caption = f"👤: {author}"

        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=file_id,
            caption=final_caption,
            parse_mode=ParseMode.HTML
        )

    elif post_type == "video":
        caption = html.escape(post_caption)
        if caption:
            final_caption = f"{caption}\n\n👤: {author}"
        else:
            final_caption = f"👤: {author}"

        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=file_id,
            caption=final_caption,
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

    request_id = int(callback.data.split(":")[1])
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
        await publish_post(request)

        db.execute(
            """
            UPDATE suggestions
            SET status = 'accepted'
            WHERE id = ?
            """,
            (request_id,)
        )
        db.commit()

        await callback.message.edit_reply_markup(
            reply_markup=None
        )
        await callback.answer(
            "✅ Пост опубликован!"
        )

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
async def reject_post(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ Нет доступа!",
            show_alert=True
        )
        return

    request_id = int(callback.data.split(":")[1])
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

    await state.set_state(AdminStates.waiting_reason)
    await state.update_data(request_id=request_id)

    await callback.message.answer(
        f"❌ Отклонение заявки №{request_id}\n\n"
        "Напиши причину отклонения.\n"
        "Она будет отправлена автору."
    )
    await callback.answer("Ожидаю причину.")


# ==================================================
# ПРИЧИНА ОТКАЗА
# ==================================================

@dp.message(AdminStates.waiting_reason)
async def reject_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    reason = message.text or message.caption
    if not reason:
        await message.answer("❌ Напиши причину обычным текстом.")
        return

    data = await state.get_data()
    request_id = data["request_id"]
    request = get_request(request_id)

    if not request or request["status"] != "pending":
        await message.answer("Заявка уже обработана.")
        await state.clear()
        return

    try:
        await bot.send_message(
            request["user_id"],
            "❌ Твой пост отклонён.\n\n"
            f"Причина: {html.escape(reason)}",
            reply_markup=main_keyboard()
        )

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
    logging.info("Бот предложки успешно запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
