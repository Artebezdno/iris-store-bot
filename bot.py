import os
import asyncio
import uuid
import time
import re
import requests
import base64
from threading import Thread

from flask import Flask
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7837011810"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@IrisStoreMarket")

REVIEWS_LINK = "https://t.me/IrisStoreMarket"
SITE_URL = "https://iris-store-bot.onrender.com/"

CARD_NUMBER = "5355 2800 2289 5252"
BANK_NAME = "PUMB"

app = Flask(__name__)

@app.route("/")
def home():
    return "Iris Store bot is running ✅"

def run_site():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_site, daemon=True).start()

def auto_ping():
    while True:
        try:
            response = requests.get(SITE_URL, timeout=10)
            print(f"Ping OK: {response.status_code}")
        except Exception as e:
            print("Ping error:", e)

        time.sleep(240)

def start_auto_ping():
    Thread(target=auto_ping, daemon=True).start()

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

def save_users_to_github():
    try:
        with open("users.txt", "r", encoding="utf-8") as f:
            content = f.read()

        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/users.txt"

        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

        get_file = requests.get(url, headers=headers)

        sha = None
        if get_file.status_code == 200:
            sha = get_file.json()["sha"]

        data = {
            "message": "Update users.txt",
            "content": base64.b64encode(content.encode()).decode(),
            "branch": GITHUB_BRANCH
        }

        if sha:
            data["sha"] = sha

        requests.put(url, headers=headers, json=data)

    except Exception as e:
        print("GitHub save error:", e)


# orders — текущий заказ пользователя
# orders_by_id — все заказы, чтобы кнопки Одобрить/Отклонить работали правильно,
# даже если пользователь уже выбрал новый пакет.
orders = {}
orders_by_id = {}
waiting_username = {}


def make_order_id():
    return f"IRIS{1000 + (uuid.uuid4().int % 9000)}"

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 Купить ириски", callback_data="buy_iris")],
        [
            InlineKeyboardButton(text="⭐ Отзывы", url=REVIEWS_LINK),
            InlineKeyboardButton(text="❓ FAQ", callback_data="faq")
        ],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")]
    ])

@dp.message(Command("start"))
async def start(message: Message):
    # Сохраняем пользователя для рассылки
    user_id = str(message.from_user.id)

    try:
        with open("users.txt", "r", encoding="utf-8") as f:
            users = f.read().splitlines()
    except:
        users = []

    if user_id not in users:
        with open("users.txt", "a", encoding="utf-8") as f:
            f.write(user_id + "\n")
        save_users_to_github()

    await message.answer(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "faq")
async def faq(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Почему Iris Store?", callback_data="why_store")],
        [InlineKeyboardButton(text="🛡️ Гарантия", callback_data="guarantee")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_start")]
    ])

    await call.message.edit_text(
    "❓ <b>FAQ / Частые вопросы</b>\n\n"
    "💳 <b>Как купить?</b>\n"
    "— Выберите пакет, укажите username, оплатите и отправьте чек.\n\n"
    "⏳ <b>Сколько ждать?</b>\n"
    "— Обычно в течение 24 часов.\n\n"
    "🍬 <b>Куда придут ириски?</b>\n"
    "— На username, который вы указали.\n\n"
    "💸 <b>Можно ли сделать возврат?</b>\n"
    "— Да, если заказ ещё не выполнен. После выдачи ирисок возврат невозможен.\n\n"
    "📸 <b>Отправил чек — что дальше?</b>\n"
    "— Ожидайте проверки администратора.\n\n"
    "⭐ <b>Где отзывы?</b>\n"
    "— Кнопка «Отзывы» в главном меню.",
    reply_markup=keyboard
)



@dp.callback_query(F.data == "why_store")
async def why_store(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="faq")]
    ])

    await call.message.edit_text(
        "⭐ <b>Почему выбирают Iris Store?</b>\n\n"
        "✅ Быстрая обработка заказов\n"
        "💳 Удобная оплата на украинскую карту\n"
        "🍬 Выдача на username\n"
        "⭐ Отзывы покупателей\n"
        "🇺🇦 Украинский продавец",
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "guarantee")
async def guarantee(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="faq")]
    ])

    await call.message.edit_text(
        "🛡️ <b>Гарантия Iris Store</b>\n\n"
        "🍬 Заказы проверяются вручную\n\n"
        "✅ Ириски выдаются на указанный username\n\n"
        "💬 При вопросах поддержка поможет\n\n"
        "📸 Каждый чек проверяется администратором\n\n"
        "⚠️ Проверяйте username внимательно перед оплатой.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗️ Написать в поддержку", url="https://t.me/Artemwesh")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_start")]
    ])

    await call.message.edit_text(
        "💬 <b>Поддержка</b>\n\n"
        "Если возникли вопросы по оплате, заказу или выдаче ирисок — напишите нам.\n\n"
        "⏳ Обычно отвечаем быстро",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "buy_iris")
async def buy_iris(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 50 ирисок — 45 грн", callback_data="pack_50")],
        [InlineKeyboardButton(text="🍬 100 ирисок — 89 грн", callback_data="pack_100")],
        [InlineKeyboardButton(text="🍬 500 ирисок — 425 грн", callback_data="pack_500")],
        [InlineKeyboardButton(text="🍬 1000 ирисок — 845 грн", callback_data="pack_1000")],
        [InlineKeyboardButton(text="🍬 2000 ирисок — 1660 грн", callback_data="pack_2000")],
        [InlineKeyboardButton(text="🍬 5000 ирисок — 4100 грн", callback_data="pack_5000")],
        [InlineKeyboardButton(text="🍬 10000 ирисок — 8100 грн", callback_data="pack_10000")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_start")]
    ])

    await call.message.edit_text(
        "🍬 <b>Выберите пакет ирисок:</b>",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("pack_"))
async def choose_pack(call: CallbackQuery):
    packs = {
        "pack_50": ("50 ирисок", "45 грн"),
        "pack_100": ("100 ирисок", "89 грн"),
        "pack_500": ("500 ирисок", "425 грн"),
        "pack_1000": ("1000 ирисок", "845 грн"),
        "pack_2000": ("2000 ирисок", "1660 грн"),
        "pack_5000": ("5000 ирисок", "4100 грн"),
        "pack_10000": ("10000 ирисок", "8100 грн")
    }

    item, price = packs[call.data]
    order_id = make_order_id()

    new_order = {
        "buyer_id": call.from_user.id,
        "buyer_username": call.from_user.username,
        "buyer_name": call.from_user.full_name,
        "item": item,
        "price": price,
        "order_id": order_id,
        "receiver": None,
        "status": "new"
    }

    # Новый выбранный пакет становится текущим заказом.
    # Старые заказы остаются в orders_by_id, чтобы админ мог их одобрить/отклонить.
    orders[call.from_user.id] = new_order
    orders_by_id[order_id] = new_order
    waiting_username[call.from_user.id] = True

    await call.message.edit_text(
        "🍬 <b>Введите username получателя</b>\n\n"
        "Пример:\n"
        "<code>@username</code>\n\n"
        "⚠️ Проверьте username внимательно.\n"
        "После выдачи изменить получателя нельзя."
    )

@dp.message(F.text.startswith("@"))
async def get_receiver_username(message: Message):
    if not waiting_username.get(message.from_user.id):
        return

    user_order = orders.get(message.from_user.id)

    if not user_order:
        await message.answer("❌ Сначала выберите пакет ирисок.")
        return

    receiver = message.text.strip()

    if not re.match(r"^@[A-Za-z0-9_]{5,32}$", receiver):
        await message.answer(
            "❌ <b>Username указан неверно.</b>\n\n"
            "Пример правильного формата:\n"
            "<code>@username</code>"
        )
        return

    user_order["receiver"] = receiver
    user_order["status"] = "waiting_payment"
    waiting_username[message.from_user.id] = False

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_iris")]
    ])

    await message.answer(
        "💳 <b>Оплата заказа</b>\n\n"
        f"🧾 <b>Номер заказа:</b> #{user_order['order_id']}\n\n"
        f"🍬 <b>Товар:</b> {user_order['item']}\n"
        f"👤 <b>Получатель:</b> {receiver}\n"
        f"💸 <b>Сумма:</b> {user_order['price']}\n\n"
        f"🏦 <b>Банк:</b> {BANK_NAME}\n"
        f"💳 <b>Карта:</b> <code>{CARD_NUMBER}</code>\n\n"
        "⏳ <b>Проверка:</b> Обычно в течение 24 часов 💛\n\n"
        "После оплаты нажмите кнопку ниже.",
        reply_markup=keyboard
    )


@dp.message(Command("sendall"))
async def sendall(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    text_to_send = message.text.replace("/sendall", "", 1).strip()

    if not text_to_send:
        await message.answer(
            "❌ Напишите текст рассылки\n\n"
            "Пример:\n"
            "/sendall 🔥 Новые цены на ириски!"
        )
        return

    try:
        with open("users.txt", "r", encoding="utf-8") as f:
            users = [u.strip() for u in f.read().splitlines() if u.strip()]
    except:
        users = []

    if not users:
        await message.answer("❌ В users.txt пока нет пользователей.")
        return

    success = 0
    failed = 0

    for user_id in users:
        try:
            await bot.send_message(int(user_id), text_to_send)
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"👥 Отправлено: {success}\n"
        f"❌ Ошибок: {failed}"
    )


@dp.message(F.text)
async def text_router(message: Message):

    # Умные слова: прайс / помощь / статус / карта
    user_text = (message.text or "").lower().strip()

    if user_text in ["прайс", "цены", "цена", "сколько стоит", "стоимость"]:
        await message.answer(
            "🍬 <b>Прайс Iris Store</b>

"
            "━━━━━━━━━━━━━━

"
            "50 ирисок — 45 грн
"
            "100 ирисок — 89 грн
"
            "500 ирисок — 425 грн
"
            "1000 ирисок — 845 грн
"
            "2000 ирисок — 1660 грн
"
            "5000 ирисок — 4100 грн
"
            "10000 ирисок — 8100 грн

"
            "━━━━━━━━━━━━━━

"
            "🛍️ Для покупки нажмите:
"
            "🍬 Купить ириски"
        )
        return

    if user_text in ["помощь", "поддержка", "админ", "проблема"]:
        await message.answer(
            "💬 <b>Поддержка Iris Store</b>\n\n"
            "Если возникла проблема — напишите администратору:\n\n"
            "@Artemwesh\n\n"
            "📌 Желательно укажите номер заказа."
        )
        return

    if user_text in ["статус", "заказ", "проверить заказ"]:
        await message.answer(
            "🧾 <b>Проверка заказа</b>\n\n"
            "Отправьте номер заказа:\n\n"
            "Пример:\n"
            "<code>#IRIS5091</code>"
        )
        return

    if user_text in ["карта", "оплата", "реквизиты", "номер карты"]:
        await message.answer(
            "💳 <b>Реквизиты для оплаты</b>\n\n"
            "Банк: PUMB\n\n"
            "<code>5355 2800 2289 5252</code>\n\n"
            "⚠️ После оплаты обязательно отправьте чек."
        )
        return

    text = (message.text or "").strip().upper()
    # Если ждём username, но пользователь написал не @username
    if waiting_username.get(message.from_user.id):
        await message.answer(
            "❌ Отправьте username в правильном формате.\n\n"
            "Пример:\n"
            "<code>@Artemwesh</code>"
        )
        return

@dp.callback_query(F.data == "paid")
async def paid(call: CallbackQuery):
    user_order = orders.get(call.from_user.id)

    if not user_order:
        await call.message.answer("❌ Сначала выберите пакет ирисок.")
        return

    if not user_order.get("receiver"):
        await call.message.answer("❌ Сначала укажите username получателя.")
        return

    if user_order.get("status") == "pending":
        await call.message.answer(
            "⏳ Ваш чек уже находится на проверке.\n"
            "Пожалуйста, дождитесь решения администратора."
        )
        return

    if user_order.get("status") == "approved":
        await call.message.answer(
            "✅ Этот заказ уже одобрен.\n"
            "Чтобы купить ещё, выберите новый пакет."
        )
        return

    user_order["status"] = "waiting_photo"

    await call.message.answer(
        "📸 <b>Отправьте чек оплаты</b>"
    )

@dp.message(F.photo)
async def get_payment_photo(message: Message):
    user_order = orders.get(message.from_user.id)

    if not user_order:
        await message.answer("❌ Сначала выберите пакет ирисок.")
        return

    if not user_order.get("receiver"):
        await message.answer(
            "❌ Сначала отправьте username получателя.\n\n"
            "Пример:\n"
            "<code>@Artemwesh</code>"
        )
        return

    # Если по текущему заказу уже отправлен чек — второй скрин не отправляем админу.
    if user_order.get("status") == "pending":
        await message.answer(
            "⏳ Ваш чек уже находится на проверке.\n"
            "Пожалуйста, дождитесь решения администратора."
        )
        return

    if user_order.get("status") == "approved":
        await message.answer(
            "✅ Этот заказ уже одобрен.\n"
            "Чтобы купить ещё, выберите новый пакет."
        )
        return

    # Первый скрин по текущему заказу
    user_order["status"] = "pending"

    buyer_username = f"@{user_order['buyer_username']}" if user_order["buyer_username"] else "нет username"

    await message.answer(
        f"🟡 <b>Заказ #{user_order['order_id']}</b>\n\n"
        "Чек отправлен на проверку.\n\n"
        "⏳ Заказ будет обработан в течение 24 часов 💛"
    )
    caption = (
        "🧾 <b>Новый заказ</b>\n\n"
        f"🆔 Номер: <code>#{user_order['order_id']}</code>\n\n"
        f"👤 Покупатель: <b>{user_order['buyer_name']}</b>\n"
        f"🔗 Username: {buyer_username}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"🎯 Получатель: <b>{user_order['receiver']}</b>\n"
        f"💸 Сумма: <b>{user_order['price']}</b>\n\n"
        "📸 Чек оплаты:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_{message.from_user.id}_{user_order['order_id']}"
            ),
            InlineKeyboardButton(
                text="❌ Отказаться",
                callback_data=f"deny_{message.from_user.id}_{user_order['order_id']}"
            )
        ]
    ])

    await bot.send_photo(
        ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=caption,
        reply_markup=keyboard
    )

def get_value_from_caption(caption: str, label: str):
    for line in (caption or "").splitlines():
        if label in line:
            value = line.split(":", 1)[-1].strip()
            value = value.replace("<b>", "").replace("</b>", "")
            value = value.replace("<code>", "").replace("</code>", "")
            return value
    return "не указано"




@dp.callback_query(F.data.startswith("approve_"))
async def approve_payment(call: CallbackQuery):
    data = call.data.replace("approve_", "", 1)
    parts = data.split("_", 1)

    if len(parts) == 2:
        user_id = int(parts[0])
        order_id = parts[1]
    else:
        # На всякий случай поддержка старых кнопок
        order_id = data
        user_order_old = orders_by_id.get(order_id)
        if not user_order_old:
            await call.answer("Заказ не найден", show_alert=True)
            return
        user_id = user_order_old["buyer_id"]

    user_order = orders_by_id.get(order_id)

    if user_order and user_order.get("status") == "approved":
        await call.answer("Этот заказ уже одобрен", show_alert=True)
        return

    if user_order:
        user_order["status"] = "approved"
        item = user_order["item"]
        receiver = user_order["receiver"]
    else:
        # Если бот перезапустился, берём данные из текста заявки админу.
        caption = call.message.caption or ""
        item = get_value_from_caption(caption, "🍬 Товар")
        receiver = get_value_from_caption(caption, "🎯 Получатель")

    await bot.send_message(
        user_id,
        f"✅ <b>Заказ #{order_id} выполнен!</b>\n\n"
        "🍬 Ириски успешно выданы 💜"
    )

    await bot.send_message(
        CHANNEL_ID,
        f"✅ <b>Покупатель получил ириски</b>\n\n"
        f"🧾 <b>Номер заказа:</b> #{order_id}\n"
        f"🍬 <b>Количество:</b> {item}\n"
        f"👤 <b>Получатель:</b> {receiver}\n"
        f"💎 <b>Статус:</b> успешно получено\n\n"
        "🛍️ Спасибо за покупку в <b>Iris Store</b>"
    )

    await call.message.edit_caption(
        caption=(call.message.caption or "") + "\n\n✅ <b>ОДОБРЕНО</b>"
    )


@dp.callback_query(F.data.startswith("deny_"))
async def deny_payment(call: CallbackQuery):
    data = call.data.replace("deny_", "", 1)
    parts = data.split("_", 1)

    if len(parts) == 2:
        user_id = int(parts[0])
        order_id = parts[1]
    else:
        # На всякий случай поддержка старых кнопок
        order_id = data
        user_order_old = orders_by_id.get(order_id)
        if not user_order_old:
            await call.answer("Заказ не найден", show_alert=True)
            return
        user_id = user_order_old["buyer_id"]

    user_order = orders_by_id.get(order_id)

    if user_order and user_order.get("status") == "denied":
        await call.answer("Этот заказ уже отклонён", show_alert=True)
        return

    if user_order:
        user_order["status"] = "denied"

    await bot.send_message(
        user_id,
        f"❌ <b>Заказ #{order_id} отклонён</b>\n\n"
        "💬 Если возникли вопросы — напишите в поддержку."
    )

    await call.message.edit_caption(
        caption=(call.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>"
    )

@dp.callback_query(F.data == "back_start")
async def back_start(call: CallbackQuery):
    await call.message.edit_text(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬",
        reply_markup=main_menu()
    )

async def main():
    keep_alive()
    start_auto_ping()
    print("Iris Store bot started ✅")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
