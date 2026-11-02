import asyncio
import base64
import json
import logging
import os
import html
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

import aiohttp
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
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError


# ==================================================
# НАСТРОЙКИ
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 7837011810
CHANNEL_ID = "@zapillspost"
RENDER_URL = "https://iris-store-bot-eqkf.onrender.com/"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
GITHUB_USERS_FILE = os.getenv("GITHUB_USERS_FILE", "data/users.json").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Добавь токен в Environment Render.")


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
# АВТОПИНГ (БЕСКОНЕЧНЫЕ ПОПЫТКИ ПРОБУЖДЕНИЯ)
# ==================================================

async def self_ping_loop():
    """Каждые 5 минут пингует сайт. Если он спит — стучится бесконечно, пока не разбудит."""
    while True:
        await asyncio.sleep(300)  # Интервал 5 минут
        success = False
        attempt = 1
        
        async with aiohttp.ClientSession() as session:
            while not success:
                try:
                    async with session.get(RENDER_URL, timeout=10) as resp:
                        if resp.status == 200:
                            logging.info(f"🔄 Автопинг успешен! Сайт бодрствует (попытка {attempt}).")
                            success = True
                        else:
                            logging.warning(f"⚠️ Автопинг: сервер вернул код {resp.status}, пробуем снова...")
                            attempt += 1
                            await asyncio.sleep(5)  # Пауза 5 секунд перед повторной попыткой
                except Exception as e:
                    logging.warning(f"💤 Сайт спит или недоступен (попытка {attempt}): {e}. Пробуем еще раз...")
                    attempt += 1
                    await asyncio.sleep(5)  # Повторяем попытку сразу (через 5 секунд) бесконечно


# ==================================================
# БОТ И ДИСПЕТЧЕР
# ==================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

users_file_lock = asyncio.Lock()


# ==================================================
# БАЗА ДАННЫХ
# ==================================================

def init_db():
    conn = sqlite3.connect("suggestions.db", check_same_thread=False)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        author_name TEXT NOT NULL,
        username TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        post_text TEXT DEFAULT '',
        post_caption TEXT DEFAULT '',
        post_type TEXT DEFAULT 'text',
        file_id TEXT DEFAULT '',
        is_anon INTEGER DEFAULT 0
    )
    """)
    
    columns = [row[1] for row in conn.execute("PRAGMA table_info(suggestions)").fetchall()]
    if "is_anon" not in columns:
        conn.execute("ALTER TABLE suggestions ADD COLUMN is_anon INTEGER DEFAULT 0")
    if "username" not in columns:
        conn.execute("ALTER TABLE suggestions ADD COLUMN username TEXT DEFAULT ''")
    
    conn.commit()
    return conn

db = init_db()


# ==================================================
# РАБОТА С ПОЛЬЗОВАТЕЛЯМИ И GITHUB
# ==================================================

def ensure_users_file():
    dir_name = os.path.dirname(GITHUB_USERS_FILE)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    if not os.path.exists(GITHUB_USERS_FILE):
        with open(GITHUB_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)


async def load_users() -> dict:
    async with users_file_lock:
        ensure_users_file()
        try:
            with open(GITHUB_USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logging.warning(f"Файл users.json поврежден ({e}), восстанавливаем...")
            data = {}

        cleaned_users = {}
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    user_id_int = int(k)
                    if isinstance(v, dict):
                        cleaned_users[str(user_id_int)] = {
                            "user_id": user_id_int,
                            "username": str(v.get("username", "")),
                            "full_name": str(v.get("full_name", "")),
                            "status": str(v.get("status", "active"))
                        }
                except ValueError:
                    continue
            return cleaned_users

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "user_id" in item:
                    try:
                        uid = int(item["user_id"])
                        cleaned_users[str(uid)] = {
                            "user_id": uid,
                            "username": str(item.get("username", "")),
                            "full_name": str(item.get("full_name", "")),
                            "status": str(item.get("status", "active"))
                        }
                    except ValueError:
                        continue
            return cleaned_users

        return {}


async def save_users(users_data: dict):
    async with users_file_lock:
        ensure_users_file()
        with open(GITHUB_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=4)
    asyncio.create_task(sync_users_to_github())


async def register_user(user):
    if not user:
        return
    users = await load_users()
    uid_str = str(user.id)
    users[uid_str] = {
        "user_id": user.id,
        "username": user.username or "",
        "full_name": user.full_name or "",
        "status": "active"
    }
    await save_users(users)


async def sync_users_to_github():
    if not GITHUB_TOKEN or not GITHUB_OWNER or not GITHUB_REPO:
        return

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_USERS_FILE}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    async with users_file_lock:
        ensure_users_file()
        if not os.path.exists(GITHUB_USERS_FILE):
            return
        with open(GITHUB_USERS_FILE, "rb") as f:
            content_bytes = f.read()

    encoded_content = base64.b64encode(content_bytes).decode("utf-8")

    async with aiohttp.ClientSession() as session:
        try:
            sha = None
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    sha = res_json.get("sha")

            payload = {
                "message": "Auto-sync users.json",
                "content": encoded_content,
                "branch": GITHUB_BRANCH
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    logging.info("users.json успешно синхронизирован с GitHub.")
                else:
                    err_text = await resp.text()
                    logging.error(f"Ошибка синхронизации с GitHub: {resp.status} - {err_text}")
        except Exception as e:
            logging.exception(f"Исключение при синхронизации с GitHub: {e}")


async def github_sync_background_loop():
    while True:
        await asyncio.sleep(300)
        await sync_users_to_github()


# ==================================================
# СОСТОЯНИЯ (FSM)
# ==================================================

class SuggestionStates(StatesGroup):
    waiting_post = State()
    waiting_anon_choice = State()


class SupportStates(StatesGroup):
    waiting_message = State()


class AdminStates(StatesGroup):
    waiting_reason = State()
    waiting_support_reply = State()
    waiting_edit_text = State()
    waiting_broadcast_message = State()


# ==================================================
# КЛАВИАТУРЫ
# ==================================================

def main_keyboard(is_admin: bool = False):
    keyboard = [
        [
            KeyboardButton(text="📩 Предложить пост"),
            KeyboardButton(text="💬 Поддержка")
        ]
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="📢 Рассылка")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
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
                InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{request_id}"),
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_prep:{request_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{request_id}")
            ]
        ]
    )


def support_admin_keyboard(user_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💬 Ответить", callback_data=f"support_reply:{user_id}"),
                InlineKeyboardButton(text="✅ Прочитано", callback_data="support_read")
            ]
        ]
    )


def broadcast_confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить рассылку", callback_data="broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
            ]
        ]
    )


# ==================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==================================================

def author_link(user_id, name, username=None):
    safe_name = html.escape(name)
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def get_request(request_id):
    row = db.execute(
        """
        SELECT id, user_id, author_name, username, status, post_text, post_caption, post_type, file_id, is_anon
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
        "username": row[3] or "",
        "status": row[4],
        "post_text": row[5] or "",
        "post_caption": row[6] or "",
        "post_type": row[7] or "text",
        "file_id": row[8] or "",
        "is_anon": row[9] or 0
    }


# ==================================================
# СТАРТ И РЕГИСТРАЦИЯ
# ==================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await register_user(message.from_user)
    is_admin = (message.from_user.id == ADMIN_ID)
    await message.answer(
        "👋 Привет!\n\n"
        "Хочешь, чтобы другие люди узнали, как проходит твоя жизнь?\n\n"
        "Здесь можно поделиться историей, фотографией, видео или просто написать сообщение.\n\n"
        "📩 Нажми «Предложить пост» или обратись в «Поддержку».",
        reply_markup=main_keyboard(is_admin)
    )


# ==================================================
# РАССЫЛКА ДЛЯ АДМИНА
# ==================================================

@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_broadcast_message)
    await message.answer(
        "📢 Отправьте сообщение для рассылки всем пользователям.\n"
        "Это может быть текст, фото, видео или любой другой контент.",
        reply_markup=cancel_keyboard()
    )


@dp.message(AdminStates.waiting_broadcast_message)
async def broadcast_preview(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=main_keyboard(True))
        return

    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    await message.answer("👇 Вы хотите запустить рассылку этого сообщения всем пользователям?", reply_markup=broadcast_confirm_keyboard())


@dp.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.message.answer("Главное меню:", reply_markup=main_keyboard(True))
    await callback.answer()


@dp.callback_query(F.data == "broadcast_confirm")
async def broadcast_execute(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    data = await state.get_data()
    msg_id = data.get("broadcast_message_id")
    from_chat_id = data.get("broadcast_chat_id")

    await callback.message.edit_text("🚀 Рассылка запущена... Пожалуйста, подождите.")
    await state.clear()

    users = await load_users()
    delivered = 0
    failed = 0

    for uid_str, user_info in users.items():
        if user_info.get("status") == "blocked":
            continue
        target_id = user_info["user_id"]
        try:
            await bot.copy_message(chat_id=target_id, from_chat_id=from_chat_id, message_id=msg_id)
            delivered += 1
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            user_info["status"] = "blocked"
            failed += 1
        except TelegramAPIError:
            failed += 1
        except Exception:
            failed += 1

    await save_users(users)

    await bot.send_message(
        ADMIN_ID,
        f"📊 <b>Рассылка завершена!</b>\n\n"
        f"✅ Доставлено: <b>{delivered}</b>\n"
        f"❌ Ошибок / заблокировали: <b>{failed}</b>",
        reply_markup=main_keyboard(True)
    )
    await callback.answer()


# ==================================================
# ПРЕДЛОЖКА ПОСТОВ
# ==================================================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_post(message: Message, state: FSMContext):
    await register_user(message.from_user)
    await state.set_state(SuggestionStates.waiting_post)
    await message.answer(
        "📩 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить:\n📝 Текст\n📸 Фото с подписью или без\n🎥 Видео с подписью или без\n\n"
        "Если передумал, нажми «❌ Отмена».",
        reply_markup=cancel_keyboard()
    )


# ==================================================
# ПОДДЕРЖКА
# ==================================================

@dp.message(F.text == "💬 Поддержка")
async def support_start(message: Message, state: FSMContext):
    await register_user(message.from_user)
    await state.set_state(SupportStates.waiting_message)
    await message.answer(
        "💬 Напиши свое сообщение для поддержки.\n\n"
        "Можешь отправить текст, фото или видео.\n\n"
        "Если передумал, нажми «❌ Отмена».",
        reply_markup=cancel_keyboard()
    )


@dp.message(SupportStates.waiting_message)
async def receive_support_message(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        is_admin = (message.from_user.id == ADMIN_ID)
        await message.answer("❌ Запрос в поддержку отменён.", reply_markup=main_keyboard(is_admin))
        return

    user = message.from_user
    username = f"@{user.username}" if user.username else "Нет юзернейма"
    author_name = html.escape(user.full_name or "Пользователь")
    user_info = f"👤 Пользователь: {author_name}\n🔗 Юзернейм: {username}\n🆔 ID: <code>{user.id}</code>"

    is_admin = (user.id == ADMIN_ID)
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
        else:
            await message.answer("❌ Поддерживаются только текст, фото или видео.")
            return

        await message.answer(
            "✅ Ваше сообщение отправлено в поддержку!\nОжидайте ответа администратора.",
            reply_markup=main_keyboard(is_admin)
        )
        await state.clear()

    except TelegramAPIError as error:
        logging.exception("Ошибка при отправке в поддержку: %s", error)
        await message.answer("❌ Не удалось отправить сообщение. Попробуйте позже.")


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

    await callback.message.answer(f"✍️ Напиши текст ответа для пользователя (ID: <code>{target_user_id}</code>):")
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
# ОБЩАЯ ОТМЕНА
# ==================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_suggestion(message: Message, state: FSMContext):
    await state.clear()
    is_admin = (message.from_user.id == ADMIN_ID)
    await message.answer("❌ Действие отменено.", reply_markup=main_keyboard(is_admin))


# ==================================================
# ОБРАБОТКА ПОСТА И АНОНИМНОСТИ
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
        await message.answer("❌ Пожалуйста, отправь текст, фото или видео.")
        return

    user = message.from_user
    author_name = user.full_name or user.username or "Автор"
    username = user.username or ""

    await state.update_data(
        user_id=user.id,
        post_type=post_type,
        post_text=post_text,
        post_caption=post_caption,
        file_id=file_id,
        author_name=author_name,
        username=username
    )

    await state.set_state(SuggestionStates.waiting_anon_choice)
    await message.answer("🕶 Как подписать твой пост?", reply_markup=anon_keyboard())


@dp.callback_query(SuggestionStates.waiting_anon_choice, F.data.startswith("anon:"))
async def process_anon_choice(callback: CallbackQuery, state: FSMContext):
    is_anon = int(callback.data.split(":")[1])
    data = await state.get_data()

    user_id = data["user_id"]
    author_name = data.get("author_name") or "Автор"
    username = data.get("username") or ""

    cursor = db.execute(
        """
        INSERT INTO suggestions (user_id, author_name, username, status, post_text, post_caption, post_type, file_id, is_anon)
        VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (user_id, author_name, username, data["post_text"], data["post_caption"], data["post_type"], data["file_id"], is_anon)
    )

    request_id = cursor.lastrowid
    db.commit()

    anon_status_text = "🕶 Анонимно" if is_anon else "👤 С автором"
    p_caption = data.get("post_caption", "")
    caption_line = f"\n\nПодпись: {p_caption}" if p_caption else ""

    try:
        if data["post_type"] == "text":
            await bot.send_message(
                ADMIN_ID,
                f"📩 Новая заявка №{request_id} ({anon_status_text})\n\n"
                f"📝 Текст:\n{data['post_text']}\n\n"
                f"👤 Автор: {html.escape(author_name)} (<code>{user_id}</code>)",
                reply_markup=admin_keyboard(request_id)
            )
        elif data["post_type"] == "photo":
            await bot.send_photo(
                ADMIN_ID,
                photo=data["file_id"],
                caption=f"📩 Новая заявка №{request_id} ({anon_status_text})\n"
                        f"👤 Автор: {html.escape(author_name)} (<code>{user_id}</code>){caption_line}",
                reply_markup=admin_keyboard(request_id)
            )
        elif data["post_type"] == "video":
            await bot.send_video(
                ADMIN_ID,
                video=data["file_id"],
                caption=f"📩 Новая заявка №{request_id} ({anon_status_text})\n"
                        f"👤 Автор: {html.escape(author_name)} (<code>{user_id}</code>){caption_line}",
                reply_markup=admin_keyboard(request_id)
            )

        await callback.message.edit_text("✅ Твой пост отправлен администратору!\n\nОжидай решения.")
        await callback.message.answer("Главное меню:", reply_markup=main_keyboard(False))
        await state.clear()

    except TelegramAPIError as error:
        logging.exception("Ошибка отправки заявки: %s", error)
        await callback.message.answer("❌ Не удалось отправить заявку. Попробуй ещё раз.")


# ==================================================
# ПУБЛИКАЦИЯ В КАНАЛ
# ==================================================

async def publish_post(request):
    user_id = request["user_id"]
    author_name = request["author_name"]
    username = request["username"]
    post_type = request["post_type"]
    post_text = request["post_text"]
    post_caption = request["post_caption"]
    file_id = request["file_id"]
    is_anon = request["is_anon"]

    author = author_link(user_id, author_name, username) if not is_anon else None

    if post_type == "text":
        text = html.escape(post_text)
        final_text = f"{text}\n\n👤: {author}" if author else text
        await bot.send_message(chat_id=CHANNEL_ID, text=final_text, parse_mode=ParseMode.HTML)

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

        await bot.send_photo(chat_id=CHANNEL_ID, photo=file_id, caption=final_caption, parse_mode=ParseMode.HTML)

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

        await bot.send_video(chat_id=CHANNEL_ID, video=file_id, caption=final_caption, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    request = get_request(request_id)

    if not request:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("⚠️ Заявка не найдена в базе (возможно, сервер перезапускался).", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    try:
        await publish_post(request)
        db.execute("UPDATE suggestions SET status = 'accepted' WHERE id = ?", (request_id,))
        db.commit()

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Пост опубликован!")

        await bot.send_message(
            request["user_id"],
            "✅ Твой пост опубликован в канале!\n\nСпасибо за предложку.",
            reply_markup=main_keyboard(False)
        )
    except TelegramAPIError as error:
        logging.exception("Ошибка публикации: %s", error)
        await callback.answer("❌ Ошибка публикации. Проверь права бота в канале.", show_alert=True)


# ==================================================
# РЕДАКТИРОВАНИЕ ПОСТА АДМИНОМ
# ==================================================

@dp.callback_query(F.data.startswith("edit_prep:"))
async def edit_post_prep(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    request = get_request(request_id)

    if not request:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("⚠️ Заявка не найдена в базе (возможно, сервер перезапускался).", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_edit_text)
    await state.update_data(request_id=request_id)

    await callback.message.answer(
        f"✏️ Редактирование заявки №{request_id}\n\nОтправь новый текст (или подпись) следующим сообщением:"
    )
    await callback.answer("Ожидаю новый текст.")


@dp.message(AdminStates.waiting_edit_text)
async def save_edited_post(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    new_text = message.text or message.caption
    if not new_text:
        await message.answer("❌ Отправь текст для замены обычным сообщением.")
        return

    data = await state.get_data()
    request_id = data["request_id"]
    request = get_request(request_id)

    if not request or request["status"] != "pending":
        await message.answer("Заявка уже обработана.")
        await state.clear()
        return

    if request["post_type"] == "text":
        db.execute("UPDATE suggestions SET post_text = ? WHERE id = ?", (new_text, request_id))
    else:
        db.execute("UPDATE suggestions SET post_caption = ? WHERE id = ?", (new_text, request_id))
    db.commit()

    updated_request = get_request(request_id)

    try:
        await publish_post(updated_request)
        db.execute("UPDATE suggestions SET status = 'accepted' WHERE id = ?", (request_id,))
        db.commit()

        await message.answer(f"✅ Заявка №{request_id} успешно отредактирована и опубликована!", reply_markup=ReplyKeyboardRemove())
        await bot.send_message(
            updated_request["user_id"],
            "✅ Твой пост (после редактирования администратором) опубликован в канале!\n\nСпасибо за предложку.",
            reply_markup=main_keyboard(False)
        )
    except TelegramAPIError as error:
        logging.exception("Ошибка публикации отредактированного поста: %s", error)
        await message.answer("❌ Ошибка публикации. Проверь права бота в канале.")

    await state.clear()


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
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("⚠️ Заявка не найдена в базе (возможно, сервер перезапускался).", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_reason)
    await state.update_data(request_id=request_id)

    await callback.message.answer(
        f"❌ Отклонение заявки №{request_id}\n\nНапиши причину отклонения. Она будет отправлена автору."
    )
    await callback.answer("Ожидаю причину.")


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
            f"❌ Твой пост отклонён.\n\nПричина: {html.escape(reason)}",
            reply_markup=main_keyboard(False)
        )

        db.execute("UPDATE suggestions SET status = 'rejected' WHERE id = ?", (request_id,))
        db.commit()

        await message.answer("✅ Причина отправлена автору.", reply_markup=ReplyKeyboardRemove())
    except TelegramAPIError as error:
        logging.exception("Ошибка отправки причины: %s", error)
        await message.answer("❌ Не удалось отправить причину.")

    await state.clear()


# ==================================================
# ЗАПУСК БОТА
# ==================================================

async def main():
    ensure_users_file()
    asyncio.create_task(github_sync_background_loop())
    asyncio.create_task(self_ping_loop())  # Запускаем бесконечный автопинг

    logging.info("Бот успешно запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
