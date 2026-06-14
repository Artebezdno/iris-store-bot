import os
import asyncio
import random
import time
import requests
from threading import Thread

from flask import Flask
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Environment на Render")

ADMIN_ID = int(os.getenv("ADMIN_ID", "7837011810"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@IrisStoreMarket")
REVIEWS_LINK = "https://t.me/IrisStoreMarket"
SUPPORT_USERNAME = "@Artemwesh"
SITE_URL = "https://iris-store-bot.onrender.com/"
CARD_NUMBER = "5355 2800 2289 5252"
BANK_NAME = "PUMB"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)

orders = {}
orders_by_id = {}

PACKAGES = {
    "🍬 10 ирисок — 10 грн": ("10 ирисок", "10 грн"),
    "🍬 25 ирисок — 25 грн": ("25 ирисок", "25 грн"),
    "🍬 50 ирисок — 45 грн": ("50 ирисок", "45 грн"),
    "🍬 100 ирисок — 85 грн": ("100 ирисок", "85 грн"),
    "🍬 250 ирисок — 210 грн": ("250 ирисок", "210 грн"),
    "🍬 500 ирисок — 400 грн": ("500 ирисок", "400 грн"),
    "🍬 1000 ирисок — 800 грн": ("1000 ирисок", "800 грн"),
    "🍬 2000 ирисок — 1550 грн": ("2000 ирисок", "1550 грн"),
}

@app.route("/")
def home():
    return "Iris Store bot is running ✅"

def keep_alive():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def auto_ping():
    while True:
        try:
            response = requests.get(SITE_URL, timeout=10)
            print(f"Ping OK: {response.status_code}")
        except Exception as e:
            print("Ping error:", e)
        time.sleep(240)

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍬 Купить ириски")],
            [KeyboardButton(text="⭐ Отзывы"), KeyboardButton(text="❓ FAQ")],
            [KeyboardButton(text="🛠 Поддержка")],
        ],
        resize_keyboard=True
    )

def packages_keyboard():
    rows = [[KeyboardButton(text=text)] for text in PACKAGES.keys()]
    rows.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def pay_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Я оплатил")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )

def get_value_from_caption(caption: str, label: str):
    for line in (caption or "").splitlines():
        if label in line:
            value = line.split(":", 1)[-1].strip()
            value = value.replace("<b>", "").replace("</b>", "")
            value = value.replace("<code>", "").replace("</code>", "")
            return value
    return "не указано"

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "⬅️ Назад")
async def back(message: Message):
    await message.answer("🏠 Главное меню", reply_markup=main_keyboard())

@dp.message(F.text == "🍬 Купить ириски")
async def buy(message: Message):
    await message.answer("🍬 <b>Выберите пакет ирисок:</b>", reply_markup=packages_keyboard())

@dp.message(F.text.in_(PACKAGES.keys()))
async def choose_package(message: Message):
    item, price = PACKAGES[message.text]
    order_id = str(random.randint(1000, 9999))
    order = {
        "order_id": order_id,
        "buyer_id": message.from_user.id,
        "buyer_name": message.from_user.full_name,
        "buyer_username": message.from_user.username,
        "item": item,
        "price": price,
        "receiver": None,
        "status": "waiting_username",
    }
    orders[message.from_user.id] = order
    orders_by_id[order_id] = order
    await message.answer(
        f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
        f"🍬 Товар: <b>{item}</b>\n"
        f"💸 Цена: <b>{price}</b>\n\n"
        "📩 Отправьте username получателя ирисок.\n"
        "Пример: <code>@username</code>"
    )

@dp.message(F.text == "⭐ Отзывы")
async def reviews(message: Message):
    await message.answer(f"⭐ Отзывы покупателей: {REVIEWS_LINK}", reply_markup=main_keyboard())

@dp.message(F.text == "❓ FAQ")
async def faq(message: Message):
    await message.answer(
        "❓ <b>FAQ</b>\n\n"
        "🛒 <b>Как купить?</b>\nВыберите пакет, укажите username, оплатите и отправьте чек.\n\n"
        "⏳ <b>Сколько ждать?</b>\nОбычно 5–30 минут.\n\n"
        "🎯 <b>Куда придут ириски?</b>\nНа указанный username.\n\n"
        "💸 <b>Можно ли сделать возврат?</b>\nДа, если заказ ещё не выполнен. После выдачи возврат невозможен.",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "🛠 Поддержка")
async def support(message: Message):
    await message.answer(
        "🛠 <b>Поддержка</b>\n\n"
        f"Пишите сюда: {SUPPORT_USERNAME}\n"
        "Укажите номер заказа и проблему.",
        reply_markup=main_keyboard()
    )

@dp.message(F.text.startswith("@"))
async def get_receiver(message: Message):
    user_order = orders.get(message.from_user.id)
    if not user_order or user_order.get("status") != "waiting_username":
        return

    user_order["receiver"] = message.text.strip()
    user_order["status"] = "waiting_payment"

    await message.answer(
        f"🧾 <b>Заказ #{user_order['order_id']}</b>\n\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"🎯 Получатель: <b>{user_order['receiver']}</b>\n"
        f"💸 Сумма: <b>{user_order['price']}</b>\n\n"
        "💳 <b>Реквизиты для оплаты:</b>\n"
        f"🏦 Банк: <b>{BANK_NAME}</b>\n"
        f"💳 Карта: <code>{CARD_NUMBER}</code>\n\n"
        "После оплаты нажмите кнопку ниже.",
        reply_markup=pay_keyboard()
    )

@dp.message(F.text == "✅ Я оплатил")
async def paid(message: Message):
    user_order = orders.get(message.from_user.id)
    if not user_order:
        await message.answer("❌ Сначала выберите пакет ирисок.")
        return
    if not user_order.get("receiver"):
        await message.answer("❌ Сначала укажите username получателя.")
        return
    if user_order.get("status") == "pending":
        await message.answer("⏳ Ваш чек уже находится на проверке.")
        return
    if user_order.get("status") == "approved":
        await message.answer("✅ Этот заказ уже одобрен. Чтобы купить ещё, выберите новый пакет.")
        return

    user_order["status"] = "waiting_photo"
    await message.answer("📸 <b>Отправьте чек оплаты фото/скриншотом</b>")

@dp.message(F.photo)
async def get_payment_photo(message: Message):
    user_order = orders.get(message.from_user.id)
    if not user_order:
        await message.answer("❌ Сначала выберите пакет ирисок.")
        return
    if user_order.get("status") == "pending":
        await message.answer("⏳ Ваш чек уже находится на проверке.")
        return
    if user_order.get("status") == "approved":
        await message.answer("✅ Этот заказ уже одобрен. Чтобы купить ещё, выберите новый пакет.")
        return

    user_order["status"] = "pending"
    buyer_username = f"@{user_order['buyer_username']}" if user_order["buyer_username"] else "нет username"

    await message.answer(
        f"🟡 <b>Заказ #{user_order['order_id']}</b>\n\n"
        "Чек отправлен на проверку.\n\n"
        "⏳ Заказ будет обработан в течение 24 часов 💛",
        reply_markup=main_keyboard()
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[ 
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{message.from_user.id}_{user_order['order_id']}"),
        InlineKeyboardButton(text="❌ Отказать", callback_data=f"deny_{message.from_user.id}_{user_order['order_id']}")
    ]])
    await bot.send_photo(ADMIN_ID, photo=message.photo[-1].file_id, caption=caption, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("approve_"))
async def approve_payment(call: CallbackQuery):
    data = call.data.replace("approve_", "", 1)
    user_id_text, order_id = data.split("_", 1)
    user_id = int(user_id_text)
    user_order = orders_by_id.get(order_id)

    if user_order:
        user_order["status"] = "approved"
        item = user_order["item"]
    else:
        item = get_value_from_caption(call.message.caption or "", "🍬 Товар")

    await bot.send_message(user_id, f"🎉 <b>Заказ #{order_id} выполнен!</b>\n\n🍬 Ириски успешно выданы 💜")
    try:
        await bot.send_message(
            CHANNEL_ID,
            f"✅ <b>Покупатель получил ириски</b>\n\n"
            f"🧾 <b>Номер заказа:</b> #{order_id}\n"
            f"🍬 <b>Количество:</b> {item}\n"
            "💎 <b>Статус:</b> успешно получено\n\n"
            "🛍️ Спасибо за покупку в <b>Iris Store</b>"
        )
    except Exception as e:
        print("Review post error:", e)

    await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ <b>ОДОБРЕНО</b>")
    await call.answer("Одобрено")

@dp.callback_query(F.data.startswith("deny_"))
async def deny_payment(call: CallbackQuery):
    data = call.data.replace("deny_", "", 1)
    user_id_text, order_id = data.split("_", 1)
    user_id = int(user_id_text)
    user_order = orders_by_id.get(order_id)
    if user_order:
        user_order["status"] = "denied"
    await bot.send_message(user_id, f"❌ <b>Заказ #{order_id} отклонён</b>\n\n💬 Поддержка: {SUPPORT_USERNAME}")
    await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>")
    await call.answer("Отклонено")

async def main():
    print("Iris Store bot started ✅")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    Thread(target=keep_alive, daemon=True).start()
    Thread(target=auto_ping, daemon=True).start()
    asyncio.run(main())
