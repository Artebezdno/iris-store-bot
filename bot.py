import os
import asyncio
import uuid
import time
import requests
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

# orders — текущий заказ пользователя
# orders_by_id — все заказы, чтобы кнопки Одобрить/Отклонить работали правильно,
# даже если пользователь уже выбрал новый пакет.
orders = {}
orders_by_id = {}
waiting_username = {}

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍬 Купить ириски", callback_data="buy_iris")],
        [
            InlineKeyboardButton(text="⭐ Отзывы", url=REVIEWS_LINK),
            InlineKeyboardButton(text="❓ FAQ", callback_data="faq")
        ]
    ])

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в <b>Iris Store</b>!\n\n"
        "Здесь вы можете быстро купить ириски 🍬",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "faq")
async def faq(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_start")]
    ])

    await call.message.edit_text(
    "❓ <b>FAQ / Частые вопросы</b>\n\n"
    "💳 <b>Как купить?</b>\n"
    "— Выберите пакет, укажите username, оплатите и отправьте чек.\n\n"
    "⏳ <b>Сколько ждать?</b>\n"
    "— Обычно 5–30 минут.\n\n"
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
        "🍬 <b>Куда выдать ириски?</b>\n\n"
        "Отправьте username получателя, на которого нужно передать ириски.\n\n"
        "Пример:\n"
        "<code>@Artemwesh</code>\n\n"
        "⚠️ Укажите username внимательно."
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
    user_order["status"] = "waiting_payment"
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
        "✅ Скрин оплаты получен.\n"
        "⏳ Заказ отправлен на проверку.\n"
        "Ожидайте администратора."
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
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_{user_order['order_id']}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"deny_{user_order['order_id']}"
            )
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
    order_id = call.data.replace("approve_", "", 1)
    user_order = orders_by_id.get(order_id)

    if not user_order:
        await call.answer("Заказ не найден", show_alert=True)
        return

    if user_order.get("status") == "approved":
        await call.answer("Этот заказ уже одобрен", show_alert=True)
        return

    user_order["status"] = "approved"
    user_id = user_order["buyer_id"]

    await bot.send_message(
        user_id,
        "✅ <b>Оплата подтверждена!</b>\n\n"
        "Ваш заказ одобрен.\n"
        "Ожидайте выдачу ирисок 🍬"
    )

    await bot.send_message(
        CHANNEL_ID,
        f"✅ Покупатель получил <b>{user_order['item']}</b>\n\n"
        f"👤 Получатель: {user_order['receiver']}\n"
        f"🍬 Количество: {user_order['item']}\n"
        f"💎 Статус: успешно получено\n"
        f"🛍️ Спасибо за покупку в <b>Iris Store</b>"
    )

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>"
    )

@dp.callback_query(F.data.startswith("deny_"))
async def deny_payment(call: CallbackQuery):
    order_id = call.data.replace("deny_", "", 1)
    user_order = orders_by_id.get(order_id)

    if not user_order:
        await call.answer("Заказ не найден", show_alert=True)
        return

    if user_order.get("status") == "denied":
        await call.answer("Этот заказ уже отклонён", show_alert=True)
        return

    user_order["status"] = "denied"
    user_id = user_order["buyer_id"]

    await bot.send_message(
        user_id,
        "❌ <b>Оплата отклонена</b>\n\n"
        "Скрин не прошёл проверку.\n"
        "Вы можете отправить новый чек или выбрать новый пакет."
    )

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>"
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
