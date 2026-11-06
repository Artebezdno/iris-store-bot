import asyncio
import base64
import json
import logging
import os
import html
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
GITHUB_SUGGESTIONS_FILE = os.getenv("GITHUB_SUGGESTIONS_FILE", "data/suggestions.json").strip()

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
# АВТОПИНГ
# ==================================================

async def self_ping_loop():
    while True:
        await asyncio.sleep(300)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(RENDER_URL, timeout=10) as resp:
                    if resp.status == 200:
                        logging.info("🔄 Автопинг успешен!")
            except Exception as e:
                logging.warning(f"💤 Ошибка автопинга: {e}")


# ==================================================
# БОТ И ДИСПЕТЧЕР
# ==================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

users_file_lock = asyncio.Lock()
suggestions_file_lock = asyncio.Lock()


# ==================================================
# РАБОТА С SUGGESTIONS (JSON + GITHUB)
# ==================================================

def ensure_file(filepath):
    dir_name = os.path.dirname(filepath)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    if not os.path.exists(filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)


async def download_file_from_github(filepath):
    if not GITHUB_TOKEN or not GITHUB_OWNER or not GITHUB_REPO:
        return
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    content_encoded = res_json.get("content", "")
                    content_bytes = base64.b64decode(content_encoded)
                    ensure_file(filepath)
                    with open(filepath, "wb") as f:
                        f.write(content_bytes)
                    logging.info(f"{filepath} успешно скачан с GitHub при старте.")
        except Exception as e:
            logging.warning(f"Не удалось скачать {filepath} с GitHub: {e}")


async def load_suggestions() -> dict:
    async with suggestions_file_lock:
        ensure_file(GITHUB_SUGGESTIONS_FILE)
        try:
            with open(GITHUB_SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}


async def save_suggestions(suggestions_data: dict):
    async with suggestions_file_lock:
        ensure_file(GITHUB_SUGGESTIONS_FILE)
        with open(GITHUB_SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(suggestions_data, f, ensure_ascii=False, indent=4)
    asyncio.create_task(sync_file_to_github(GITHUB_SUGGESTIONS_FILE, "Auto-sync suggestions.json"))


def get_request(request_id):
    try:
        with open(GITHUB_SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(str(request_id))
    except Exception:
        return None


# ==================================================
# РАБОТА С ПОЛЬЗОВАТЕЛЯМИ И GITHUB
# ==================================================

async def load_users() -> dict:
    async with users_file_lock:
        ensure_file(GITHUB_USERS_FILE)
        try:
            with open(GITHUB_USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}


async def save_users(users_data: dict):
    async with users_file_lock:
        ensure_file(GITHUB_USERS_FILE)
        with open(GITHUB_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=4)
    asyncio.create_task(sync_file_to_github(GITHUB_USERS_FILE, "Auto-sync users.json"))


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


async def sync_file_to_github(filepath, commit_message):
    if not GITHUB_TOKEN or not GITHUB_OWNER or not GITHUB_REPO:
        return

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    if not os.path.exists(filepath):
        return
    with open(filepath, "rb") as f:
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
                "message": commit_message,
                "content": encoded_content,
                "branch": GITHUB_BRANCH
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    logging.info(f"{filepath} успешно синхронизирован с GitHub.")
        except Exception as e:
            logging.exception(f"Исключение при синхронизации {filepath} с GitHub: {e}")


async def github_sync_background_loop():
    while True:
        await asyncio.sleep(300)
        await sync_file_to_github(GITHUB_USERS_FILE, "Periodic sync users.json")
        await sync_file_to_github(GITHUB_SUGGESTIONS_FILE, "Periodic sync suggestions.json")


# ==================================================
# СОСТОЯНИЯ (FSM) И КЛАВИАТУРЫ
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


def main_keyboard(is_admin: bool = False):
    keyboard = [[KeyboardButton(text="📩 Предложить пост"), KeyboardButton(text="💬 Поддержка")]]
    if is_admin:
        keyboard.append([KeyboardButton(text="📢 Рассылка")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

def anon_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 С автором", callback_data="anon:0"),
        InlineKeyboardButton(text="🕶 Анонимно", callback_data="anon:1")
    ]])

def admin_keyboard(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{request_id}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_prep:{request_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{request_id}")]
    ])

def support_admin_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💬 Ответить", callback_data=f"support_reply:{user_id}"),
        InlineKeyboardButton(text="✅ Прочитано", callback_data="support_read")
    ]])

def broadcast_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить рассылку", callback_data="broadcast_confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
    ]])

def author_link(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


# ==================================================
# ХЕНДЛЕРЫ СТАРТА И ПОДДЕРЖКИ
# ==================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await register_user(message.from_user)
    is_admin = (message.from_user.id == ADMIN_ID)
    await message.answer("👋 Привет!\n\n📩 Нажми «Предложить пост» или обратись в «Поддержку».", reply_markup=main_keyboard(is_admin))

@dp.message(F.text == "❌ Отмена")
async def cancel_suggestion(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=main_keyboard(message.from_user.id == ADMIN_ID))


# ==================================================
# РАССЫЛКА ДЛЯ АДМИНА
# ==================================================

@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_broadcast_message)
    await message.answer("📢 Отправьте сообщение для рассылки всем пользователям:", reply_markup=cancel_keyboard())

@dp.message(AdminStates.waiting_broadcast_message)
async def broadcast_preview(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=main_keyboard(True))
        return
    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    await message.answer("👇 Запустить рассылку этого сообщения?", reply_markup=broadcast_confirm_keyboard())

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
    await callback.message.edit_text("🚀 Рассылка запущена...")
    await state.clear()

    users = await load_users()
    delivered, failed = 0, 0
    for uid_str, user_info in users.items():
        if user_info.get("status") == "blocked":
            continue
        try:
            await bot.copy_message(chat_id=user_info["user_id"], from_chat_id=from_chat_id, message_id=msg_id)
            delivered += 1
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            user_info["status"] = "blocked"
            failed += 1
        except Exception:
            failed += 1
    await save_users(users)
    await bot.send_message(ADMIN_ID, f"📊 Рассылка завершена!\n✅ Доставлено: {delivered}\n❌ Ошибок: {failed}", reply_markup=main_keyboard(True))
    await callback.answer()


# ==================================================
# ПРЕДЛОЖКА ПОСТОВ
# ==================================================

@dp.message(F.text == "📩 Предложить пост")
async def suggest_post(message: Message, state: FSMContext):
    await register_user(message.from_user)
    await state.set_state(SuggestionStates.waiting_post)
    await message.answer("📩 Отправь свой пост следующим сообщением (текст, фото, видео или стикер):", reply_markup=cancel_keyboard())

@dp.message(SuggestionStates.waiting_post)
async def receive_post(message: Message, state: FSMContext):
    if message.text and not message.text.startswith("/"):
        post_type, post_text, file_id, post_caption = "text", message.text, "", ""
    elif message.photo:
        post_type, post_text, file_id, post_caption = "photo", "", message.photo[-1].file_id, message.caption or ""
    elif message.video:
        post_type, post_text, file_id, post_caption = "video", "", message.video.file_id, message.caption or ""
    elif message.sticker:
        post_type, post_text, file_id, post_caption = "sticker", "", message.sticker.file_id, ""
    else:
        await message.answer("❌ Отправь текст, фото, видео или стикер.")
        return

    user = message.from_user
    await state.update_data(
        user_id=user.id, post_type=post_type, post_text=post_text,
        post_caption=post_caption, file_id=file_id,
        author_name=user.full_name or "Автор", username=user.username or ""
    )
    await state.set_state(SuggestionStates.waiting_anon_choice)
    await message.answer("🕶 Как подписать твой пост?", reply_markup=anon_keyboard())

@dp.callback_query(SuggestionStates.waiting_anon_choice, F.data.startswith("anon:"))
async def process_anon_choice(callback: CallbackQuery, state: FSMContext):
    is_anon = int(callback.data.split(":")[1])
    data = await state.get_data()

    request_id = str(int(asyncio.get_event_loop().time() * 1000))
    suggestions = await load_suggestions()
    suggestions[request_id] = {
        "id": request_id,
        "user_id": data["user_id"],
        "author_name": data["author_name"],
        "username": data["username"],
        "status": "pending",
        "post_text": data["post_text"],
        "post_caption": data["post_caption"],
        "post_type": data["post_type"],
        "file_id": data["file_id"],
        "is_anon": is_anon
    }
    await save_suggestions(suggestions)

    anon_status = "🕶 Анонимно" if is_anon else "👤 С автором"
    try:
        if data["post_type"] == "text":
            await bot.send_message(ADMIN_ID, f"📩 Новая заявка №{request_id} ({anon_status})\n\n📝 Текст:\n{data['post_text']}", reply_markup=admin_keyboard(request_id))
        elif data["post_type"] == "photo":
            await bot.send_photo(ADMIN_ID, photo=data["file_id"], caption=f"📩 Новая заявка №{request_id} ({anon_status})", reply_markup=admin_keyboard(request_id))
        elif data["post_type"] == "video":
            await bot.send_video(ADMIN_ID, video=data["file_id"], caption=f"📩 Новая заявка №{request_id} ({anon_status})", reply_markup=admin_keyboard(request_id))
        elif data["post_type"] == "sticker":
            await bot.send_sticker(ADMIN_ID, sticker=data["file_id"])
            await bot.send_message(ADMIN_ID, f"📩 Новая заявка №{request_id} (Стикер | {anon_status})", reply_markup=admin_keyboard(request_id))

        await callback.message.edit_text("✅ Твой пост отправлен администратору!")
        await callback.message.answer("Главное меню:", reply_markup=main_keyboard(False))
        await state.clear()
    except Exception as e:
        logging.error(f"Ошибка отправки админу: {e}")
        await callback.message.answer("❌ Ошибка отправки.")


# ==================================================
# ПУБЛИКАЦИЯ И УДАЛЕНИЕ (КЛАССИЧЕСКИЙ МЕТОД С ПОДПИСЬЮ)
# ==================================================

async def publish_post(request):
    author = author_link(request["user_id"], request["author_name"]) if not request["is_anon"] else None
    ptype = request["post_type"]

    for attempt in range(3):
        try:
            sent_message = None
            if ptype == "text":
                txt = html.escape(request["post_text"])
                sent_message = await bot.send_message(CHANNEL_ID, f"{txt}\n\n👤: {author}" if author else txt)
            elif ptype == "photo":
                cap = html.escape(request["post_caption"])
                final_cap = f"{cap}\n\n👤: {author}" if cap and author else (cap or (f"👤: {author}" if author else None))
                sent_message = await bot.send_photo(CHANNEL_ID, photo=request["file_id"], caption=final_cap)
            elif ptype == "video":
                cap = html.escape(request["post_caption"])
                final_cap = f"{cap}\n\n👤: {author}" if cap and author else (cap or (f"👤: {author}" if author else None))
                sent_message = await bot.send_video(CHANNEL_ID, video=request["file_id"], caption=final_cap)
            elif ptype == "sticker":
                sent_message = await bot.send_sticker(CHANNEL_ID, sticker=request["file_id"])
                if author:
                    await bot.send_message(CHANNEL_ID, f"👤: {author}")
            return sent_message
        except TelegramAPIError as e:
            if attempt == 2:
                raise e
            await asyncio.sleep(2)
    return None

@dp.callback_query(F.data.startswith("accept:"))
async def accept_post(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    request_id = callback.data.split(":")[1]
    suggestions = await load_suggestions()
    request = suggestions.get(request_id)

    if not request:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("⚠️ Заявка уже обработана или удалена.", show_alert=True)
        return

    try:
        sent_message = await publish_post(request)
        
        channel_username = CHANNEL_ID.replace("@", "")
        post_link = f"https://t.me/{channel_username}/{sent_message.message_id}"

        del suggestions[request_id]
        await save_suggestions(suggestions)

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Пост опубликован!")
        
        await bot.send_message(
            request["user_id"], 
            f"🔥 Твою историю опубликовали!\nПосмотреть можно здесь: {post_link}"
        )
    except Exception as e:
        logging.error(f"Ошибка публикации: {e}")
        await callback.answer("❌ Ошибка публикации.", show_alert=True)


# ==================================================
# РЕДАКТИРОВАНИЕ ПОСТА АДМИНОМ
# ==================================================

@dp.callback_query(F.data.startswith("edit_prep:"))
async def edit_post_prep(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    request_id = callback.data.split(":")[1]
    request = get_request(request_id)

    if not request:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("⚠️ Заявка не найдена.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_edit_text)
    await state.update_data(request_id=request_id)

    await callback.message.answer(f"✏️ Редактирование заявки №{request_id}\n\nОтправь новый текст (или подпись):")
    await callback.answer("Ожидаю текст.")

@dp.message(AdminStates.waiting_edit_text)
async def save_edited_post(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    new_text = message.text or message.caption
    if not new_text:
        await message.answer("❌ Отправь текст обычным сообщением.")
        return

    data = await state.get_data()
    request_id = data["request_id"]
    suggestions = await load_suggestions()
    request = suggestions.get(request_id)

    if not request:
        await message.answer("Заявка не найдена.")
        await state.clear()
        return

    if request["post_type"] == "text":
        request["post_text"] = new_text
    else:
        request["post_caption"] = new_text

    try:
        sent_message = await publish_post(request)
        
        channel_username = CHANNEL_ID.replace("@", "")
        post_link = f"https://t.me/{channel_username}/{sent_message.message_id}"

        del suggestions[request_id]
        await save_suggestions(suggestions)

        await message.answer(f"✅ Заявка №{request_id} отредактирована и опубликована!", reply_markup=ReplyKeyboardRemove())
        
        await bot.send_message(
            request["user_id"], 
            f"🔥 Твою историю (после правок) опубликовали!\nПосмотреть можно здесь: {post_link}"
        )
    except Exception as e:
        logging.error(f"Ошибка публикации отредактированного поста: {e}")
        await message.answer("❌ Ошибка публикации.")

    await state.clear()


# ==================================================
# ОТКЛОНЕНИЕ ЗАЯВКИ
# ==================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_post(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    request_id = callback.data.split(":")[1]
    request = get_request(request_id)
    if not request:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("⚠️ Заявка уже обработана или удалена.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_reason)
    await state.update_data(request_id=request_id)
    await callback.message.answer(f"❌ Напиши причину отклонения:")
    await callback.answer()

@dp.message(AdminStates.waiting_reason)
async def reject_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    request_id = data["request_id"]
    suggestions = await load_suggestions()
    request = suggestions.get(request_id)

    if request:
        try:
            await bot.send_message(request["user_id"], f"❌ Твой пост отклонён.\nПричина: {html.escape(message.text)}")
            del suggestions[request_id]
            await save_suggestions(suggestions)
            await message.answer("✅ Заявка отклонена и удалена.", reply_markup=ReplyKeyboardRemove())
        except Exception:
            await message.answer("❌ Ошибка отправки.")
    await state.clear()


# ==================================================
# ПОДДЕРЖКА
# ==================================================

@dp.message(F.text == "💬 Поддержка")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportStates.waiting_message)
    await message.answer("💬 Напиши сообщение для поддержки:", reply_markup=cancel_keyboard())

@dp.message(SupportStates.waiting_message)
async def receive_support_message(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_keyboard(message.from_user.id == ADMIN_ID))
        return
    user = message.from_user
    await bot.send_message(ADMIN_ID, f"💬 Обращение от {user.full_name} (ID: {user.id}):\n\n{message.text}", reply_markup=support_admin_keyboard(user.id))
    await message.answer("✅ Отправлено в поддержку!", reply_markup=main_keyboard(user.id == ADMIN_ID))
    await state.clear()

@dp.callback_query(F.data == "support_read")
async def support_read_callback(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Прочитано.")

@dp.callback_query(F.data.startswith("support_reply:"))
async def support_reply_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_support_reply)
    await state.update_data(target_user_id=int(callback.data.split(":")[1]))
    await callback.message.answer("✍️ Напиши ответ пользователю:")
    await callback.answer()

@dp.message(AdminStates.waiting_support_reply)
async def send_support_reply(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    try:
        await bot.send_message(data["target_user_id"], f"🎧 Ответ поддержки:\n\n{message.text}")
        await message.answer("✅ Ответ отправлен!")
    except Exception:
        await message.answer("❌ Не удалось отправить.")
    await state.clear()


# ==================================================
# ЗАПУСК
# ==================================================

async def main():
    # Скачиваем актуальные файлы с GitHub при старте (защита от сброса на Render при сне)
    await download_file_from_github(GITHUB_USERS_FILE)
    await download_file_from_github(GITHUB_SUGGESTIONS_FILE)

    ensure_file(GITHUB_USERS_FILE)
    ensure_file(GITHUB_SUGGESTIONS_FILE)
    asyncio.create_task(github_sync_background_loop())
    asyncio.create_task(self_ping_loop())
    logging.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
