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
waiting_username = {}

@dp.message(Command("start"))
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 Купить ириски", callback_data="buy_iris")]
    ])

    await message.answer(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬\n"
        "Выберите пакет, укажите username получателя и отправьте скрин оплаты.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "buy_iris")
async def buy_iris(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 50 ирисок — 45 грн", callback_data="pack_50")],
        [InlineKeyboardButton(text="🍬 100 ирисок — 85 грн", callback_data="pack_100")],
        [InlineKeyboardButton(text="🍬 500 ирисок — 400 грн", callback_data="pack_500")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_start")]
    ])

    await call.message.edit_text(
        "🍬 <b>Выберите пакет ирисок:</b>\n\n"
        "После выбора нужно будет указать username получателя.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("pack_"))
async def choose_pack(call: CallbackQuery):
    packs = {
        "pack_50": ("50 ирисок", "45 грн"),
        "pack_100": ("100 ирисок", "85 грн"),
        "pack_500": ("500 ирисок", "400 грн")
    }

    item, price = packs[call.data]
    order_id = str(uuid.uuid4())[:13]

    orders[call.from_user.id] = {
        "buyer_username": call.from_user.username,
        "buyer_name": call.from_user.full_name,
        "item": item,
        "price": price,
        "order_id": order_id,
        "receiver": None
    }

    waiting_username[call.from_user.id] = True

    await call.message.edit_text(
        "🍬 <b>Куда выдать ириски?</b>\n\n"
        "Пожалуйста, отправьте username получателя, на которого нужно передать ириски.\n\n"
        "Пример:\n"
        "<code>@Artemwesh</code>\n\n"
        "⚠️ Укажите username внимательно.\n"
        "После оплаты ириски будут выданы именно на этот аккаунт."
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

    if len(receiver) < 5:
        await message.answer("❌ Username слишком короткий. Пример: @Artemwesh")
        return

    user_order["receiver"] = receiver
    waiting_username[message.from_user.id] = False

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_iris")]
    ])

    await message.answer(
        "💳 <b>Оплата переводом на украинскую карту</b>\n\n"
        f"🧾 Заказ: <code>#{user_order['order_id']}</code>\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"👤 Получатель: <b>{receiver}</b>\n"
        f"💰 К оплате: <b>{user_order['price']}</b>\n\n"
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

@dp.message(F.text)
async def wrong_username(message: Message):
    if waiting_username.get(message.from_user.id):
        await message.answer(
            "❌ Отправьте username в правильном формате.\n\n"
            "Пример:\n"
            "<code>@Artemwesh</code>"
        )

@dp.callback_query(F.data == "paid")
async def paid(call: CallbackQuery):
    user_order = orders.get(call.from_user.id)

    if not user_order:
        await call.message.answer("❌ Сначала выберите пакет ирисок.")
        return

    if not user_order.get("receiver"):
        await call.message.answer("❌ Сначала укажите username получателя.")
        return

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

    if not user_order.get("receiver"):
        await message.answer("❌ Сначала отправьте username получателя.")
        return

    buyer_username = f"@{user_order['buyer_username']}" if user_order["buyer_username"] else "нет username"

    await message.answer(
        "✅ Скрин оплаты получен.\n"
        "Ожидайте проверку администратором."
    )

    caption = (
        "🧾 <b>Новая оплата</b>\n\n"
        f"🧾 Заказ: <code>#{user_order['order_id']}</code>\n"
        f"👤 Покупатель: <b>{user_order['buyer_name']}</b>\n"
        f"🔗 Username покупателя: {buyer_username}\n"
        f"🆔 ID покупателя: <code>{message.from_user.id}</code>\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"🎯 Выдать на: <b>{user_order['receiver']}</b>\n"
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
