import os
import sqlite3
import logging
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB = "bot/data.sqlite3"

MAIN_MENU = [
    [KeyboardButton("📱 Получить номер")],
    [KeyboardButton("❓ Помощь"), KeyboardButton("ℹ️ Информация")]
]
ADMIN_MENU = [
    [KeyboardButton("🔎 Найти пользователя")],
    [KeyboardButton("🏷 Метки"), KeyboardButton("🔒 Блокировка")],
    [KeyboardButton("⭐ Stars / Premium"), KeyboardButton("🖼 NFT")],
    [KeyboardButton("📊 Статистика"), KeyboardButton("⬅️ Главное меню")]
]


def db():
    os.makedirs("bot", exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        frozen INTEGER DEFAULT 0,
        demo_stars INTEGER DEFAULT 0,
        demo_premium TEXT DEFAULT '',
        demo_nft TEXT DEFAULT '',
        label TEXT DEFAULT ''
    )""")
    return con


def save_user(user):
    if not user:
        return
    with db() as con:
        con.execute(
            """INSERT INTO users(user_id, username)
            VALUES(?, ?) ON CONFLICT(user_id)
            DO UPDATE SET username=excluded.username""",
            (user.id, user.username or "")
        )


def is_admin(uid):
    return uid in ADMIN_IDS


def keyboard(uid):
    if is_admin(uid):
        return ReplyKeyboardMarkup(
            MAIN_MENU + ADMIN_MENU, resize_keyboard=True
        )
    return ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    await update.message.reply_text(
        "🌑 Добро пожаловать в FlostGram Bot!\n\n"
        "Выбери действие в меню ниже.",
        reply_markup=keyboard(user.id)
    )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if not user or not msg or not msg.text:
        return

    save_user(user)
    text = msg.text.strip()

    with db() as con:
        row = con.execute(
            "SELECT frozen FROM users WHERE user_id=?", (user.id,)
        ).fetchone()

    if row and row[0] and not is_admin(user.id):
        await msg.reply_text("🔒 Доступ к этому боту ограничен.")
        return

    if text == "⬅️ Главное меню":
        await msg.reply_text("Главное меню:", reply_markup=keyboard(user.id))
    elif text == "📱 Получить номер":
        await msg.reply_text(
            "📱 Демонстрационный раздел номеров.\n\n"
            "Реальный номер и SMS-код здесь не выдаются. "
            "Для этого нужен подключённый легальный SMS-провайдер."
        )
    elif text == "❓ Помощь":
        await msg.reply_text(
            "Выбери действие кнопкой в меню.\n"
            "Для вопросов обратись к администратору."
        )
    elif text == "ℹ️ Информация":
        await msg.reply_text(
            "🌑 FlostGram Bot\n"
            "Бот с меню, метками и инструментами администратора."
        )
    elif text in (
        "🔎 Найти пользователя", "🏷 Метки", "🔒 Блокировка",
        "⭐ Stars / Premium", "🖼 NFT"
    ):
        if not is_admin(user.id):
            await msg.reply_text("⛔ Нет доступа.")
            return
        prompts = {
            "🔎 Найти пользователя":
                "Отправь числовой Telegram ID. Поиск по username "
                "работает только среди пользователей, уже известных боту.",
            "🏷 Метки":
                "Отправь ID и метку через пробел.\nПример: 123456 VIP",
            "🔒 Блокировка":
                "Отправь ID и действие: block или unblock.\n"
                "Пример: 123456 block",
            "⭐ Stars / Premium":
                "Демо-запись Stars: отправь ID и количество.\n"
                "Пример: 123456 1000\nЭто не настоящие Telegram Stars.",
            "🖼 NFT":
                "Демо-запись NFT: отправь ID и описание через пробел."
        }
        context.user_data["action"] = text
        await msg.reply_text(prompts[text])
    elif text == "📊 Статистика" and is_admin(user.id):
        with db() as con:
            total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            frozen = con.execute(
                "SELECT COUNT(*) FROM users WHERE frozen=1"
            ).fetchone()[0]
        await msg.reply_text(
            f"📊 Пользователей бота: {total}\n"
            f"🔒 Внутренне ограничено: {frozen}"
        )
    elif "action" in context.user_data and is_admin(user.id):
        action = context.user_data.pop("action")
        parts = text.split(maxsplit=1)
        try:
            target = int(parts[0])
        except (ValueError, IndexError):
            await msg.reply_text("Нужен числовой Telegram ID.")
            return

        with db() as con:
            exists = con.execute(
                "SELECT user_id, username, frozen, demo_stars, "
                "demo_premium, demo_nft, label FROM users WHERE user_id=?",
                (target,)
            ).fetchone()

            if action == "🔎 Найти пользователя":
                if exists:
                    await msg.reply_text(
                        f"ID: {exists[0]}\nUsername: @{exists[1] or 'нет'}\n"
                        f"Блокировка: {'да' if exists[2] else 'нет'}\n"
                        f"Демо Stars: {exists[3]}\n"
                        f"Демо Premium: {exists[4] or 'нет'}\n"
                        f"Демо NFT: {exists[5] or 'нет'}\n"
                        f"Метка: {exists[6] or 'нет'}"
                    )
                else:
                    await msg.reply_text(
                        "Пользователь не найден. Он должен сначала "
                        "запустить этого бота."
                    )
            elif not exists:
                await msg.reply_text(
                    "Пользователь пока не запускал бота."
                )
            elif action == "🏷 Метки" and len(parts) == 2:
                con.execute(
                    "UPDATE users SET label=? WHERE user_id=?",
                    (parts[1], target)
                )
                await msg.reply_text("✅ Метка сохранена.")
            elif action == "🔒 Блокировка" and len(parts) == 2:
                if parts[1].lower() not in ("block", "unblock"):
                    await msg.reply_text("Укажи block или unblock.")
                else:
                    con.execute(
                        "UPDATE users SET frozen=? WHERE user_id=?",
                        (int(parts[1].lower() == "block"), target)
                    )
                    await msg.reply_text("✅ Настройка бота обновлена.")
            elif action == "⭐ Stars / Premium" and len(parts) == 2:
                try:
                    amount = int(parts[1])
                    if amount < 0:
                        raise ValueError
                    con.execute(
                        "UPDATE users SET demo_stars=? WHERE user_id=?",
                        (amount, target)
                    )
                    await msg.reply_text(
                        "✅ Демо-баланс сохранён. Это не реальные Stars."
                    )
                except ValueError:
                    await msg.reply_text("Укажи неотрицательное число.")
            elif action == "🖼 NFT" and len(parts) == 2:
                con.execute(
                    "UPDATE users SET demo_nft=? WHERE user_id=?",
                    (parts[1], target)
                )
                await msg.reply_text("✅ Демо-запись NFT сохранена.")
            else:
                await msg.reply_text("Проверь формат сообщения.")


def main():
    if not TOKEN:
        raise RuntimeError("Не задан секрет BOT_TOKEN")
    db().close()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()


if __name__ == "__main__":
    main()
