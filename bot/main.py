import os
import sqlite3
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB = "bot/data.sqlite3"


def init_db():
    os.makedirs("bot", exist_ok=True)
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                user_id INTEGER PRIMARY KEY,
                label TEXT NOT NULL,
                reason TEXT DEFAULT ''
            )
        """)


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать в FlostGram Bot!\n"
        "Команды: /help"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — запуск\n"
        "/help — помощь\n"
        "/admin — панель администратора\n"
        "/label ID метка — добавить внутреннюю метку\n"
        "/unlabel ID — удалить метку\n"
        "/stats — статистика меток"
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("Нет доступа.")
        return
    await update.message.reply_text(
        "Панель администратора\n"
        "/label ID метка — добавить метку\n"
        "/unlabel ID — удалить метку\n"
        "/stats — статистика"
    )


async def label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /label ID метка")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    mark = " ".join(context.args[1:])[:100]
    with sqlite3.connect(DB) as con:
        con.execute(
            "INSERT OR REPLACE INTO labels(user_id,label) VALUES(?,?)",
            (target_id, mark),
        )
    await update.message.reply_text(
        f"Для ID {target_id} сохранена внутренняя метка: {mark}"
    )


async def unlabel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /unlabel ID")
        return
    target_id = int(context.args[0])
    with sqlite3.connect(DB) as con:
        con.execute("DELETE FROM labels WHERE user_id=?", (target_id,))
    await update.message.reply_text("Метка удалена, если существовала.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    with sqlite3.connect(DB) as con:
        count = con.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    await update.message.reply_text(f"Всего внутренних меток: {count}")


def main():
    if not TOKEN:
        raise RuntimeError("Не задан секрет BOT_TOKEN")
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("label", label))
    app.add_handler(CommandHandler("unlabel", unlabel))
    app.add_handler(CommandHandler("stats", stats))
    app.run_polling()


if __name__ == "__main__":
    main()
