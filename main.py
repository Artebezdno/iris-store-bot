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
# ВЕБ-СЕРВЕР ДЛЯ RENDER
# ==================================================

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    logging.info(f"Веб-сервер запущен на порту {port}")
    server.serve_forever()

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
    file_id TEXT DEFAULT '',
    is_anon INTEGER DEFAULT 0
)
""")

columns = [row[1] for row in db.execute("PRAGMA table_info(suggestions)").fetchall()]
if "is_anon" not in columns:
    db.execute("ALTER TABLE suggestions ADD COLUMN is_anon INTEGER DEFAULT 0")

db.commit()


# ==================================================
# СОСТОЯНИЯ
# ==================================================

class SuggestionStates(StatesGroup):
    waiting_post = State()
    waiting_anon_choice = State()


class SupportStates(StatesGroup):
    waiting_message = State()


class AdminStates(StatesGroup):
    waiting_reason = State()
    waiting_support_reply = State()


# ==================================================
# КЛАВИАТУРЫ
# ==================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📩 Предложить пост"),
                KeyboardButton(text="💬 Поддержка")
            ]
        ],
        resize_keyboard=True
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="❌ Отмена")
            ]
        ],
        resize_keyboard=True
    )


def anon_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 С автором", callback_data="anon:0"),
                InlineKeyboardButton(text="🕶 Анонимно", callback_data="anon:1")
            ]
        ]
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


def support_admin_keyboard(user_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"support_reply:{user_id}"
                ),
                InlineKeyboardButton(
                    text="✅ Прочитано",
                    callback_data="support_read"
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
            file_id,
            is_anon
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
        "file_id": row[7] or "",
        "is_anon": row[8] or 0
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
        "фотографией, видео, кружочком или просто написать сообщение.\n\n"
        "📩 Нажми «Предложить пост» или обратись в «Поддержку».",
        reply_markup=main_keyboard()
    )


# ==================================================
# НАЧАЛО ПРЕДЛОЖКИ
# ==================================================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_post(message: Message, state: FSMContext):
    await state.set_state(SuggestionStates.waiting_post)
    await message.answer(
        "📩 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить:\n"
        "📝 Текст\n"
        "📸 Фото с подписью или без\n"
        "🎥 Видео с подписью или без\n"
        "⭕️ Кружочек (видеосообщение)\n\n"
        "Если передумал, нажми «❌ Отмена».",
        reply_markup=cancel_keyboard()
    )


# ==================================================
# ПОДДЕРЖКА — ПОЛЬЗОВАТЕЛЬ
# ==================================================

@dp.message(F.text == "💬 Поддержка")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportStates.waiting_message)
    await message.answer(
        "💬 Напиши свое сообщение для поддержки.\n\n"
        "Можешь отправить текст, фото, видео или кружочек с объяснением твоего вопроса.\n\n"
        "Если передумал, нажми «❌ Отмена».",
        reply_markup=cancel_keyboard()
    )


@dp.message(SupportStates.waiting_message)
async def receive_support_message(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Запрос в поддержку отменён.", reply_markup=main_keyboard())
        return

    user = message.from_user
    username = f"@{user.username}" if user.username else "Нет юзернейма"
    author_name = html.escape(user.full_name or "Пользователь")
    user_info = f"👤 Пользователь: {author_name}\n🔗 Юзернейм: {username}\n🆔 ID: <code>{user.id}</code>"

    try:
        if message.text:
            await bot.send_message(
                ADMIN_ID,
                f"💬 <b>Новое обращение в поддержку!</b>\n\n{user_info}\n\n📝 <b>Сообщение:</b>\n{html.escape(message.text)}",
                reply_markup=support_admin_keyboard(user.id)
            )
        elif message.photo:
            file_id = message.photo[-1].file_id
            caption = message.caption or ""
            await bot.send_photo(
                ADMIN_ID,
                photo=file_id,
                caption=f"💬 <b>Новое обращение в поддержку!</b>\n\n{user_info}\n\n📝 <b>Подпись:</b>\n{html.escape(caption)}",
                reply_markup=support_admin_keyboard(user.id)
            )
        elif message.video:
            file_id = message.video.file_id
            caption = message.caption or ""
            await bot.send_video(
                ADMIN_ID,
                video=file_id,
                caption=f"💬 <b>Новое обращение в поддержку!</b>\n\n{user_info}\n\n📝 <b>Подпись:</b>\n{html.escape(caption)}",
                reply_markup=support_admin_keyboard(user.id)
            )
        elif message.video_note:
            file_id = message.video_note.file_id
            await bot.send_video_note(ADMIN_ID, video_note=file_id)
            await bot.send_message(
                ADMIN_ID,
                f"💬 <b>Новое обращение в поддержку (кружочек)!</b>\n\n{user_info}",
                reply_markup=support_admin_keyboard(user.id)
            )
        else:
            await message.answer("❌ Поддерживаются текст, фото, видео или кружочки.")
            return

        await message.answer(
            "✅ Ваше сообщение отправлено в поддержку!\nОжидайте ответа администратора.",
            reply_markup=main_keyboard()
        )
        await state.clear()

    except TelegramAPIError as error:
        logging.exception("Ошибка при отправке в поддержку: %s", error)
        await message.answer("❌ Не удалось отправить сообщение. Попробуйте позже.")


# ==================================================
# ПОДДЕРЖКА — АДМИН
# ==================================================

@dp.callback_query(F.data == "support_read")
async def support_read_callback(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Отмечено как прочитанное.")


@dp.callback_query(F.data.startswith("support_reply:"))
async def support_reply_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    target_user_id = int(callback.data.split(":")[1])
    await state.set_state(AdminStates.waiting_support_reply)
    await state.update_data(target_user_id=target_user_id)

    await callback.message.answer(
        f"✍️ Напиши текст ответа для пользователя (ID: <code>{target_user_id}</code>):"
    )
    await callback.answer()


@dp.message(AdminStates.waiting_support_reply)
async def send_support_reply(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    reply_text = message.text or message.caption
    if not reply_text:
        await message.answer("❌ Отправь ответ текстом.")
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")

    try:
        await bot.send_message(
            target_user_id,
            f"🎧 <b>Ответ службы поддержки:</b>\n\n{html.escape(reply_text)}"
        )
        await message.answer("✅ Ответ успешно отправлен пользователю!")
    except TelegramAPIError as error:
        logging.exception("Ошибка отправки ответа поддержки: %s", error)
        await message.answer("❌ Не удалось доставить ответ пользователю.")

    await state.clear()


# ==================================================
# ОТМЕНА ОБЩАЯ
# ==================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_suggestion(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_keyboard()
    )


# ==================================================
# ПОЛУЧЕНИЕ ПОСТА И ВЫБОР АНОНИМНОСТИ
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
    elif message.video_note:
        post_type = "video_note"
        file_id = message.video_note.file_id
    else:
        await message.answer(
            "❌ Пожалуйста, отправь текст, фото, видео или кружочек."
        )
        return

    await state.update_data(
        post_type=post_type,
        post_text=post_text,
        post_caption=post_caption,
        file_id=file_id
    )

    await state.set_state(SuggestionStates.waiting_anon_choice)
    await message.answer(
        "🕶 Как подписать твой пост?",
        reply_markup=anon_keyboard()
    )


@dp.callback_query(SuggestionStates.waiting_anon_choice, F.data.startswith("anon:"))
async def process_anon_choice(callback: CallbackQuery, state: FSMContext):
    is_anon = int(callback.data.split(":")[1])
    data = await state.get_data()

    user = callback.from_user
    author_name = user.full_name or user.username or "Автор"

    cursor = db.execute(
        """
        INSERT INTO suggestions (
            user_id,
            author_name,
            status,
            post_text,
            post_caption,
            post_type,
            file_id,
            is_anon
        )
        VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (
            user.id,
            author_name,
            data["post_text"],
            data["post_caption"],
            data["post_type"],
            data["file_id"],
            is_anon
        )
    )

    request_id = cursor.lastrowid
    db.commit()

    anon_status_text = "🕶 Анонимно" if is_anon else "👤 С автором"

    try:
        if data["post_type"] == "text":
            await bot.send_message(
                ADMIN_ID,
                f"📩 Новая заявка №{request_id} ({anon_status_text})\n\n"
                f"📝 Текст:\n{data['post_text']}\n\n"
                f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)",
                reply_markup=admin_keyboard(request_id)
            )
        elif data["post_type"] == "photo":
            await bot.send_photo(
                ADMIN_ID,
                photo=data["file_id"],
                caption=f"📩 Новая заявка №{request_id} ({anon_status_text})\n"
                        f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)"
                        f"{f'\n\nПодпись: {data[\"post_caption\"]}' if data[\"post_caption\"] else ''}",
                reply_markup=admin_keyboard(request_id)
            )
        elif data["post_type"] == "video":
            await bot.send_video(
                ADMIN_ID,
                video=data["file_id"],
                caption=f"📩 Новая заявка №{request_id} ({anon_status_text})\n"
                        f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)"
                        f"{f'\n\nПодпись: {data[\"post_caption\"]}' if data[\"post_caption\"] else ''}",
                reply_markup=admin_keyboard(request_id)
            )
        elif data["post_type"] == "video_note":
            await bot.send_video_note(ADMIN_ID, video_note=data["file_id"])
            await bot.send_message(
                ADMIN_ID,
                f"📩 Новая заявка (кружочек) №{request_id} ({anon_status_text})\n"
                f"👤 Автор: {html.escape(author_name)} (<code>{user.id}</code>)",
                reply_markup=admin_keyboard(request_id)
            )

        await callback.message.edit_text(
            "✅ Твой пост отправлен администратору!\n\nОжидай решения."
        )
        await callback.message.answer(
            "Главное меню:",
            reply_markup=main_keyboard()
        )
        await state.clear()

    except TelegramAPIError as error:
        logging.exception("Ошибка отправки заявки: %s", error)
        await callback.message.answer("❌ Не удалось отправить заявку. Попробуй ещё раз.")


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
    is_anon = request["is_anon"]

    author = author_link(user_id, author_name) if not is_anon else None

    if post_type == "text":
        text = html.escape(post_text)
        final_text = f"{text}\n\n👤: {author}" if author else text
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=final_text,
            parse_mode=ParseMode.HTML
        )

    elif post_type == "photo":
        caption = html.escape(post_caption)
        if caption and author:
            final_caption = f"{caption}\n\n👤: {author}"
        elif caption and not author:
            final_caption = caption
        elif not caption and author:
            final_caption = f"👤: {author}"
        else:
            final_caption = None

        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=file_id,
            caption=final_caption,
            parse_mode=ParseMode.HTML
        )

    elif post_type == "video":
        caption = html.escape(post_caption)
        if caption and author:
            final_caption = f"{caption}\n\n👤: {author}"
        elif caption and not author:
            final_caption = caption
        elif not caption and author:
            final_caption = f"👤: {author}"
        else:
            final_caption = None

        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=file_id,
            caption=final_caption,
            parse_mode=ParseMode.HTML
        )

    elif post_type == "video_note":
        await bot.send_video_note(
            chat_id=CHANNEL_ID,
            video_note=file_id
        )
        if author:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"👤: {author}",
                parse_mode=ParseMode.HTML
            )


# ==================================================
# ПРИНЯТИЕ ЗАЯВКИ
# ==================================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    request = get_request(request_id)

    if not request:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
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

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Пост опубликован!")

        await bot.send_message(
            request["user_id"],
            "✅ Твой пост опубликован в канале!\n\nСпасибо за предложку.",
            reply_markup=main_keyboard()
        )

    except TelegramAPIError as error:
        logging.exception("Ошибка публикации: %s", error)
        await callback.answer("❌ Ошибка публикации. Проверь права бота в канале.", show_alert=True)


# ==================================================
# ОТКЛОНЕНИЕ ЗАЯВКИ
# ==================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_post(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    request = get_request(request_id)

    if not request:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
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
        logging.exception("Ошибка отправки причины: %s", error)
        await message.answer("❌ Не удалось отправить причину.")

    await state.clear()


# ==================================================
# ЗАПУСК
# ==================================================

async def main():
    logging.info("Бот предложки успешно запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
