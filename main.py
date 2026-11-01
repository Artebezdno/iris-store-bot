import asyncio
import html
import logging
import os
import urllib.request

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.client.default import DefaultBotProperties


# ==========================================
# НАСТРОЙКИ
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 7837011810

CHANNEL_ID = "@zapillspost"

PING_URL = "https://iris-store-bot-eqkf.onrender.com/"

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в Environment Render")


# ==========================================
# ЗАПУСК БОТА
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# ==========================================
# КЛАВИАТУРЫ
# ==========================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="📩 Предложить пост"
            )
        ]
    ],
    resize_keyboard=True
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="❌ Отмена"
            )
        ]
    ],
    resize_keyboard=True
)


def admin_keyboard(proposal_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"approve:{proposal_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{proposal_id}"
                )
            ]
        ]
    )


# ==========================================
# СОСТОЯНИЯ
# ==========================================

class ProposalStates(StatesGroup):
    waiting_post = State()


class AdminStates(StatesGroup):
    waiting_reason = State()


# ==========================================
# ХРАНИЛИЩЕ ЗАЯВОК
# ==========================================

proposals = {}

proposal_counter = 0


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def get_author(user):
    name = html.escape(
        user.full_name or "Пользователь"
    )

    return (
        f'\n\n👤: '
        f'<a href="tg://user?id={user.id}">'
        f'{name}</a>'
    )


def get_author_text(user):
    name = html.escape(
        user.full_name or "Пользователь"
    )

    return (
        f'👤: <a href="tg://user?id={user.id}">'
        f'{name}</a>'
    )


def get_post_text(message):
    if message.text:
        return message.text

    if message.caption:
        return message.caption

    return ""


def is_supported_post(message):
    return bool(
        message.text
        or message.photo
        or message.video
    )


# ==========================================
# ПРИВЕТСТВИЕ
# ==========================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "👋 Привет!\n\n"
        "Добро пожаловать в предложку канала "
        "«Вся твоя жизнь здесь».\n\n"
        "Здесь ты можешь поделиться тем, "
        "что сейчас делаешь, своей историей, "
        "фото или видео.\n\n"
        "Нажми кнопку ниже, чтобы предложить пост.",
        reply_markup=main_keyboard
    )


# ==========================================
# НАЧАЛО ПРЕДЛОЖКИ
# ==========================================

@dp.message(F.text == "📩 Предложить пост")
async def start_proposal(
    message: Message,
    state: FSMContext
):

    await state.set_state(
        ProposalStates.waiting_post
    )

    await message.answer(
        "📩 Отправь свой пост следующим сообщением.\n\n"
        "Можно отправить:\n"
        "• Текст\n"
        "• Фото с подписью\n"
        "• Видео с подписью\n\n"
        "После отправки заявка попадёт "
        "администратору на проверку.",
        reply_markup=cancel_keyboard
    )


# ==========================================
# ОТМЕНА
# ==========================================

@dp.message(F.text == "❌ Отмена")
async def cancel_proposal(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "❌ Предложение поста отменено.",
        reply_markup=main_keyboard
    )


# ==========================================
# ПОЛУЧЕНИЕ ПОСТА
# ==========================================

@dp.message(ProposalStates.waiting_post)
async def receive_proposal(
    message: Message,
    state: FSMContext
):

    global proposal_counter

    if not is_supported_post(message):

        await message.answer(
            "⚠️ Можно отправить только текст, "
            "фото или видео.\n\n"
            "Попробуй ещё раз или нажми "
            "«❌ Отмена»."
        )

        return

    proposal_counter += 1

    proposal_id = proposal_counter

    user = message.from_user

    proposals[proposal_id] = {
        "user_id": user.id,
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "status": "pending",
        "author_name": user.full_name,
    }

    author = get_author_text(user)

    admin_caption = (
        f"📩 <b>Новая предложка #{proposal_id}</b>\n\n"
        f"Отправитель: {author}\n"
        f"ID: <code>{user.id}</code>\n\n"
        f"👇 <b>Предложенный пост:</b>\n"
        f"{html.escape(get_post_text(message))}"
    )

    keyboard = admin_keyboard(proposal_id)

    try:

        # Текстовый пост
        if message.text:

            await bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_caption,
                reply_markup=keyboard
            )

        # Фото
        elif message.photo:

            await bot.copy_message(
                chat_id=ADMIN_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                caption=admin_caption,
                reply_markup=keyboard
            )

        # Видео
        elif message.video:

            await bot.copy_message(
                chat_id=ADMIN_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                caption=admin_caption,
                reply_markup=keyboard
            )

        await message.answer(
            "✅ Твой пост отправлен администратору!\n\n"
            "После проверки ты получишь уведомление.",
            reply_markup=main_keyboard
        )

        await state.clear()

    except Exception as error:

        logging.exception(
            "Ошибка при отправке заявки администратору"
        )

        await message.answer(
            "⚠️ Не удалось отправить пост.\n"
            "Попробуй ещё раз немного позже."
        )


# ==========================================
# ПУБЛИКАЦИЯ ПОСТА В КАНАЛ
# ==========================================

async def publish_post(proposal_id: int):

    proposal = proposals.get(proposal_id)

    if not proposal:
        raise ValueError("Заявка не найдена")

    user_id = proposal["user_id"]

    chat_id = proposal["chat_id"]

    message_id = proposal["message_id"]

    user = await bot.get_chat(user_id)

    author = get_author(user)

    # Получаем исходное сообщение
    original = await bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=chat_id,
        message_id=message_id
    )

    try:

        # Текст
        if original.text:

            text = original.text

            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=html.escape(text) + author,
                parse_mode=ParseMode.HTML
            )

        # Фото
        elif original.photo:

            caption = (
                html.escape(original.caption or "")
                + author
            )

            await bot.copy_message(
                chat_id=CHANNEL_ID,
                from_chat_id=ADMIN_ID,
                message_id=original.message_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        # Видео
        elif original.video:

            caption = (
                html.escape(original.caption or "")
                + author
            )

            await bot.copy_message(
                chat_id=CHANNEL_ID,
                from_chat_id=ADMIN_ID,
                message_id=original.message_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        else:

            await bot.copy_message(
                chat_id=CHANNEL_ID,
                from_chat_id=ADMIN_ID,
                message_id=original.message_id
            )

    finally:

        # Удаляем временную пересылку из админ-чата
        try:

            await bot.delete_message(
                chat_id=ADMIN_ID,
                message_id=original.message_id
            )

        except Exception:

            pass


# ==========================================
# ПРИНЯТИЕ ПОСТА
# ==========================================

@dp.callback_query(F.data.startswith("approve:"))
async def approve_proposal(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ У тебя нет прав.",
            show_alert=True
        )

        return

    proposal_id = int(
        callback.data.split(":")[1]
    )

    proposal = proposals.get(proposal_id)

    if not proposal:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    if proposal["status"] != "pending":

        await callback.answer(
            "Эта заявка уже обработана.",
            show_alert=True
        )

        return

    try:

        await publish_post(proposal_id)

        proposal["status"] = "approved"

        await bot.send_message(
            chat_id=proposal["user_id"],
            text=(
                "✅ Твой пост принят "
                "и опубликован в канале!\n\n"
                "Спасибо за предложку ❤️"
            )
        )

        await callback.message.edit_reply_markup(
            reply_markup=None
        )

        await callback.answer(
            "Пост опубликован!"
        )

    except Exception as error:

        logging.exception(
            "Ошибка публикации"
        )

        await callback.answer(
            "Ошибка публикации. Проверь права бота.",
            show_alert=True
        )


# ==========================================
# ОТКЛОНЕНИЕ ПОСТА
# ==========================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_proposal(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ У тебя нет прав.",
            show_alert=True
        )

        return

    proposal_id = int(
        callback.data.split(":")[1]
    )

    proposal = proposals.get(proposal_id)

    if not proposal:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    if proposal["status"] != "pending":

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    proposal["status"] = "waiting_reason"

    await state.set_state(
        AdminStates.waiting_reason
    )

    await state.update_data(
        proposal_id=proposal_id
    )

    await callback.message.answer(
        f"✍️ Напиши причину отказа "
        f"для заявки #{proposal_id}.\n\n"
        f"Следующее сообщение будет отправлено автору."
    )

    await callback.answer()


# ==========================================
# ПРИЧИНА ОТКАЗА
# ==========================================

@dp.message(AdminStates.waiting_reason)
async def send_rejection_reason(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()

    proposal_id = data.get("proposal_id")

    proposal = proposals.get(proposal_id)

    if not proposal:

        await message.answer(
            "Заявка не найдена."
        )

        await state.clear()

        return

    reason = message.text or message.caption

    if not reason:

        await message.answer(
            "Напиши причину отказа текстом."
        )

        return

    try:

        await bot.send_message(
            chat_id=proposal["user_id"],
            text=(
                "❌ Твой пост отклонён.\n\n"
                f"Причина:\n{html.escape(reason)}"
            )
        )

        proposal["status"] = "rejected"

        await message.answer(
            "✅ Причина отказа отправлена автору."
        )

    except Exception as error:

        logging.exception(
            "Ошибка отправки отказа"
        )

        await message.answer(
            "Не удалось отправить отказ пользователю."
        )

    await state.clear()


# ==========================================
# АВТОПИНГ RENDER
# ==========================================

def ping_site():

    request = urllib.request.Request(
        PING_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.status


async def auto_ping():

    while True:

        try:

            status = await asyncio.to_thread(
                ping_site
            )

            logging.info(
                f"Автопинг: сайт ответил {status}"
            )

        except Exception as error:

            logging.warning(
                f"Сайт не отвечает: {error}"
            )

        # Повторная попытка через 5 минут
        await asyncio.sleep(300)


# ==========================================
# ЗАПУСК
# ==========================================

async def main():

    logging.info(
        "Бот предложки запускается..."
    )

    # Запускаем автопинг
    asyncio.create_task(
        auto_ping()
    )

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
