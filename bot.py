import os
import asyncio
import uuid
from threading import Thread

from flask import Flask
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7837011810"))

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

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

orders = {}

@dp.message(Command("start"))
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 Купить ириски", callback_data="buy_iris")]
    ])

    await message.answer(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬\n"
        "Выберите пакет, оплатите и отправьте скрин оплаты.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "buy_iris")
async def buy_iris(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="35 ирисок — 50 грн", callback_data="pack_35")],
        [InlineKeyboardButton(text="80 ирисок — 100 грн", callback_data="pack_80")],
        [InlineKeyboardButton(text="170 ирисок — 200 грн", callback_data="pack_170")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_start")]
    ])

    await call.message.edit_text(
        "🍬 <b>Выберите пакет ирисок:</b>\n\n"
        "После выбора бот покажет реквизиты для оплаты.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("pack_"))
async def choose_pack(call: CallbackQuery):
    packs = {
        "pack_35": ("35 ирисок", "50 грн"),
        "pack_80": ("80 ирисок", "100 грн"),
        "pack_170": ("170 ирисок", "200 грн")
    }

    item, price = packs[call.data]
    order_id = str(uuid.uuid4())[:13]

    orders[call.from_user.id] = {
        "username": call.from_user.username,
        "name": call.from_user.full_name,
        "item": item,
        "price": price,
        "order_id": order_id
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_iris")]
    ])

    username = call.from_user.username or "без username"

    await call.message.edit_text(
        "💳 <b>Оплата переводом на украинскую карту</b>\n\n"
        f"🧾 Заказ: <code>#{order_id}</code>\n"
        f"🍬 Товар: <b>{item}</b>\n"
        f"👤 Покупатель: @{username}\n"
        f"💰 К оплате: <b>{price}</b>\n\n"
        "🏦 <b>Реквизиты для перевода</b>\n\n"
        f"• Банк: <b>{BANK_NAME}</b>\n"
        f"• Номер карты: <code>{CARD_NUMBER}</code>\n"
        "• Получатель: <b>Не указан</b>\n\n"
        "❗ <b>Что нужно сделать</b>\n\n"
        "1. Переведите точную сумму на карту выше\n"
        "2. Нажмите кнопку «✅ Я оплатил»\n"
        "3. Отправьте скриншот или фото чека\n\n"
        "⏳ Проверка выполняется администратором вручную.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "paid")
async def paid(call: CallbackQuery):
    await call.message.answer(
        "📸 Теперь отправьте сюда скриншот или фото чека оплаты.\n\n"
        "После этого админ проверит оплату вручную."
    )

@dp.message(F.photo)
async def get_payment_photo(message: Message):
    user_order = orders.get(message.from_user.id)

    if not user_order:
        await message.answer("❌ Сначала выберите пакет ирисок.")
        return

    username = f"@{user_order['username']}" if user_order["username"] else "нет username"

    await message.answer(
        "✅ Скрин оплаты получен.\n"
        "Ожидайте проверку администратором."
    )

    caption = (
        "🧾 <b>Новая оплата</b>\n\n"
        f"🧾 Заказ: <code>#{user_order['order_id']}</code>\n"
        f"👤 Имя: <b>{user_order['name']}</b>\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"💰 Сумма: <b>{user_order['price']}</b>\n\n"
        "📸 Скрин оплаты:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"deny_{message.from_user.id}")
        ]
    ])

    await bot.send_photo(
        ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=caption,
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("approve_"))
async def approve_payment(call: CallbackQuery):
    user_id = int(call.data.split("_")[1])

    await bot.send_message(
        user_id,
        "✅ <b>Оплата подтверждена!</b>\n\n"
        "Ваш заказ одобрен.\n"
        "Ожидайте выдачу ирисок 🍬"
    )

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>"
    )

@dp.callback_query(F.data.startswith("deny_"))
async def deny_payment(call: CallbackQuery):
    user_id = int(call.data.split("_")[1])

    await bot.send_message(
        user_id,
        "❌ <b>Оплата отклонена</b>\n\n"
        "Скрин не прошёл проверку.\n"
        "Попробуйте отправить новый чек."
    )

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>"
    )

@dp.callback_query(F.data == "back_start")
async def back_start(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 Купить ириски", callback_data="buy_iris")]
    ])

    await call.message.edit_text(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬",
        reply_markup=keyboard
    )

async def main():
    keep_alive()
    print("Iris Store bot started ✅")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
