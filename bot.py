import os
import asyncio
import uuid
import time
import re
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
        [InlineKeyboardButton(text="🍬 500 ирисок — 430 грн", callback_data="pack_500")],
        [InlineKeyboardButton(text="🍬 1000 ирисок — 850 грн", callback_data="pack_1000")],
        [InlineKeyboardButton(text="🍬 2000 ирисок — 1670 грн", callback_data="pack_2000")],
        [InlineKeyboardButton(text="🍬 5000 ирисок — 4150 грн", callback_data="pack_5000")],
        [InlineKeyboardButton(text="🍬 10000 ирисок — 8200 грн", callback_data="pack_10000")],
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
        "pack_500": ("500 ирисок", "430 грн"),
        "pack_1000": ("1000 ирисок", "850 грн"),
        "pack_2000": ("2000 ирисок", "1670 грн"),
        "pack_5000": ("5000 ирисок", "4150 грн"),
        "pack_10000": ("10000 ирисок", "8200 грн")
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

        "<blockquote>"
        f"🧾 <b>Заказ:</b> #{user_order['order_id']}\n"
        f"🍬 <b>Товар:</b> {user_order['item']}\n"
        f"👤 <b>Получатель:</b> {receiver}\n"
        f"💰 <b>К оплате:</b> {user_order['price']}"
        "</blockquote>\n\n"

        "🏦 <b>Реквизиты для перевода</b>\n\n"

        "<blockquote>"
        f"• <b>Банк:</b> {BANK_NAME}\n"
        f"• <b>Номер карты:</b> <code>{CARD_NUMBER}</code>\n"
        "• <b>Получатель:</b> Не указан"
        "</blockquote>\n\n"

        "🤖 <b>Что нужно сделать</b>\n\n"

        "<blockquote>"
        "1. Переведите точную сумму на карту выше\n"
        "2. Нажмите кнопку «✅ Я оплатил»\n"
        "3. Отправьте скриншот или фото чека"
        "</blockquote>\n\n"

        "⚠️ <b>Важно</b>\n\n"
        "• Проверьте <b>username</b> перед оплатой\n"
        "• После выдачи изменить получателя нельзя\n\n"
        "🔒 <b>Безопасная сделка</b>\n\n"
        "Все заказы проверяются\n"
        "вручную администратором\n\n"
        "⏳ <b>Проверка:</b> Обычно 5–30 минут 💛",
        reply_markup=keyboard
    )

@dp.message(F.text)
async def text_router(message: Message):
    text = (message.text or "").strip().upper()

    # Проверка заказа по номеру: #IRIS8791
    if re.match(r"^#?IRIS\d+$", text):
        order_number = text.replace("#", "").strip().upper()
        order = orders_by_id.get(order_number)

        if not order:
            await message.answer("❌ Заказ не найден")
            return

        status = order.get("status", "pending")

        if status == "viewed":
            status_text = (
                "👀 <b>Статус:</b>\n"
                "Заказ увиден администратором\n\n"
                "⏳ Ожидайте решение."
            )
        elif status == "approved":
            status_text = (
                "🟢 <b>Статус:</b>\n"
                "Успешно выполнен\n\n"
                "🍬 Ириски успешно выданы."
            )
        elif status == "denied":
            status_text = (
                "🔴 <b>Статус:</b>\n"
                "Отклонён\n\n"
                "💬 Если возникли вопросы — напишите в поддержку."
            )
        else:
            status_text = (
                "🟡 <b>Статус:</b>\n"
                "Ещё не просмотрен администратором\n\n"
                "⏳ Ожидайте проверки."
            )

        await message.answer(
            f"🧾 <b>Заказ:</b> <code>#{order_number}</code>\n\n{status_text}"
        )
        return

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
        "🚨 <b>НОВЫЙ ЗАКАЗ</b>\n\n"
        f"🧾 Заказ: <code>#{user_order['order_id']}</code>\n\n"
        f"👤 Покупатель: <b>{user_order['buyer_name']}</b>\n"
        f"🔗 Username: {buyer_username}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"🍬 Товар: <b>{user_order['item']}</b>\n"
        f"🎯 Выдать на: <b>{user_order['receiver']}</b>\n"
        f"💰 Сумма: <b>{user_order['price']}</b>\n\n"
        "📸 Чек оплаты:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👀 Заказ увиден",
                callback_data=f"view_{message.from_user.id}_{user_order['order_id']}"
            ),
            InlineKeyboardButton(
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



@dp.callback_query(F.data.startswith("view_"))
async def view_order(call: CallbackQuery):
    data = call.data.replace("view_", "", 1)
    parts = data.split("_", 1)

    if len(parts) != 2:
        await call.answer("Ошибка", show_alert=True)
        return

    user_id = int(parts[0])
    order_id = parts[1]

    user_order = orders_by_id.get(order_id)
    if not user_order:
        await call.answer("Заказ не найден", show_alert=True)
        return

    if user_order.get("status") == "viewed":
        await call.answer("Заказ уже отмечен как увиденный", show_alert=True)
        return

    user_order["status"] = "viewed"

    # Убираем кнопку «Заказ увиден», оставляем только Одобрить/Отказаться
    new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_{user_id}_{order_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отказаться",
                callback_data=f"deny_{user_id}_{order_id}"
            )
        ]
    ])

    caption = call.message.caption or ""
    if "👀 <b>ЗАКАЗ УВИДЕН</b>" not in caption:
        caption += "\n\n👀 <b>ЗАКАЗ УВИДЕН</b>"

    await call.message.edit_caption(
        caption=caption,
        reply_markup=new_keyboard
    )

    await call.answer("Заказ отмечен как увиденный ✅")


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
        receiver = get_value_from_caption(caption, "🎯 Выдать на")

    await bot.send_message(
        user_id,
        "🎉 <b>Ириски успешно выданы!</b>\n\n"
        "🍬 Ваш заказ выполнен.\n"
        "Спасибо за покупку в <b>Iris Store</b> 💛\n\n"
        "⭐ Не забудьте оставить отзыв"
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
        "❌ <b>Оплата отклонена</b>\n\n"
        "Скрин не прошёл проверку.\n"
        "Вы можете отправить новый чек или выбрать новый пакет."
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
