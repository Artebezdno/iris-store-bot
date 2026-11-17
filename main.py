import asyncio
import base64
import json
import logging
import os
import html
import time
import re
import calendar
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

import aiohttp
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart, StateFilter
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
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # очень старый Python
    ZoneInfo = None


# ==================================================
# НАСТРОЙКИ
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 7837011810
CHANNEL_ID = "@zapillspost"
CHANNEL_URL = "https://t.me/zapillspost"
RENDER_URL = "https://iris-store-bot-eqkf.onrender.com/"

# Лимит между постами (в секундах). 300 = 5 минут
POST_COOLDOWN = 300

# Лимит между обращениями в поддержку (в секундах). 60 = 1 минута
SUPPORT_COOLDOWN = 60

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
    old = users.get(uid_str, {})
    users[uid_str] = {
        **old,  # сохраняем last_post_ts и прочие поля
        "user_id": user.id,
        "username": user.username or "",
        "full_name": user.full_name or "",
        "status": "active"
    }
    await save_users(users)


async def set_last_post_time(user_id: int):
    users = await load_users()
    uid_str = str(user_id)
    if uid_str in users:
        users[uid_str]["last_post_ts"] = time.time()
        await save_users(users)


async def get_cooldown_left(user_id: int) -> int:
    """Сколько секунд осталось до следующего поста (0 — можно слать)."""
    users = await load_users()
    last_ts = users.get(str(user_id), {}).get("last_post_ts", 0)
    left = int(last_ts + POST_COOLDOWN - time.time())
    return max(left, 0)


async def set_last_support_time(user_id: int):
    users = await load_users()
    uid_str = str(user_id)
    if uid_str in users:
        users[uid_str]["last_support_ts"] = time.time()
        await save_users(users)


async def get_support_cooldown_left(user_id: int) -> int:
    """Сколько секунд осталось до следующего обращения в поддержку (0 — можно писать)."""
    users = await load_users()
    last_ts = users.get(str(user_id), {}).get("last_support_ts", 0)
    left = int(last_ts + SUPPORT_COOLDOWN - time.time())
    return max(left, 0)


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
# ДНИ РОЖДЕНИЯ: ЛОГИКА И ПОЗДРАВЛЕНИЯ
# ==================================================

BIRTHDAY_HOUR = 9  # во сколько по местному времени поздравлять


def get_birthday_tz():
    if ZoneInfo is not None:
        for name in ("Europe/Kyiv", "Europe/Kiev"):
            try:
                return ZoneInfo(name)
            except Exception:
                pass
    return timezone(timedelta(hours=2))  # запасной вариант


BIRTHDAY_TZ = get_birthday_tz()


def parse_birthday(text: str):
    """Возвращает дату как ДД.ММ.ГГГГ или ДД.ММ, либо None, если не распознано."""
    m = re.fullmatch(r"\s*(\d{1,2})[.\-/ ](\d{1,2})(?:[.\-/ ](\d{4}))?\s*", text or "")
    if not m:
        return None

    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else None
    today = datetime.now(BIRTHDAY_TZ).date()

    try:
        if year is None:
            datetime(2000, month, day)  # 2000 високосный, поэтому 29.02 допустимо
            return f"{day:02d}.{month:02d}"
        born = datetime(year, month, day).date()
    except ValueError:
        return None

    if year < 1900 or born > today:
        return None
    return f"{day:02d}.{month:02d}.{year}"


def is_birthday_today(bday: str, today) -> bool:
    try:
        parts = bday.split(".")
        day, month = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return False
    # Родившимся 29 февраля в невисокосный год поздравляем 28-го
    if day == 29 and month == 2 and not calendar.isleap(today.year):
        day = 28
    return (today.day, today.month) == (day, month)


async def set_birthday(user_id: int, value):
    """Сохраняет дату рождения. Старая дата просто заменяется новой. value=None удаляет дату."""
    users = await load_users()
    uid_str = str(user_id)
    if uid_str not in users:
        return
    if value:
        users[uid_str]["birthday"] = value
    else:
        users[uid_str].pop("birthday", None)
    await save_users(users)


async def mark_congratulated(user_id: int, year: int, blocked: bool = False):
    users = await load_users()
    uid_str = str(user_id)
    if uid_str not in users:
        return
    if blocked:
        users[uid_str]["status"] = "blocked"
    else:
        users[uid_str]["last_congrats_year"] = year
    await save_users(users)


GREET_LIMIT = 3          # сколько поздравлений друзьям можно отправить...
GREET_WINDOW = 3600      # ...за этот период (секунд)
GREET_MAX_LEN = 500      # максимум символов в тексте поздравления
GREET_PENDING_MAX = 20   # максимум отложенных поздравлений на одного человека


def greet_wait_text(wait: int) -> str:
    minutes = max(1, (wait + 59) // 60)
    return f"⏳ Ты уже отправил {GREET_LIMIT} поздравления за последний час. Попробуй через {minutes} мин."


async def get_greet_wait(user_id: int) -> int:
    """Сколько секунд ждать до следующего поздравления другу (0 — можно слать)."""
    users = await load_users()
    stamps = users.get(str(user_id), {}).get("greet_ts", [])
    now = time.time()
    recent = sorted(t for t in stamps if now - t < GREET_WINDOW)
    if len(recent) < GREET_LIMIT:
        return 0
    return int(recent[-GREET_LIMIT] + GREET_WINDOW - now) + 1


async def record_greeting(user_id: int):
    users = await load_users()
    uid_str = str(user_id)
    if uid_str not in users:
        return
    now = time.time()
    stamps = [t for t in users[uid_str].get("greet_ts", []) if now - t < GREET_WINDOW]
    stamps.append(now)
    users[uid_str]["greet_ts"] = stamps
    await save_users(users)


async def find_user_by_username(username: str):
    users = await load_users()
    for uid_str, rec in users.items():
        if (rec.get("username") or "").lower() == username.lower():
            return uid_str, rec
    return None, None


async def send_greeting_now(sender, target_id: int, text: str):
    """Отправляет поздравление сразу. Подпись всегда с именем отправителя."""
    try:
        await bot.send_message(
            target_id,
            f"🎁 Тебе поздравление от {author_link(sender.id, sender.full_name or 'друга')}:\n\n"
            f"{html.escape(text)}"
        )
        return True, ""
    except TelegramForbiddenError:
        await mark_congratulated(target_id, 0, blocked=True)
        return False, "❌ Не получилось отправить: человек заблокировал бота."
    except Exception as e:
        logging.warning(f"Не удалось отправить поздравление {target_id}: {e}")
        return False, "❌ Не получилось отправить поздравление. Попробуй позже."


async def add_pending_greeting(target_id: int, sender, text: str) -> bool:
    """Откладывает поздравление до дня рождения. Хранится в users.json у получателя."""
    users = await load_users()
    uid_str = str(target_id)
    if uid_str not in users:
        return False
    pending = list(users[uid_str].get("pending_greetings", []))
    if len(pending) >= GREET_PENDING_MAX:
        return False
    pending.append({
        "id": int(time.time() * 1000),
        "from_id": sender.id,
        "from_name": sender.full_name or "Друг",
        "text": text
    })
    users[uid_str]["pending_greetings"] = pending
    await save_users(users)
    return True


async def remove_pending(user_id: int, ids):
    users = await load_users()
    uid_str = str(user_id)
    if uid_str not in users:
        return
    left = [g for g in users[uid_str].get("pending_greetings", []) if g.get("id") not in ids]
    if left:
        users[uid_str]["pending_greetings"] = left
    else:
        users[uid_str].pop("pending_greetings", None)
    await save_users(users)


def build_greeting_chunks(pending):
    """Собирает отложенные поздравления в одно сообщение (или несколько, если не влезают)."""
    if len(pending) == 1:
        g = pending[0]
        return [
            f"🎁 Тебе поздравление от {author_link(g['from_id'], g['from_name'])}:\n\n"
            f"{html.escape(g['text'])}"
        ]

    chunks, cur = [], "🎁 <b>Поздравления от друзей:</b>\n\n"
    for g in pending:
        entry = f"{author_link(g['from_id'], g['from_name'])}:\n{html.escape(g['text'])}\n\n"
        if len(cur) + len(entry) > 3800:
            chunks.append(cur.rstrip())
            cur = ""
        cur += entry
    if cur.strip():
        chunks.append(cur.rstrip())
    return chunks


async def deliver_pending(user_id: int, pending) -> bool:
    ids = {g.get("id") for g in pending}
    try:
        for chunk in build_greeting_chunks(pending):
            await bot.send_message(user_id, chunk)
            await asyncio.sleep(0.05)
    except TelegramForbiddenError:
        await mark_congratulated(user_id, 0, blocked=True)
        return False
    except Exception as e:
        logging.warning(f"Не удалось отправить поздравления друзей {user_id}: {e}")
        return False
    await remove_pending(user_id, ids)
    return True


async def check_birthdays():
    now = datetime.now(BIRTHDAY_TZ)
    if now.hour < BIRTHDAY_HOUR:
        return

    users = await load_users()
    for uid_str, u in list(users.items()):
        bday = u.get("birthday")
        if not bday or u.get("status") == "blocked":
            continue
        if not is_birthday_today(bday, now.date()):
            continue

        user_id = u.get("user_id") or int(uid_str)

        # 1) Поздравление от бота (один раз в год)
        if u.get("last_congrats_year") != now.year:
            name = html.escape(u.get("full_name") or "друг")

            age_line = ""
            parts = bday.split(".")
            if len(parts) == 3:
                age_line = f"Сегодня тебе исполняется <b>{now.year - int(parts[2])}</b>! "

            text = (
                f"🎉🎂 <b>С днём рождения, {name}!</b>\n\n"
                f"{age_line}Желаем отличного настроения, классных людей рядом "
                "и чтобы всё получалось! 🥳"
            )

            try:
                await bot.send_message(user_id, text)
                await mark_congratulated(user_id, now.year)
            except TelegramForbiddenError:
                await mark_congratulated(user_id, now.year, blocked=True)
                continue
            except Exception as e:
                logging.warning(f"Не удалось поздравить {user_id}: {e}")
                continue
            await asyncio.sleep(0.05)

        # 2) Поздравления от друзей, которые ждали этого дня
        pending = u.get("pending_greetings") or []
        if pending:
            await deliver_pending(user_id, pending)


async def birthday_loop():
    while True:
        try:
            await check_birthdays()
        except Exception as e:
            logging.exception(f"Ошибка в проверке дней рождения: {e}")
        await asyncio.sleep(600)  # проверка раз в 10 минут


# ==================================================
# СОСТОЯНИЯ (FSM) И КЛАВИАТУРЫ
# ==================================================

class SuggestionStates(StatesGroup):
    waiting_post = State()
    waiting_anon_choice = State()


class BirthdayStates(StatesGroup):
    waiting_date = State()


class GreetStates(StatesGroup):
    waiting_target = State()
    waiting_text = State()
    waiting_choice = State()


class SupportStates(StatesGroup):
    waiting_message = State()


class AdminStates(StatesGroup):
    waiting_reason = State()
    waiting_support_reply = State()
    waiting_edit_text = State()
    waiting_broadcast_message = State()
    waiting_author_message = State()


def main_keyboard(is_admin: bool = False):
    keyboard = [
        [KeyboardButton(text="📩 Предложить пост"), KeyboardButton(text="💬 Поддержка")],
        [KeyboardButton(text="ℹ️ FAQ"), KeyboardButton(text="🎂 День рождения")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


HOW_TEXT = (
    "ℹ️ <b>Как пользоваться ботом</b>\n\n"
    "Через этого бота можно отправить свой пост в наш канал.\n\n"
    "<b>Что делать:</b>\n\n"
    "1️⃣ Нажми «📩 Предложить пост»\n"
    "2️⃣ Отправь то, что хочешь опубликовать: текст, фото, видео или стикер\n"
    "3️⃣ Выбери, как подписать: 👤 с твоим именем или 🕶 анонимно\n"
    "4️⃣ Готово! Администратор посмотрит заявку, а когда пост выйдет, бот пришлёт тебе ссылку\n\n"
    "<b>Полезно знать:</b>\n\n"
    "• 📢 Пользоваться ботом можно только подписчикам канала\n"
    "• ⏳ Новый пост можно отправить раз в 5 минут\n"
    "• ❌ Если пост не подошёл, бот напишет причину\n"
    "• 💬 Остались вопросы? Кнопка «Поддержка» ведёт прямо к администратору"
)

FAQ_TITLE = "❓ <b>Частые вопросы</b>\n\nВыбери, что тебя интересует:"

# ключ -> (название кнопки, текст ответа)
FAQ_ITEMS = {
    "how": ("ℹ️ Как пользоваться ботом", HOW_TEXT),
    "limit": (
        "⏳ Почему нужно ждать 5 минут?",
        "⏳ <b>Почему нужно ждать 5 минут?</b>\n\n"
        "Между постами нужна пауза, чтобы заявки не копились пачками.\n\n"
        "Таймер включается только после того, как заявка дошла до администратора. "
        "Если ты отменил отправку, ждать не придётся."
    ),
    "anon": (
        "🕶 Можно ли анонимно?",
        "🕶 <b>Можно ли анонимно?</b>\n\n"
        "Да! После отправки поста бот спросит, как его подписать:\n\n"
        "• 👤 <b>С автором</b>: в канале будет твоё имя со ссылкой на профиль\n"
        "• 🕶 <b>Анонимно</b>: твоё имя в канале не показывается"
    ),
    "reject": (
        "❌ Почему отклонили пост?",
        "❌ <b>Почему отклонили пост?</b>\n\n"
        "Бот пришлёт причину отказа. Если что-то непонятно, напиши в «💬 Поддержку», "
        "администратор ответит прямо в этот чат."
    ),
    "edit": (
        "✏️ Могут ли изменить мой пост?",
        "✏️ <b>Могут ли изменить мой пост?</b>\n\n"
        "Да, администратор может поправить текст перед публикацией, например исправить опечатки."
    ),
    "link": (
        "📬 Как узнать, что пост вышел?",
        "📬 <b>Как узнать, что пост вышел?</b>\n\n"
        "Когда пост опубликуют, бот сам пришлёт тебе ссылку на него в канале."
    ),
    "bday": (
        "🎂 День рождения и поздравления",
        "🎂 <b>День рождения и поздравления</b>\n\n"
        "<b>Своя дата.</b> Нажми «🎂 День рождения» → «📅 Моя дата рождения» и отправь дату "
        "в формате ДД.ММ.ГГГГ, например 10.05.2004 (год можно не указывать). "
        "В этот день бот тебя поздравит. Дату можно изменить или удалить в любой момент.\n\n"
        "<b>Поздравить друга.</b> Нажми «🎁 Поздравить друга», напиши его @юзернейм и текст. "
        "Друг должен уже пользоваться ботом. Поздравление подписано твоим именем. "
        "Если день рождения не сегодня, бот предложит отправить сразу или в день рождения.\n\n"
        "Можно отправлять не больше 3 поздравлений в час."
    ),
    "support": (
        "💬 Как связаться с админом?",
        "💬 <b>Как связаться с админом?</b>\n\n"
        "Нажми «💬 Поддержка» в главном меню и напиши сообщение. "
        "Ответ придёт сюда, в этот же чат."
    ),
}


def faq_menu_keyboard():
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"faq:{key}")]
        for key, (title, _) in FAQ_ITEMS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data="faq:menu")
    ]])


SUB_TEXT = (
    "📢 <b>Чтобы пользоваться ботом, подпишись на наш канал.</b>\n\n"
    "Подпишись и нажми «✅ Я подписался»."
)


def subscribe_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
    ])


def cancel_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)


def anon_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 С автором", callback_data="anon:0"),
        InlineKeyboardButton(text="🕶 Анонимно", callback_data="anon:1")
    ]])


def admin_keyboard(request_id, user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{request_id}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_prep:{request_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{request_id}"),
         InlineKeyboardButton(text="✉️ Написать автору", callback_data=f"write_author:{user_id}")]
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


async def notify_user(user_id, text):
    """Безопасная отправка пользователю (не падает, если он заблокировал бота)."""
    try:
        await bot.send_message(user_id, text)
    except Exception as e:
        logging.warning(f"Не удалось уведомить пользователя {user_id}: {e}")


# ==================================================
# ОБЯЗАТЕЛЬНАЯ ПОДПИСКА НА КАНАЛ
# ==================================================

async def is_subscribed(user_id: int) -> bool:
    """Проверяет, что пользователь состоит в канале.
    Бот должен быть администратором канала (он уже им является, раз публикует посты)."""
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
    except Exception as e:
        # Если проверить не удалось, не блокируем людей из-за сбоя Telegram
        logging.warning(f"Не удалось проверить подписку {user_id}: {e}")
        return True

    if member.status in (
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    ):
        return True
    if member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False):
        return True
    return False


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")

        # Админа и неопределённых пользователей не проверяем
        if user is None or user.id == ADMIN_ID:
            return await handler(event, data)

        # Кнопку «Я подписался» пропускаем, она сама проверяет подписку
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)

        if await is_subscribed(user.id):
            return await handler(event, data)

        # Не подписан: запоминаем для рассылки и показываем просьбу подписаться
        users = await load_users()
        if str(user.id) not in users:
            await register_user(user)

        if isinstance(event, Message):
            await event.answer(SUB_TEXT, reply_markup=subscribe_keyboard())
        elif isinstance(event, CallbackQuery):
            await event.answer("📢 Сначала подпишись на канал!", show_alert=True)
            if event.message:
                await event.message.answer(SUB_TEXT, reply_markup=subscribe_keyboard())
        return None


dp.message.outer_middleware(SubscriptionMiddleware())
dp.callback_query.outer_middleware(SubscriptionMiddleware())


# ==================================================
# ХЕНДЛЕРЫ СТАРТА И ОТМЕНЫ
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


@dp.message(F.text == "ℹ️ FAQ")
async def faq_open(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(FAQ_TITLE, reply_markup=faq_menu_keyboard())


@dp.callback_query(F.data.startswith("faq:"))
async def faq_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]

    if key == "menu":
        text, keyboard = FAQ_TITLE, faq_menu_keyboard()
    elif key in FAQ_ITEMS:
        text, keyboard = FAQ_ITEMS[key][1], faq_back_keyboard()
    else:
        await callback.answer()
        return

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramAPIError:
        pass  # то же сообщение нажали повторно
    await callback.answer()


@dp.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await register_user(callback.from_user)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "✅ Спасибо за подписку! Теперь бот полностью доступен.",
            reply_markup=main_keyboard(callback.from_user.id == ADMIN_ID)
        )
        await callback.answer()
    else:
        await callback.answer("❌ Ты ещё не подписан на канал.", show_alert=True)


# ==================================================
# ДНИ РОЖДЕНИЯ: МЕНЮ
# ==================================================

BIRTHDAY_PROMPT = (
    "🎂 <b>Напиши свою дату рождения</b> в формате ДД.ММ.ГГГГ, например <code>10.05.2004</code>\n\n"
    "Год можно не указывать: <code>10.05</code>\n\n"
    "В этот день бот тебя поздравит 🎉"
)


def birthday_manage_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ Изменить", callback_data="bday:edit"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data="bday:delete")
    ]])


GREET_TARGET_PROMPT = (
    "🎁 <b>Кого хочешь поздравить?</b>\n\n"
    "Напиши его @юзернейм"
)


def birthday_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Моя дата рождения", callback_data="bday:mine")],
        [InlineKeyboardButton(text="🎁 Поздравить друга", callback_data="bday:congrats")]
    ])


def greet_choice_keyboard(has_date: bool):
    if has_date:
        rows = [
            [InlineKeyboardButton(text="⏰ В день рождения", callback_data="greet:later"),
             InlineKeyboardButton(text="📨 Сейчас", callback_data="greet:now")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="greet:cancel")]
        ]
    else:
        rows = [[
            InlineKeyboardButton(text="📨 Сейчас", callback_data="greet:now"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="greet:cancel")
        ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_my_birthday(target: Message, user, state: FSMContext):
    await register_user(user)
    users = await load_users()
    bday = users.get(str(user.id), {}).get("birthday")

    if bday:
        await target.answer(
            f"🎂 <b>Твой день рождения:</b> {bday}\n\nВ этот день бот тебя поздравит 🎉",
            reply_markup=birthday_manage_keyboard()
        )
    else:
        await state.set_state(BirthdayStates.waiting_date)
        await target.answer(BIRTHDAY_PROMPT, reply_markup=cancel_keyboard())


@dp.message(F.text == "🎂 День рождения")
async def birthday_open(message: Message, state: FSMContext):
    await state.clear()
    await register_user(message.from_user)
    await message.answer(
        "🎂 <b>День рождения</b>\n\nЧто хочешь сделать?",
        reply_markup=birthday_menu_keyboard()
    )


@dp.callback_query(F.data == "bday:mine")
async def birthday_mine(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_my_birthday(callback.message, callback.from_user, state)
    await callback.answer()


@dp.callback_query(F.data == "bday:congrats")
async def greet_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user.id != ADMIN_ID:
        wait = await get_greet_wait(callback.from_user.id)
        if wait > 0:
            await callback.answer(greet_wait_text(wait), show_alert=True)
            return
    await register_user(callback.from_user)
    await state.set_state(GreetStates.waiting_target)
    await callback.message.answer(GREET_TARGET_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "bday:edit")
async def birthday_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BirthdayStates.waiting_date)
    await callback.message.answer(BIRTHDAY_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "bday:delete")
async def birthday_delete(callback: CallbackQuery):
    user_id = callback.from_user.id
    await set_birthday(user_id, None)

    # Ждать больше нечего, поэтому отложенные поздравления друзей уходят сразу
    users = await load_users()
    pending = users.get(str(user_id), {}).get("pending_greetings") or []
    delivered = await deliver_pending(user_id, pending) if pending else False

    text = "🗑 Дата рождения удалена."
    if delivered:
        text += "\n\nПоздравления от друзей, которые ждали твоего дня, отправлены сейчас."
    try:
        await callback.message.edit_text(text)
    except TelegramAPIError:
        pass
    await callback.answer()


@dp.message(Command("birthdays"), F.from_user.id == ADMIN_ID)
async def list_birthdays(message: Message, state: FSMContext):
    await state.clear()
    users = await load_users()

    items = []
    for u in users.values():
        b = u.get("birthday")
        if not b:
            continue
        try:
            day, month = int(b[:2]), int(b[3:5])
        except ValueError:
            continue
        name = html.escape(u.get("full_name") or "Без имени")
        uname = f" (@{html.escape(u['username'])})" if u.get("username") else ""
        items.append(((month, day), f"{name}{uname} — {b}"))

    if not items:
        await message.answer("🎂 Пока никто не указал день рождения.")
        return

    items.sort(key=lambda x: x[0])
    chunk = f"🎂 <b>Дни рождения ({len(items)}):</b>\n\n"
    for _, line in items:
        if len(chunk) + len(line) + 1 > 3800:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await message.answer(chunk)


# ==================================================
# СТАТИСТИКА ДЛЯ АДМИНА
# ==================================================

@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
@dp.message(F.text == "📊 Статистика", F.from_user.id == ADMIN_ID)
async def show_stats(message: Message, state: FSMContext):
    await state.clear()
    users = await load_users()
    suggestions = await load_suggestions()

    total = len(users)
    blocked = sum(1 for u in users.values() if u.get("status") == "blocked")
    active = total - blocked
    pending = len(suggestions)
    with_bday = sum(1 for u in users.values() if u.get("birthday"))

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Людей в боте: <b>{active}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n"
        f"📁 Всего запускали: <b>{total}</b>\n"
        f"🎂 Указали день рождения: <b>{with_bday}</b>\n\n"
        f"📩 Заявок на рассмотрении: <b>{pending}</b>\n\n"
        "✉️ Чтобы написать человеку, отправь ID на первой строке, а текст со второй.",
        reply_markup=main_keyboard(True)
    )


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

    # Лимит: для админа не действует
    if message.from_user.id != ADMIN_ID:
        left = await get_cooldown_left(message.from_user.id)
        if left > 0:
            await state.clear()
            minutes, seconds = divmod(left, 60)
            await message.answer(
                f"⏳ Подождите {minutes} мин {seconds} сек перед следующим постом.",
                reply_markup=main_keyboard(False)
            )
            return

    await state.set_state(SuggestionStates.waiting_post)
    await message.answer(
        "📩 Отправь свой пост следующим сообщением (текст, фото, видео или стикер):",
        reply_markup=cancel_keyboard()
    )


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

    # Сразу сбрасываем состояние, чтобы двойной клик не создал дубль заявки
    await state.clear()

    request_id = str(int(time.time() * 1000))
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
            await bot.send_message(ADMIN_ID, f"📩 Новая заявка №{request_id} ({anon_status})\n\n📝 Текст:\n{html.escape(data['post_text'])}", reply_markup=admin_keyboard(request_id, data["user_id"]))
        elif data["post_type"] == "photo":
            await bot.send_photo(ADMIN_ID, photo=data["file_id"], caption=f"📩 Новая заявка №{request_id} ({anon_status})", reply_markup=admin_keyboard(request_id, data["user_id"]))
        elif data["post_type"] == "video":
            await bot.send_video(ADMIN_ID, video=data["file_id"], caption=f"📩 Новая заявка №{request_id} ({anon_status})", reply_markup=admin_keyboard(request_id, data["user_id"]))
        elif data["post_type"] == "sticker":
            await bot.send_sticker(ADMIN_ID, sticker=data["file_id"])
            await bot.send_message(ADMIN_ID, f"📩 Новая заявка №{request_id} (Стикер | {anon_status})", reply_markup=admin_keyboard(request_id, data["user_id"]))

        await callback.message.edit_text("✅ Твой пост отправлен администратору!")
        await callback.message.answer("Главное меню:", reply_markup=main_keyboard(False))

        # Запускаем таймер лимита только после успешной отправки
        await set_last_post_time(data["user_id"])
    except Exception as e:
        logging.error(f"Ошибка отправки админу: {e}")
        # Откатываем заявку, раз админ её не получил
        suggestions = await load_suggestions()
        suggestions.pop(request_id, None)
        await save_suggestions(suggestions)
        await callback.message.answer("❌ Ошибка отправки. Попробуй ещё раз.", reply_markup=main_keyboard(False))


# ==================================================
# ПУБЛИКАЦИЯ
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
    except Exception as e:
        logging.error(f"Ошибка публикации: {e}")
        await callback.answer("❌ Ошибка публикации.", show_alert=True)
        return

    # Уведомление автору — отдельно, чтобы его ошибка не выглядела как ошибка публикации
    await notify_user(
        request["user_id"],
        f"🔥 Твою историю опубликовали!\nПосмотреть можно здесь: {post_link}"
    )


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
    except Exception as e:
        logging.error(f"Ошибка публикации отредактированного поста: {e}")
        await message.answer("❌ Ошибка публикации.")
        await state.clear()
        return

    await notify_user(
        request["user_id"],
        f"🔥 Твою историю (после правок) опубликовали!\nПосмотреть можно здесь: {post_link}"
    )
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
    await callback.message.answer("❌ Напиши причину отклонения:")
    await callback.answer()


@dp.message(AdminStates.waiting_reason)
async def reject_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text:
        await message.answer("❌ Отправь причину текстом.")
        return

    data = await state.get_data()
    request_id = data["request_id"]
    suggestions = await load_suggestions()
    request = suggestions.get(request_id)

    if request:
        try:
            await bot.send_message(request["user_id"], f"❌ Твой пост отклонён.\nПричина: {html.escape(message.text)}")
        except Exception as e:
            logging.warning(f"Не удалось отправить причину отклонения: {e}")
            await message.answer("⚠️ Не удалось уведомить автора (возможно, он заблокировал бота). Заявка всё равно удалена.")
        del suggestions[request_id]
        await save_suggestions(suggestions)
        await message.answer("✅ Заявка отклонена и удалена.", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("⚠️ Заявка уже обработана или удалена.", reply_markup=ReplyKeyboardRemove())
    await state.clear()


# ==================================================
# ПОДДЕРЖКА
# ==================================================

@dp.message(F.text == "💬 Поддержка")
async def support_start(message: Message, state: FSMContext):
    # Лимит: для админа не действует
    if message.from_user.id != ADMIN_ID:
        left = await get_support_cooldown_left(message.from_user.id)
        if left > 0:
            await state.clear()
            minutes, seconds = divmod(left, 60)
            wait = f"{minutes} мин {seconds} сек" if minutes else f"{seconds} сек"
            await message.answer(
                f"⏳ Ты уже недавно писал в поддержку. Подожди {wait} перед следующим обращением.",
                reply_markup=main_keyboard(False)
            )
            return

    await state.set_state(SupportStates.waiting_message)
    await message.answer("💬 Напиши сообщение для поддержки:", reply_markup=cancel_keyboard())


@dp.message(SupportStates.waiting_message)
async def receive_support_message(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_keyboard(message.from_user.id == ADMIN_ID))
        return
    if not message.text:
        await message.answer("❌ Отправь сообщение текстом.")
        return
    user = message.from_user
    await bot.send_message(
        ADMIN_ID,
        f"💬 Обращение от {html.escape(user.full_name)} (ID: {user.id}):\n\n{html.escape(message.text)}",
        reply_markup=support_admin_keyboard(user.id)
    )
    await message.answer("✅ Отправлено в поддержку!", reply_markup=main_keyboard(user.id == ADMIN_ID))
    await set_last_support_time(user.id)
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
    if not message.text:
        await message.answer("❌ Отправь ответ текстом.")
        return
    data = await state.get_data()
    try:
        await bot.send_message(data["target_user_id"], f"🎧 Ответ поддержки:\n\n{html.escape(message.text)}")
        await message.answer("✅ Ответ отправлен!")
    except Exception:
        await message.answer("❌ Не удалось отправить.")
    await state.clear()


# ==================================================
# ДНИ РОЖДЕНИЯ: ВВОД ДАТЫ
# ==================================================

@dp.message(BirthdayStates.waiting_date)
async def birthday_receive(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Отправь дату текстом, например 10.05.2004")
        return

    value = parse_birthday(message.text)
    if not value:
        await message.answer(
            "❌ Не получилось понять дату.\n\n"
            "Напиши в формате ДД.ММ.ГГГГ, например <code>10.05.2004</code> "
            "(год можно не указывать: <code>10.05</code>)."
        )
        return

    await register_user(message.from_user)
    await set_birthday(message.from_user.id, value)
    await state.clear()
    await message.answer(
        f"✅ Сохранено: <b>{value}</b>\n\n"
        "В этот день бот тебя поздравит 🎉\n"
        "Изменить дату можно в любой момент кнопкой «🎂 День рождения».",
        reply_markup=main_keyboard(message.from_user.id == ADMIN_ID)
    )


# ==================================================
# ПОЗДРАВЛЕНИЕ ДРУГА
# ==================================================

@dp.message(GreetStates.waiting_target)
async def greet_target(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Напиши @юзернейм текстом.")
        return

    raw = re.sub(r"^(https?://)?t\.me/", "", message.text.strip(), flags=re.IGNORECASE)
    raw = raw.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", raw):
        await message.answer("❌ Это не похоже на юзернейм. Напиши, например, <code>@ivan</code>")
        return

    uid_str, rec = await find_user_by_username(raw)
    if not rec:
        await message.answer(
            f"❌ Не нашёл @{html.escape(raw)}.\n\n"
            "Поздравить можно только тех, кто уже пользуется ботом. "
            "Попробуй другой юзернейм или нажми «Отмена»."
        )
        return

    target_id = int(uid_str)
    if target_id == message.from_user.id:
        await message.answer("❌ Себя поздравлять не нужно, бот сделает это сам. Напиши другой юзернейм.")
        return
    if rec.get("status") == "blocked":
        await message.answer("❌ Этот человек заблокировал бота, поздравление не дойдёт. Напиши другой юзернейм.")
        return

    name = rec.get("full_name") or raw
    await state.update_data(target_id=target_id, target_name=name)
    await state.set_state(GreetStates.waiting_text)
    await message.answer(
        f"✅ Нашёл: <b>{html.escape(name)}</b> (@{html.escape(rec.get('username') or raw)})\n"
        "Напиши текст поздравления:"
    )


@dp.message(GreetStates.waiting_text)
async def greet_text(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Отправь поздравление текстом.")
        return

    text = message.text.strip()
    if len(text) > GREET_MAX_LEN:
        await message.answer(f"❌ Слишком длинно: максимум {GREET_MAX_LEN} символов, сейчас {len(text)}. Сократи текст.")
        return

    sender = message.from_user
    is_admin = sender.id == ADMIN_ID

    if not is_admin:
        wait = await get_greet_wait(sender.id)
        if wait > 0:
            await state.clear()
            await message.answer(greet_wait_text(wait), reply_markup=main_keyboard(False))
            return

    data = await state.get_data()
    target_id = data["target_id"]
    name = html.escape(data["target_name"])

    users = await load_users()
    bday = users.get(str(target_id), {}).get("birthday")
    today = datetime.now(BIRTHDAY_TZ).date()

    # День рождения именно сегодня: отправляем сразу
    if bday and is_birthday_today(bday, today):
        ok, err = await send_greeting_now(sender, target_id, text)
        await state.clear()
        if ok:
            await record_greeting(sender.id)
            await message.answer(
                f"✅ Поздравление отправлено: {name}.\nКак раз сегодня день рождения!",
                reply_markup=main_keyboard(is_admin)
            )
        else:
            await message.answer(err, reply_markup=main_keyboard(is_admin))
        return

    await state.update_data(text=text)
    await state.set_state(GreetStates.waiting_choice)
    if bday:
        await message.answer(
            f"🎂 День рождения у {name}: <b>{bday[:5]}</b>.\nЧто сделать с поздравлением?",
            reply_markup=greet_choice_keyboard(True)
        )
    else:
        await message.answer(
            f"Дата рождения у {name} не указана.\nОтправить поздравление сейчас?",
            reply_markup=greet_choice_keyboard(False)
        )


@dp.callback_query(GreetStates.waiting_choice, F.data.startswith("greet:"))
async def greet_choice(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    sender = callback.from_user
    target_id = data.get("target_id")
    text = data.get("text")
    name = html.escape(data.get("target_name") or "")
    await state.clear()

    if action == "now":
        ok, err = await send_greeting_now(sender, target_id, text)
        if ok:
            await record_greeting(sender.id)
            result = f"✅ Поздравление отправлено: {name}."
        else:
            result = err
    elif action == "later":
        users = await load_users()
        bday = users.get(str(target_id), {}).get("birthday")
        if not bday:
            result = "⚠️ Дату рождения уже удалили, поздравление не сохранено. Отправь его заново."
        elif await add_pending_greeting(target_id, sender, text):
            await record_greeting(sender.id)
            result = f"✅ Поздравление для {name} будет отправлено {bday[:5]}."
        else:
            result = f"❌ Для {name} уже накопилось слишком много поздравлений. Отправь своё сейчас."
    else:
        result = "❌ Отменено."

    try:
        await callback.message.edit_text(result)
    except TelegramAPIError:
        pass
    await callback.message.answer("Главное меню:", reply_markup=main_keyboard(sender.id == ADMIN_ID))
    await callback.answer()


@dp.callback_query(F.data.startswith("greet:"))
async def greet_stale(callback: CallbackQuery):
    await callback.answer("Это сообщение устарело. Начни заново через «🎂 День рождения».", show_alert=True)


# ==================================================
# СООБЩЕНИЯ ОТ АДМИНА ПОЛЬЗОВАТЕЛЯМ
# 1) по ID: первая строка — ID, со второй строки — текст
# 2) кнопкой «Написать автору» под заявкой
# ==================================================

async def deliver_admin_text(target_id: int, text: str, who: str) -> str:
    """Отправляет текст админа пользователю. Возвращает ответ для админа."""
    try:
        await bot.send_message(
            target_id,
            f"📩 Сообщение от администратора:\n\n{html.escape(text)}\n\n"
            "💬 Чтобы ответить, нажми «Поддержка» в меню."
        )
        return f"✅ Сообщение отправлено {who}."
    except TelegramForbiddenError:
        # Пользователь заблокировал бота или удалил чат
        users = await load_users()
        if str(target_id) in users:
            users[str(target_id)]["status"] = "blocked"
            await save_users(users)
        return f"❌ Не получилось отправить {who}: он заблокировал бота или удалил чат."
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            return (f"❌ Не получилось отправить {who}: чат не найден. "
                    "Либо он ни разу не запускал бота, либо удалил чат.")
        logging.warning(f"Ошибка отправки {target_id}: {e}")
        return f"❌ Не получилось отправить {who}."
    except Exception as e:
        logging.warning(f"Ошибка отправки {target_id}: {e}")
        return f"❌ Не получилось отправить {who}."


@dp.message(StateFilter(None), F.from_user.id == ADMIN_ID, F.text)
async def admin_direct_message(message: Message):
    parts = message.text.split("\n", 1)
    first_line = parts[0].strip()

    # Если первая строка не ID, это обычное сообщение, ничего не делаем
    if not first_line.isdigit():
        return

    target_id = int(first_line)
    text = parts[1].strip() if len(parts) > 1 else ""

    if not text:
        await message.answer(
            "⚠️ Не вижу текста.\n\n"
            "Формат: на первой строке ID, а со второй строки текст сообщения."
        )
        return

    result = await deliver_admin_text(target_id, text, f"пользователю {target_id}")
    await message.answer(result)


@dp.callback_query(F.data.startswith("write_author:"))
async def write_author_prepare(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    target_id = int(callback.data.split(":")[1])
    await state.set_state(AdminStates.waiting_author_message)
    await state.update_data(target_user_id=target_id)
    await callback.message.answer(
        "✍️ Напиши сообщение автору этой заявки:",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()


@dp.message(AdminStates.waiting_author_message)
async def write_author_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text:
        await message.answer("❌ Отправь сообщение текстом.")
        return

    data = await state.get_data()
    result = await deliver_admin_text(data["target_user_id"], message.text, "автору заявки")
    await message.answer(result, reply_markup=main_keyboard(True))
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
    asyncio.create_task(birthday_loop())
    logging.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
