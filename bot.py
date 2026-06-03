import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7837011810"))

PAY_LINK = "https://example.com/pay"  # сюда потом вставишь ссылку на оплату

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
        "Здесь вы сможете быстро купить ириски 🍬\n"
        "Выберите нужный товар, оплатите и отправьте скрин оплаты.\n\n"
        "Нажмите кнопку ниже 👇",
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
        "После выбора бот выдаст ссылку на оплату.",
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

    orders[call.from_user.id] = {
        "username": call.from_user.username,
        "name": call.from_user.full_name,
        "item": item,
        "price": price
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=PAY_LINK)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_iris")]
    ])

    await call.message.edit_text(
        "🧾 <b>Ваш заказ создан</b>\n\n"
        f"🍬 Товар: <b>{item}</b>\n"
        f"💰 Сумма: <b>{price}</b>\n\n"
        "1️⃣ Нажмите кнопку <b>Оплатить</b>\n"
        "2️⃣ После оплаты отправьте сюда скрин\n"
        "3️⃣ Админ проверит оплату и выдаст чек на ириски",
        reply_markup=keyboard
    )

@dp.message(F.photo)
async def get_payment_photo(message: Message):
    user_order = orders.get(message.from_user.id)

    if not user_order:
        await message.answer("❌ Сначала нажмите «Купить ириски» и выберите пакет.")
        return

    username = f"@{user_order['username']}" if user_order["username"] else "нет username"

    await message.answer(
        "✅ Скрин оплаты получен.\n"
        "Ожидайте проверку админом."
    )

    caption = (
        "🧾 <b>Новая оплата</b>\n\n"
        f"👤 Имя: <b>{user_order['name']}</b>\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"💰 Сумма: <b>{user_order['price']}</b>\n\n"
        "📸 Скрин оплаты:"
    )

    await bot.send_photo(
        ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=caption
    )

@dp.callback_query(F.data == "back_start")
async def back_start(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 Купить ириски", callback_data="buy_iris")]
    ])

    await call.message.edit_text(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы сможете быстро купить ириски 🍬\n"
        "Выберите нужный товар, оплатите и отправьте скрин оплаты.",
        reply_markup=keyboard
    )

async def main():
    print("Iris Store bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
