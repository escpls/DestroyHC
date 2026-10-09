import json

import logging

import os

from datetime import datetime, timedelta, timezone

from html import escape

from telegram import (

    Update,

    InlineKeyboardButton,

    InlineKeyboardMarkup,

    ChatPermissions,

)

from telegram.constants import ParseMode, ChatMemberStatus

from telegram.helpers import mention_html

from telegram.ext import (

    Application,

    MessageHandler,

    CallbackQueryHandler,

    ContextTypes,

    filters,

)

# ============================================================

# НАСТРОЙКИ

# ============================================================

MAIN_CHAT_ID = -1002578170764

ADMIN_CHAT_ID = -1004363437805

BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()

OWNER_ID = int(OWNER_ID_RAW) if OWNER_ID_RAW.isdigit() else 0

DATA_FILE = "data.json"

# ============================================================

# ЛОГИ

# ============================================================

logging.basicConfig(

    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",

    level=logging.INFO,

)

logger = logging.getLogger(__name__)

# ============================================================

# ДАННЫЕ

# ============================================================

DEFAULT_DATA = {

    "complaint_number": 0,

    "blocked_reports": [],

    "warnings": {},

    "punishments": {},

    "complaints": {},

    "users": {},

    "admins": [],

    "admin_chats": {},

}

def load_data():

    if not os.path.exists(DATA_FILE):

        data = DEFAULT_DATA.copy()

        with open(DATA_FILE, "w", encoding="utf-8") as file:

            json.dump(

                data,

                file,

                ensure_ascii=False,

                indent=2,

            )

        return data

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as file:

            data = json.load(file)

        for key, value in DEFAULT_DATA.items():

            if key not in data:

                if isinstance(value, dict):

                    data[key] = {}

                elif isinstance(value, list):

                    data[key] = []

                else:

                    data[key] = value

        return data

    except Exception as e:

        logger.error(f"Ошибка загрузки data.json: {e}")

        return DEFAULT_DATA.copy()

data = load_data()

def save_data():

    try:

        with open(DATA_FILE, "w", encoding="utf-8") as file:

            json.dump(

                data,

                file,

                ensure_ascii=False,

                indent=2,

            )

    except Exception as e:

        logger.error(f"Ошибка сохранения data.json: {e}")

# ============================================================

# ПОЛЬЗОВАТЕЛИ

# ============================================================

def user_name(user):

    if not user:

        return "Пользователь"

    if user.full_name:

        return user.full_name

    if user.username:

        return f"@{user.username}"

    return f"ID {user.id}"

def remember_user(user):

    if not user:

        return

    data["users"][str(user.id)] = {

        "id": user.id,

        "name": user_name(user),

        "username": user.username,

    }

def profile_link(user_id, name):

    """

    Надёжная кликабельная ссылка на профиль Telegram.

    Работает даже если у пользователя нет @username.

    """

    try:

        user_id = int(user_id)

    except (TypeError, ValueError):

        return escape(str(name or "Пользователь"))

    return mention_html(

        user_id,

        str(name or "Пользователь"),

    )

def mention_user(user):

    if not user:

        return "Пользователь"

    remember_user(user)

    return mention_html(

        user.id,

        user_name(user),

    )

def saved_user_link(

    user_id,

    name=None,

    username=None,

):

    try:

        user_id = int(user_id)

    except (TypeError, ValueError):

        return escape(

            str(

                name

                or username

                or "Пользователь"

            )

        )

    saved = data["users"].get(str(user_id))

    if saved:

        display_name = (

            saved.get("name")

            or saved.get("username")

            or name

            or f"ID {user_id}"

        )

    else:

        display_name = (

            name

            or username

            or f"ID {user_id}"

        )

    return mention_html(

        user_id,

        display_name,

    )

def find_user_by_username(username):

    username = username.lower().lstrip("@")

    for user_id, info in data["users"].items():

        saved_username = info.get("username")

        if saved_username:

            if saved_username.lower() == username:

                return int(user_id), info

    return None, None

# ============================================================

# ССЫЛКА НА СООБЩЕНИЕ

# ============================================================

def message_link(chat_id, message_id):

    chat_id_string = str(chat_id)

    if chat_id_string.startswith("-100"):

        internal_id = chat_id_string[4:]

        return (

            f"https://t.me/c/{internal_id}/"

            f"{message_id}"

        )

    return None

# ============================================================

# ПРОВЕРКА АДМИНА

# ============================================================

async def is_admin(update, context):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    if not chat or chat.id not in (MAIN_CHAT_ID, ADMIN_CHAT_ID):
        return False

    # Если сообщение отправлено от имени чата, проверяем именно ID этого чата.
    sender_chat = getattr(message, "sender_chat", None) if message else None
    if sender_chat:
        if str(sender_chat.id) in {str(admin_id) for admin_id in data.get("admins", [])}:
            return True
        # Сообщение от имени чата не должно получать права по ID личного аккаунта.
        return False

    if not user:
        return False
    if OWNER_ID and user.id == OWNER_ID:
        return True
    return str(user.id) in {str(admin_id) for admin_id in data.get("admins", [])}


async def deny_if_not_admin(update, context):

    if await is_admin(update, context):

        return False

    message = update.effective_message

    if message:

        await message.reply_text("❌ Доступ запрещен!")

    return True


def is_owner(user):

    return bool(user and OWNER_ID and user.id == OWNER_ID)


async def grant_admin_command(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or chat.id not in (MAIN_CHAT_ID, ADMIN_CHAT_ID):
        return
    if not is_owner(user):
        await message.reply_text("❌ Доступ запрещен!")
        return

    target_message = message.reply_to_message
    if not target_message:
        await message.reply_text(
            "📍 Используйте /выдатьадмина ответом на сообщение пользователя или чата."
        )
        return

    # Telegram send-as: сохраняем sender_chat, а не личный аккаунт автора.
    target_chat = getattr(target_message, "sender_chat", None)
    target_user = None if target_chat else target_message.from_user
    target_id = target_chat.id if target_chat else (target_user.id if target_user else None)
    if target_id is None:
        await message.reply_text("❌ Не удалось определить пользователя или чат.")
        return

    if target_user and target_user.is_bot:
        await message.reply_text("❌ Нельзя выдать права самому боту.")
        return
    if target_user and OWNER_ID and target_user.id == OWNER_ID:
        await message.reply_text("ℹ️ Владелец уже имеет полный доступ.")
        return

    admins = {str(admin_id) for admin_id in data.get("admins", [])}
    if str(target_id) in admins:
        await message.reply_text("ℹ️ У этого пользователя или чата уже есть права администратора.")
        return

    data.setdefault("admins", []).append(target_id)
    if target_chat:
        data.setdefault("admin_chats", {})[str(target_id)] = {
            "id": target_id,
            "title": target_chat.title or f"Чат {target_id}",
            "type": target_chat.type,
        }
        target_label = escape(target_chat.title or f"Чат {target_id}")
    else:
        remember_user(target_user)
        target_label = mention_user(target_user)

    save_data()
    await message.reply_text(
        f"✅ Права администратора выданы: {target_label}.",
        parse_mode=ParseMode.HTML,
    )


async def remove_admin_command(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or chat.id not in (MAIN_CHAT_ID, ADMIN_CHAT_ID):
        return
    if not is_owner(user):
        await message.reply_text("❌ Доступ запрещен!")
        return

    target_message = message.reply_to_message
    if not target_message:
        await message.reply_text(
            "📍 Используйте /снятьадмина ответом на сообщение пользователя или чата."
        )
        return

    target_chat = getattr(target_message, "sender_chat", None)
    target_user = None if target_chat else target_message.from_user
    target_id = target_chat.id if target_chat else (target_user.id if target_user else None)
    if target_id is None:
        await message.reply_text("❌ Не удалось определить пользователя или чат.")
        return
    if target_user and OWNER_ID and target_user.id == OWNER_ID:
        await message.reply_text("❌ Нельзя снять права у владельца бота.")
        return

    admins = {str(admin_id) for admin_id in data.get("admins", [])}
    if str(target_id) not in admins:
        await message.reply_text("ℹ️ У этого пользователя или чата нет прав администратора.")
        return

    data["admins"] = [
        admin_id for admin_id in data.get("admins", [])
        if str(admin_id) != str(target_id)
    ]
    data.setdefault("admin_chats", {}).pop(str(target_id), None)
    save_data()

    if target_chat:
        target_label = escape(target_chat.title or f"Чат {target_id}")
    elif target_user:
        target_label = mention_user(target_user)
    else:
        target_label = escape(f"ID {target_id}")

    await message.reply_text(
        f"✅ Права администратора сняты: {target_label}.",
        parse_mode=ParseMode.HTML,
    )


async def admin_list_command(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or chat.id not in (MAIN_CHAT_ID, ADMIN_CHAT_ID):
        return
    if not is_owner(user):
        await message.reply_text("❌ Доступ запрещен!")
        return

    admin_ids = sorted({int(admin_id) for admin_id in data.get("admins", [])}, key=int)
    if not admin_ids:
        await message.reply_text("ℹ️ Назначенных администраторов нет.")
        return

    lines = []
    saved_chats = data.get("admin_chats", {})
    for admin_id in admin_ids:
        chat_info = saved_chats.get(str(admin_id))
        if chat_info:
            lines.append(f"🛡️ {escape(chat_info.get('title') or f'Чат {admin_id}')}")
        else:
            lines.append(f"🛡️ {saved_user_link(admin_id)}")

    await message.reply_text(
        "👮 <b>Список администраторов:</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


async def is_main_chat_admin(

    context,

    user_id,

):

    try:

        member = await context.bot.get_chat_member(

            MAIN_CHAT_ID,

            user_id,

        )

        return member.status in (

            ChatMemberStatus.ADMINISTRATOR,

            ChatMemberStatus.OWNER,

        )

    except Exception:

        return False

# ============================================================

# ЗАПРЕТ НА ПОДАЧУ ЖАЛОБ

# ============================================================

def reports_are_blocked(user_id):

    blocked = data.get(

        "blocked_reports",

        [],

    )

    return str(user_id) in {

        str(x) for x in blocked

    }

# ============================================================

# ПОЛЬЗОВАТЕЛЬ ИЗ REPLY

# ============================================================

def get_target_from_reply(update):

    message = update.effective_message

    if not message:

        return None

    if not message.reply_to_message:

        return None

    return message.reply_to_message.from_user

# ============================================================

# КЛАВИАТУРА ЖАЛОБЫ

# ============================================================

def complaint_keyboard(

    complaint_id,

    initial=True,

):

    complaint = data["complaints"].get(

        str(complaint_id)

    )

    if not complaint:

        return InlineKeyboardMarkup([])

    keyboard = []

    action = complaint.get("action")

    if action == "warning":

        keyboard.append([

            InlineKeyboardButton(

                "🔄 Снять предупреждение",

                callback_data=(

                    f"remove_warning:{complaint_id}"

                ),

            )

        ])

    elif action == "mute":

        keyboard.append([

            InlineKeyboardButton(

                "🔊 Снять мут",

                callback_data=(

                    f"unmute:{complaint_id}"

                ),

            )

        ])

    elif action == "ban":

        keyboard.append([

            InlineKeyboardButton(

                "🔓 Снять блокировку",

                callback_data=(

                    f"unban:{complaint_id}"

                ),

            )

        ])

    else:

        keyboard.append([

            InlineKeyboardButton(

                "⚠️ Выдать предупреждение",

                callback_data=(

                    f"warn:{complaint_id}"

                ),

            )

        ])

        keyboard.append([

            InlineKeyboardButton(

                "🔇 Выдать мут",

                callback_data=(

                    f"mute:{complaint_id}"

                ),

            )

        ])

        keyboard.append([

            InlineKeyboardButton(

                "⛔ Заблокировать",

                callback_data=(

                    f"ban:{complaint_id}"

                ),

            )

        ])

    if complaint.get("message_link"):

        keyboard.append([

            InlineKeyboardButton(

                "🔗 Открыть сообщение",

                url=complaint["message_link"],

            )

        ])

    # Назад показываем только во внутренних меню.

    if not initial:

        keyboard.append([

            InlineKeyboardButton(

                "◀️ Назад",

                callback_data=(

                    f"back:{complaint_id}"

                ),

            )

        ])

    return InlineKeyboardMarkup(keyboard)

# ============================================================

# ТЕКСТ ЖАЛОБЫ

# ============================================================

def complaint_text(complaint_id):

    complaint = data["complaints"].get(

        str(complaint_id)

    )

    if not complaint:

        return "❌ Жалоба не найдена."

    offender = saved_user_link(

        complaint["target_id"],

        complaint.get("target_name"),

        complaint.get("target_username"),

    )

    reporter = saved_user_link(

        complaint["reporter_id"],

        complaint.get("reporter_name"),

        complaint.get("reporter_username"),

    )

    text = (

        f"🚨 <b>НОВАЯ ЖАЛОБА №{complaint_id}</b>\n\n"

        f"👤 Нарушитель: {offender}\n"

        f"👮 Отправитель: {reporter}\n"

    )

    action = complaint.get("action")

    if action == "warning":

        count = complaint.get(

            "warning_count",

            0,

        )

        text += (

            f"\n📌 Статус: "

            f"⚠️ Предупреждение {count}/3"

        )

        if complaint.get("auto_mute"):

            text += (

                "\n🔇 Автоматический мут: 1 день"

                "\n🔄 Предупреждения аннулированы"

            )

    elif action == "mute":

        duration = complaint.get(

            "mute_duration_name",

            "неизвестный срок",

        )

        text += (

            f"\n📌 Статус: "

            f"🔇 Мут на {escape(duration)}"

        )

    elif action == "ban":

        text += (

            "\n📌 Статус: "

            "⛔️ Пользователь заблокирован"

        )

    elif action == "unmute":

        text += (

            "\n📌 Статус: 🔊 Мут снят"

        )

    elif action == "unban":

        text += (

            "\n📌 Статус: 🔓 Блокировка снята"

        )

    else:

        text += (

            "\n📌 Статус: "

            "<b>На рассмотрении</b>"

        )

    return text

# ============================================================

# ЖАЛОБА

# ============================================================

async def handle_complaint(

    update,

    context,

):

    message = update.effective_message

    chat = update.effective_chat

    reporter = update.effective_user

    if not message or not reporter:

        return

    if chat.id != MAIN_CHAT_ID:

        return

    text = message.text or ""

    if not text.lower().startswith("#жалоба"):

        return

    remember_user(reporter)

    save_data()

    # ВАЖНО:

    # запрещаем жаловаться именно человеку,

    # которому установлен /зж.

    if reports_are_blocked(reporter.id):

        await message.reply_text(

            f"🚫 {mention_user(reporter)}, "

            f"вам запрещено подавать жалобы!",

            parse_mode=ParseMode.HTML,

        )

        return

    if not message.reply_to_message:

        await message.reply_text(

            "⚠️ Чтобы подать жалобу, "

            "ответьте на сообщение пользователя "

            "и напишите #жалоба."

        )

        return

    target_message = message.reply_to_message

    target = target_message.from_user

    if not target:

        await message.reply_text(

            "❌ Не удалось определить пользователя."

        )

        return

    remember_user(target)

    # Нельзя жаловаться на самого бота.

    try:

        bot_user = await context.bot.get_me()

        if target.id == bot_user.id:

            await message.reply_text(

                "⚠️ На бота нельзя подать жалобу."

            )

            return

    except Exception as e:

        logger.error(

            f"Ошибка получения данных бота: {e}"

        )

    # Нельзя жаловаться на себя.

    if target.id == reporter.id:

        await message.reply_text(

            "⚠️ Нельзя подать жалобу "

            "на самого себя."

        )

        return

    # Нельзя жаловаться на администрацию.

    if await is_main_chat_admin(

        context,

        target.id,

    ):

        await message.reply_text(

            "⚠️ На Администрацию нельзя "

            "подать жалобу."

        )

        return

    # Номер жалобы.

    data["complaint_number"] += 1

    complaint_id = data["complaint_number"]

    link = message_link(

        MAIN_CHAT_ID,

        target_message.message_id,

    )

    data["complaints"][

        str(complaint_id)

    ] = {

        "target_id": target.id,

        "target_name": user_name(target),

        "target_username": target.username,

        "reporter_id": reporter.id,

        "reporter_name": user_name(reporter),

        "reporter_username": reporter.username,

        "original_message_id": (

            target_message.message_id

        ),

        "message_link": link,

        "action": None,

        "warning_count": 0,

        "auto_mute": False,

        "mute_duration_name": None,

        "admin_message_id": None,

    }

    save_data()

    # Копируем исходное сообщение в админ-чат.

    try:

        await context.bot.copy_message(

            chat_id=ADMIN_CHAT_ID,

            from_chat_id=MAIN_CHAT_ID,

            message_id=target_message.message_id,

        )

    except Exception as e:

        logger.error(

            f"Не удалось скопировать сообщение: {e}"

        )

    # Отправляем карточку жалобы.

    try:

        admin_message = (

            await context.bot.send_message(

                chat_id=ADMIN_CHAT_ID,

                text=complaint_text(

                    complaint_id

                ),

                parse_mode=ParseMode.HTML,

                reply_markup=complaint_keyboard(

                    complaint_id,

                    initial=True,

                ),

                disable_web_page_preview=True,

            )

        )

        data["complaints"][

            str(complaint_id)

        ]["admin_message_id"] = (

            admin_message.message_id

        )

        save_data()

    except Exception as e:

        logger.error(

            f"Ошибка отправки карточки жалобы: {e}"

        )

    # Уведомление отправителю.

    await message.reply_text(

        f"🚨 {mention_user(reporter)}, "

        f"жалоба отправлена на рассмотрение Администрации!",

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# ПРЕДУПРЕЖДЕНИЯ

# ============================================================

async def give_warning(

    user_id,

    context,

):

    user_id = int(user_id)

    old_count = int(

        data["warnings"].get(

            str(user_id),

            0,

        )

    )

    count = old_count + 1

    remember_user_from_saved_id(user_id)

    # Третье предупреждение.

    if count >= 3:

        data["warnings"][str(user_id)] = 0

        until_date = (

            datetime.now(timezone.utc)

            + timedelta(days=1)

        )

        try:

            await context.bot.restrict_chat_member(

                chat_id=MAIN_CHAT_ID,

                user_id=user_id,

                permissions=ChatPermissions(

                    can_send_messages=False

                ),

                until_date=until_date,

            )

        except Exception as e:

            logger.error(

                f"Ошибка автоматического мута: {e}"

            )

        data["punishments"][

            str(user_id)

        ] = {

            "type": "mute",

            "duration": "1 день",

            "until": until_date.isoformat(),

        }

        save_data()

        user_link = saved_user_link(

            user_id

        )

        await context.bot.send_message(

            chat_id=MAIN_CHAT_ID,

            text=(

                f"⚠️ <b>{user_link}, "

                f"вам выдано предупреждение.</b>\n\n"

                f"📊 Предупреждений: 3/3\n\n"

                f"🔇 <b>За получение 3-х предупреждений "

                f"вы получили автоматический мут "

                f"на 1 день.</b>"

            ),

            parse_mode=ParseMode.HTML,

        )

        return 3, True

    data["warnings"][str(user_id)] = count

    save_data()

    user_link = saved_user_link(

        user_id

    )

    await context.bot.send_message(

        chat_id=MAIN_CHAT_ID,

        text=(

            f"<b>⚠️ {user_link}, "

            f"вам выдано предупреждение!</b>\n\n"

            f"📊 Предупреждений: {count}/3"

        ),

        parse_mode=ParseMode.HTML,

    )

    return count, False

def remember_user_from_saved_id(user_id):

    user_id = int(user_id)

    if str(user_id) not in data["users"]:

        data["users"][

            str(user_id)

        ] = {

            "id": user_id,

            "name": f"ID {user_id}",

            "username": None,

        }

# ============================================================

# МУТ

# ============================================================

MUTE_DURATIONS = {

    "10m": (

        "10 минут",

        timedelta(minutes=10),

    ),

    "30m": (

        "30 минут",

        timedelta(minutes=30),

    ),

    "1h": (

        "1 час",

        timedelta(hours=1),

    ),

    "3h": (

        "3 часа",

        timedelta(hours=3),

    ),

    "12h": (

        "12 часов",

        timedelta(hours=12),

    ),

    "1d": (

        "1 день",

        timedelta(days=1),

    ),

    "3d": (

        "3 дня",

        timedelta(days=3),

    ),

    "7d": (

        "7 дней",

        timedelta(days=7),

    ),

}

def mute_keyboard(complaint_id):

    keyboard = []

    for key, value in MUTE_DURATIONS.items():

        title = value[0]

        keyboard.append([

            InlineKeyboardButton(

                title,

                callback_data=(

                    f"mutetime:{key}:{complaint_id}"

                ),

            )

        ])

    keyboard.append([

        InlineKeyboardButton(

            "◀️ Назад",

            callback_data=(

                f"back:{complaint_id}"

            ),

        )

    ])

    return InlineKeyboardMarkup(

        keyboard

    )

async def give_mute(

    user_id,

    duration_key,

    context,

):

    if duration_key not in MUTE_DURATIONS:

        return False

    title, delta = MUTE_DURATIONS[

        duration_key

    ]

    until_date = (

        datetime.now(timezone.utc)

        + delta

    )

    try:

        await context.bot.restrict_chat_member(

            chat_id=MAIN_CHAT_ID,

            user_id=int(user_id),

            permissions=ChatPermissions(

                can_send_messages=False

            ),

            until_date=until_date,

        )

    except Exception as e:

        logger.error(

            f"Ошибка выдачи мута: {e}"

        )

        return False

    data["punishments"][

        str(user_id)

    ] = {

        "type": "mute",

        "duration": title,

        "until": until_date.isoformat(),

    }

    save_data()

    await context.bot.send_message(

        chat_id=MAIN_CHAT_ID,

        text=(

            f"🔇 <b>Участнику "

            f"{saved_user_link(user_id)} "

            f"выдан мут на {escape(title)}</b>!"

        ),

        parse_mode=ParseMode.HTML,

    )

    return True

async def remove_mute(

    user_id,

    context,

):

    try:

        await context.bot.restrict_chat_member(

            chat_id=MAIN_CHAT_ID,

            user_id=int(user_id),

            permissions=ChatPermissions(

                can_send_messages=True,

                can_send_audios=True,

                can_send_documents=True,

                can_send_photos=True,

                can_send_videos=True,

                can_send_video_notes=True,

                can_send_voice_notes=True,

                can_send_polls=True,

                can_send_other_messages=True,

                can_add_web_page_previews=True,

            ),

        )

    except Exception as e:

        logger.error(

            f"Ошибка снятия мута: {e}"

        )

        return False

    data["punishments"].pop(

        str(user_id),

        None,

    )

    save_data()

    await context.bot.send_message(

        chat_id=MAIN_CHAT_ID,

        text=(

            f"🔊 <b>С участника "

            f"{saved_user_link(user_id)} "

            f"снят мут!</b>"

        ),

        parse_mode=ParseMode.HTML,

    )

    return True

# ============================================================

# БЛОКИРОВКА

# ============================================================

async def give_ban(

    user_id,

    context,

):

    try:

        await context.bot.ban_chat_member(

            chat_id=MAIN_CHAT_ID,

            user_id=int(user_id),

        )

    except Exception as e:

        logger.error(

            f"Ошибка блокировки: {e}"

        )

        return False

    data["punishments"][

        str(user_id)

    ] = {

        "type": "ban",

    }

    save_data()

    await context.bot.send_message(

        chat_id=MAIN_CHAT_ID,

        text=(

            f"⛔️ <b>Участник "

            f"{saved_user_link(user_id)} "

            f"заблокирован!</b>"

        ),

        parse_mode=ParseMode.HTML,

    )

    return True

async def remove_ban(

    user_id,

    context,

):

    try:

        await context.bot.unban_chat_member(

            chat_id=MAIN_CHAT_ID,

            user_id=int(user_id),

            only_if_banned=True,

        )

    except Exception as e:

        logger.error(

            f"Ошибка снятия блокировки: {e}"

        )

        return False

    data["punishments"].pop(

        str(user_id),

        None,

    )

    save_data()

    await context.bot.send_message(

        chat_id=MAIN_CHAT_ID,

        text=(

            f"🔓 <b>С участника "

            f"{saved_user_link(user_id)}, "

            f"снята блокировка!</b>"

        ),

        parse_mode=ParseMode.HTML,

    )

    return True

# ============================================================

# CALLBACK-КНОПКИ

# ============================================================

async def callback_handler(

    update,

    context,

):

    query = update.callback_query

    if not query:

        return

    await query.answer()

    if not query.message:

        return

    if query.message.chat_id != ADMIN_CHAT_ID:

        return

    if await deny_if_not_admin(update, context):

        return

    parts = query.data.split(":")

    action = parts[0]

    # ========================================================

    # ВЫДАТЬ ПРЕДУПРЕЖДЕНИЕ

    # ========================================================

    if action == "warn":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        complaint = data["complaints"].get(

            str(complaint_id)

        )

        if not complaint:

            return

        count, auto_mute = await give_warning(

            complaint["target_id"],

            context,

        )

        complaint["action"] = "warning"

        complaint["warning_count"] = count

        complaint["auto_mute"] = auto_mute

        if auto_mute:

            complaint["status"] = (

                "Автоматический мут на 1 день"

            )

        else:

            complaint["status"] = (

                f"Предупреждение {count}/3"

            )

        save_data()

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=False,

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # СНЯТЬ ПРЕДУПРЕЖДЕНИЕ

    # ========================================================

    if action == "remove_warning":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        complaint = data["complaints"].get(

            str(complaint_id)

        )

        if not complaint:

            return

        target_id = complaint[

            "target_id"

        ]

        data["warnings"][

            str(target_id)

        ] = 0

        complaint["action"] = None

        complaint["warning_count"] = 0

        complaint["auto_mute"] = False

        complaint["status"] = (

            "Предупреждение снято"

        )

        save_data()

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=True,

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # ОТКРЫТЬ ВЫБОР МУТА

    # ========================================================

    if action == "mute":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        if complaint_id not in data["complaints"]:

            return

        await query.message.edit_text(

            complaint_text(

                complaint_id

            )

            + "\n\n"

            + "🔇 <b>Выберите длительность мута:</b>",

            parse_mode=ParseMode.HTML,

            reply_markup=mute_keyboard(

                complaint_id

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # ВЫДАТЬ МУТ

    # ========================================================

    if action == "mutetime":

        if len(parts) < 3:

            return

        duration_key = parts[1]

        complaint_id = parts[2]

        complaint = data["complaints"].get(

            str(complaint_id)

        )

        if not complaint:

            return

        success = await give_mute(

            complaint["target_id"],

            duration_key,

            context,

        )

        if not success:

            await query.message.reply_text(

                "❌ Не удалось выдать мут."

            )

            return

        duration_name = (

            MUTE_DURATIONS[

                duration_key

            ][0]

        )

        complaint["action"] = "mute"

        complaint["mute_duration_name"] = (

            duration_name

        )

        complaint["status"] = (

            f"Мут на {duration_name}"

        )

        save_data()

        # Здесь initial=True:

        # Кнопки "Назад" больше нет.

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=True,

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # СНЯТЬ МУТ

    # ========================================================

    if action == "unmute":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        complaint = data["complaints"].get(

            str(complaint_id)

        )

        if not complaint:

            return

        success = await remove_mute(

            complaint["target_id"],

            context,

        )

        if not success:

            await query.message.reply_text(

                "❌ Не удалось снять мут."

            )

            return

        complaint["action"] = "unmute"

        complaint["status"] = (

            "Мут снят"

        )

        save_data()

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=True,

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # ЗАБЛОКИРОВАТЬ

    # ========================================================

    if action == "ban":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        complaint = data["complaints"].get(

            str(complaint_id)

        )

        if not complaint:

            return

        success = await give_ban(

            complaint["target_id"],

            context,

        )

        if not success:

            await query.message.reply_text(

                "❌ Не удалось заблокировать участника."

            )

            return

        complaint["action"] = "ban"

        complaint["status"] = (

            "Участник заблокирован"

        )

        save_data()

        # После блокировки "Назад" нет.

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=True,

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # СНЯТЬ БЛОКИРОВКУ

    # ========================================================

    if action == "unban":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        complaint = data["complaints"].get(

            str(complaint_id)

        )

        if not complaint:

            return

        success = await remove_ban(

            complaint["target_id"],

            context,

        )

        if not success:

            await query.message.reply_text(

                "❌ Не удалось снять блокировку."

            )

            return

        complaint["action"] = "unban"

        complaint["status"] = (

            "Блокировка снята"

        )

        save_data()

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=True,

            ),

            disable_web_page_preview=True,

        )

        return

    # ========================================================

    # НАЗАД

    # ========================================================

    if action == "back":

        if len(parts) < 2:

            return

        complaint_id = parts[1]

        if complaint_id not in data["complaints"]:

            return

        await query.message.edit_text(

            complaint_text(

                complaint_id

            ),

            parse_mode=ParseMode.HTML,

            reply_markup=complaint_keyboard(

                complaint_id,

                initial=True,

            ),

            disable_web_page_preview=True,

        )

        return

# ============================================================

# /ПОМОЩЬ

# ============================================================

async def help_command(

    update,

    context,

):

    if update.effective_chat.id not in (MAIN_CHAT_ID, ADMIN_CHAT_ID):

        return

    if await deny_if_not_admin(update, context):

        return

    text = """🛠 **ПАМЯТКА ПО КОМАНДАМ**

⚠️ **ПРЕДУПРЕЖДЕНИЯ**

/преды — список предупреждений
/сп — снять предупреждения

🚫 **РАЗДЕЛ ЖАЛОБ**

/зж — запретить подачу жалоб
/рж — разрешить подачу жалоб
/запреты — список участников с запретом на #жалоба

🔨 **НАКАЗАНИЯ**

/наказания — активные наказания участников
/сн — снять наказание

❗ Команды доступны только владельцу и назначенным администраторам.
При отсутствии доступа бот ответит: ❌ Доступ запрещен!"""

    await update.message.reply_text(

        text

    )

# ============================================================

# /ПРЕДЫ

# ============================================================

async def warnings_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    lines = []

    for user_id, count in data[

        "warnings"

    ].items():

        count = int(count)

        if count > 0:

            lines.append(

                f"👤 {saved_user_link(user_id)} "

                f"— {count}/3"

            )

    if not lines:

        await update.message.reply_text(

            "ℹ️ Активных предупреждений нет."

        )

        return

    await update.message.reply_text(

        "⚠️ <b>Предупреждения участников:</b>\n\n"

        + "\n".join(lines),

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# /СП

# ============================================================

async def remove_warnings_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    target = get_target_from_reply(update)

    if target:

        remember_user(target)

        user_id = target.id

    else:

        text = (

            update.effective_message.text

            or ""

        )

        parts = text.split()

        if len(parts) < 2:

            await update.message.reply_text(

                "📍 **Используйте `/сп` ответом "

                "на сообщение пользователя "

                "или `/сп @username`.**",

                parse_mode=ParseMode.MARKDOWN

            )

            return

        username = parts[1]

        if not username.startswith("@"):

            await update.message.reply_text(

                "📍 Укажите @username."

            )

            return

        user_id, _ = find_user_by_username(

            username

        )

        if not user_id:

            await update.message.reply_text(

                "❌ Пользователь не найден."

            )

            return

    data["warnings"][

        str(user_id)

    ] = 0

    save_data()

    await update.message.reply_text(

        f"✅ <b>Предупреждения с участника "

        f"{saved_user_link(user_id)} "

        f"сняты.</b>",

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# /ЗЖ

# ============================================================

async def block_reports_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    target = get_target_from_reply(update)

    if not target:

        await update.message.reply_text(

            "📍 **Используйте `/зж` ответом "

            "на сообщение пользователя.**",

            parse_mode=ParseMode.MARKDOWN

        )

        return

    remember_user(target)

    if target.is_bot:

        await update.message.reply_text(

            "❗️ Нельзя установить запрет "

            "для бота."

        )

        return

    blocked_ids = {

        str(x)

        for x in data["blocked_reports"]

    }

    if str(target.id) not in blocked_ids:

        data["blocked_reports"].append(

            target.id

        )

    save_data()

    await update.message.reply_text(

        f"🚫 <b>Для {mention_user(target)} "

        f"включён запрет на подачу жалоб!</b>",

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# /РЖ

# ============================================================

async def unblock_reports_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    target = get_target_from_reply(update)

    if target:

        remember_user(target)

        user_id = target.id

    else:

        text = (

            update.effective_message.text

            or ""

        )

        parts = text.split()

        if len(parts) < 2:

            await update.message.reply_text(

                "📍 **Используйте `/рж` ответом "

                "на сообщение или `/рж @username`.**",

                parse_mode=ParseMode.MARKDOWN

            )

            return

        username = parts[1]

        if not username.startswith("@"):

            await update.message.reply_text(

                "📍 Укажите @username."

            )

            return

        user_id, _ = find_user_by_username(

            username

        )

        if not user_id:

            await update.message.reply_text(

                "❌ Пользователь не найден."

            )

            return

    data["blocked_reports"] = [

        x

        for x in data["blocked_reports"]

        if str(x) != str(user_id)

    ]

    save_data()

    await update.message.reply_text(

        f"✅ <b>Для {saved_user_link(user_id)} "

        f"снят запрет на подачу жалоб!</b>",

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# /ЗАПРЕТЫ

# ============================================================

async def blocked_reports_list_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    blocked = data.get(

        "blocked_reports",

        [],

    )

    if not blocked:

        await update.message.reply_text(

            "ℹ️ Пользователей с запретом "

            "на жалобы нет."

        )

        return

    lines = []

    for user_id in blocked:

        lines.append(

            f"👤 {saved_user_link(user_id)}"

        )

    await update.message.reply_text(

        "ℹ️ <b>Список участников запрещенным подавать жалобы:</b>\n\n"

        + "\n".join(lines),

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# /НАКАЗАНИЯ

# ============================================================

async def punishments_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    punishments = data.get(

        "punishments",

        {},

    )

    if not punishments:

        await update.message.reply_text(

            "ℹ️ Активных наказаний нет."

        )

        return

    lines = []

    for user_id, punishment in punishments.items():

        punishment_type = punishment.get(

            "type"

        )

        if punishment_type == "mute":

            duration = punishment.get(

                "duration",

                "неизвестно",

            )

            lines.append(

                f"🔇 {saved_user_link(user_id)} "

                f"— мут ({escape(duration)})"

            )

        elif punishment_type == "ban":

            lines.append(

                f"🔨 {saved_user_link(user_id)} "

                f"— блокировка"

            )

    if not lines:

        await update.message.reply_text(

            "ℹ️ Активных наказаний нет."

        )

        return

    await update.message.reply_text(

        "⛔️ <b>Активные наказания участников:</b>\n\n"

        + "\n".join(lines),

        parse_mode=ParseMode.HTML,

    )

# ============================================================

# /СН

# ============================================================

async def remove_punishment_command(

    update,

    context,

):

    if update.effective_chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    if await deny_if_not_admin(update, context):

        return

    target = get_target_from_reply(update)

    if target:

        remember_user(target)

        user_id = target.id

    else:

        text = (

            update.effective_message.text

            or ""

        )

        parts = text.split()

        if len(parts) < 2:

            await update.message.reply_text(

                "📍 **Используйте `/сн` ответом "

                "на сообщение или `/сн @username`.**",

                parse_mode=ParseMode.MARKDOWN

            )

            return

        username = parts[1]

        if not username.startswith("@"):

            await update.message.reply_text(

                "📍 Укажите @username."

            )

            return

        user_id, _ = find_user_by_username(

            username

        )

        if not user_id:

            await update.message.reply_text(

                "❌ Пользователь не найден."

            )

            return

    punishment = data[

        "punishments"

    ].get(

        str(user_id)

    )

    if not punishment:

        await update.message.reply_text(

            f"ℹ️ У пользователя "

            f"{saved_user_link(user_id)} "

            f"нет активных наказаний.",

            parse_mode=ParseMode.HTML,

        )

        return

    punishment_type = punishment.get(

        "type"

    )

    if punishment_type == "mute":

        success = await remove_mute(

            user_id,

            context,

        )

    elif punishment_type == "ban":

        success = await remove_ban(

            user_id,

            context,

        )

    else:

        success = False

    if not success:

        await update.message.reply_text(

            "❌ Не удалось снять наказание."

        )

# ============================================================

# ЗАПОМИНАЕМ ПОЛЬЗОВАТЕЛЕЙ

# ============================================================

async def remember_message_users(

    update,

    context,

):

    message = update.effective_message

    if not message:

        return

    chat = update.effective_chat

    if not chat:

        return

    if chat.id not in (

        MAIN_CHAT_ID,

        ADMIN_CHAT_ID,

    ):

        return

    changed = False

    users = []

    if message.from_user:

        users.append(

            message.from_user

        )

    if (

        message.reply_to_message

        and message.reply_to_message.from_user

    ):

        users.append(

            message.reply_to_message.from_user

        )

    for user in users:

        new_info = {

            "id": user.id,

            "name": user_name(user),

            "username": user.username,

        }

        old_info = data["users"].get(

            str(user.id)

        )

        if old_info != new_info:

            data["users"][

                str(user.id)

            ] = new_info

            changed = True

    if changed:

        save_data()

# ============================================================

# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ

# ============================================================

def register_handlers(application):

    # ========================================================

    # ЖАЛОБЫ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.TEXT

            & filters.Regex(

                r"(?i)^#жалоба"

            ),

            handle_complaint,

        ),

        group=0,

    )

    # ========================================================

    # КНОПКИ ЖАЛОБ

    # ========================================================

    application.add_handler(

        CallbackQueryHandler(

            callback_handler,

            pattern=(

                r"^(warn|remove_warning|"

                r"mute|mutetime|unmute|"

                r"ban|unban|back):"

            ),

        ),

        group=0,

    )

    # ========================================================

    # /ПОМОЩЬ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/помощь(?:@\w+)?$"

            ),

            help_command,

        ),

        group=0,

    )

    # ========================================================

    # /ПРЕДЫ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/преды(?:@\w+)?$"

            ),

            warnings_command,

        ),

        group=0,

    )

    # ========================================================

    # /СП

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/сп(?:@\w+)?(?:\s+.*)?$"

            ),

            remove_warnings_command,

        ),

        group=0,

    )

    # ========================================================

    # /ЗЖ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/зж(?:@\w+)?$"

            ),

            block_reports_command,

        ),

        group=0,

    )

    # ========================================================

    # /РЖ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/рж(?:@\w+)?(?:\s+.*)?$"

            ),

            unblock_reports_command,

        ),

        group=0,

    )

    # ========================================================

    # /ЗАПРЕТЫ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/запреты(?:@\w+)?$"

            ),

            blocked_reports_list_command,

        ),

        group=0,

    )

    # ========================================================

    # /НАКАЗАНИЯ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/наказания(?:@\w+)?$"

            ),

            punishments_command,

        ),

        group=0,

    )

    # ========================================================

    # /СН

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(

                r"^/сн(?:@\w+)?(?:\s+.*)?$"

            ),

            remove_punishment_command,

        ),

        group=0,

    )

    # ========================================================

    # УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ (ТОЛЬКО ВЛАДЕЛЕЦ)

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.Regex(r"^/выдатьадмина(?:@\w+)?$"),

            grant_admin_command,

        ),

        group=0,

    )

    application.add_handler(

        MessageHandler(

            filters.Regex(r"^/снятьадмина(?:@\w+)?$"),

            remove_admin_command,

        ),

        group=0,

    )

    application.add_handler(

        MessageHandler(

            filters.Regex(r"^/списокадминов(?:@\w+)?$"),

            admin_list_command,

        ),

        group=0,

    )

    # ========================================================

    # ЗАПОМИНАНИЕ ПОЛЬЗОВАТЕЛЕЙ

    # ========================================================

    application.add_handler(

        MessageHandler(

            filters.ALL,

            remember_message_users,

        ),

        group=1,

    )

# ============================================================

# ЗАПУСК

# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(

            "Не найдена переменная окружения BOT_TOKEN."

        )

    application = (

        Application.builder()

        .token(BOT_TOKEN)

        .build()

    )

    register_handlers(

        application

    )

    logger.info(

        "DESTROY HELPER CHAT WORK"

    )

    application.run_polling(

        allowed_updates=Update.ALL_TYPES

    )

if __name__ == "__main__":

    main()
