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

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

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
        time.sleep(240)  # каждые 4 минуты


dp = Dispatcher()
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
    print("Iris Store bot started ✅")
    await dp.start_polling(bot)

if __name__ == "__main__":
    Thread(target=keep_alive, daemon=True).start()
    Thread(target=auto_ping, daemon=True).start()
    asyncio.run(main())
