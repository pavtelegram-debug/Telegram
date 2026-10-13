import os
import re
import sqlite3
import secrets
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB = "bot/data.sqlite3"

def database():
    os.makedirs("bot", exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        frozen INTEGER DEFAULT 0,
        stars INTEGER DEFAULT 0,
        premium TEXT DEFAULT '',
        label TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS numbers(
        number TEXT PRIMARY KEY,
        owner INTEGER DEFAULT NULL,
        code TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS punishments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        reason TEXT,
        until TEXT DEFAULT '',
        admin_id INTEGER,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        item TEXT,
        recipient TEXT DEFAULT '',
        status TEXT DEFAULT 'Новая',
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action TEXT,
        target TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Создаём демонстрационный пул номеров, если он пуст.
    if con.execute("SELECT COUNT(*) FROM numbers").fetchone()[0] == 0:
        for i in range(100):
            number = "+7" + "".join(
                str(secrets.randbelow(10)) for _ in range(10)
            )
            con.execute(
                "INSERT OR IGNORE INTO numbers(number) VALUES(?)",
                (number,)
            )
    con.commit()
    return con

def is_admin(uid):
    return uid in ADMIN_IDS

def main_menu(uid):
    rows = [
        [("📱 Получить номер", "number")],
        [("🖼 NFT-юзернейм", "nft_user"),
         ("💎 NFT-номер", "nft_number")],
        [("📋 Мои данные", "mydata"),
         ("❓ Помощь", "help")],
    ]
    if is_admin(uid):
        rows.append([("🔐 Админ-панель", "admin")])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=action)
         for label, action in row]
        for row in rows
    ])

def admin_menu():
    rows = [
        [("🔎 Найти пользователя", "find"),
         ("⚖️ Наказания", "punish")],
        [("🏷 Метки", "labels"),
         ("🔒 Блокировка", "freeze")],
        [("⭐ Stars / Premium", "credits"),
         ("🖼 NFT-заявки", "requests")],
        [("📱 Каталог номеров", "catalog"),
         ("📊 Статистика", "stats")],
        [("📜 Журнал действий", "logs"),
         ("🏠 Главное меню", "home")]
    ]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=action)
         for label, action in row]
        for row in rows
    ])

def register_user(user):
    with database() as con:
        con.execute("""
        INSERT INTO users(id, username) VALUES(?, ?)
        ON CONFLICT(id) DO UPDATE SET username=excluded.username
        """, (user.id, user.username or ""))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    await update.message.reply_text(
        "🌑 FLOSTGRAM\n\n"
        "Твоё пространство виртуальных сервисов.\n"
        "Выбери нужный раздел:",
        reply_markup=main_menu(user.id)
    )

async def show(update, text, markup=None):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    register_user(user)
    action = q.data

    with database() as con:
        row = con.execute(
            "SELECT frozen FROM users WHERE id=?", (user.id,)
        ).fetchone()

    if row and row["frozen"] and not is_admin(user.id):
        await show(update, "🔒 Доступ к FlostGram ограничен.")
        return

    if action == "home":
        await show(update, "🌑 FLOSTGRAM\n\nГлавное меню:",
                   main_menu(user.id))
    elif action == "help":
        await show(update,
                   "❓ ПОМОЩЬ\n\nВыбирай раздел кнопками меню.",
                   main_menu(user.id))
    elif action == "number":
        with database() as con:
            item = con.execute("""
                SELECT number FROM numbers
                WHERE owner IS NULL LIMIT 1
            """).fetchone()
            if not item:
                await show(update, "Свободных тестовых номеров пока нет.",
                           main_menu(user.id))
                return
            number = item["number"]
            # Код существует только внутри тестового проекта.
            code = "".join(str(secrets.randbelow(10)) for _ in range(6))
            con.execute("""
                UPDATE numbers SET owner=?, code=?
                WHERE number=? AND owner IS NULL
            """, (user.id, code, number))
            if con.total_changes == 0:
                await show(update, "Не удалось закрепить номер. Попробуй ещё раз.",
                           main_menu(user.id))
                return
        await show(
            update,
            f"📱 ТВОЙ ТЕСТОВЫЙ НОМЕР\n\n"
            f"`{number}`\n\n"
            f"🧪 Тестовый код: `{code}`\n\n"
            "Номер и код действуют внутри FlostGram. "
            "Это не реальный телефонный номер и не SMS от Telegram.",
            main_menu(user.id)
        )
    elif action == "mydata":
        with database() as con:
            nums = con.execute(
                "SELECT number FROM numbers WHERE owner=?",
                (user.id,)
            ).fetchall()
        text = "📋 МОИ ДАННЫЕ\n\n"
        text += "\n".join(x["number"] for x in nums) if nums else "У тебя пока нет номеров."
        await show(update, text, main_menu(user.id))
    elif action in ("nft_user", "nft_number"):
        context.user_data["request_kind"] = action
        await show(update,
                   "Введи желаемый username или номер.\n"
                   "Например: mvdkit\n\n"
                   "Это создаст заявку, а не передаст реальный NFT.",
                   InlineKeyboardMarkup([[
                       InlineKeyboardButton("⬅️ Назад", callback_data="home")
                   ]]))
    elif action == "admin":
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        await show(update, "🔐 FLOSTGRAM ADMIN\n\nВыбери инструмент:",
                   admin_menu())
    elif action in ("find", "punish", "labels", "freeze", "credits"):
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        context.user_data["admin_action"] = action
        prompts = {
            "find": "🔎 Отправь ID или @username пользователя.",
            "punish": "⚖️ Отправь: ID тип причина\n"
                      "Типы: warn, mute, tempban, ban, unban.",
            "labels": "🏷 Отправь: ID метка\nНапример: 123456 VIP",
            "freeze": "🔒 Отправь: ID block или unblock",
            "credits": "⭐ Отправь: ID количество_демо_Stars"
        }
        await show(update, prompts[action])
    elif action == "requests":
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        with database() as con:
            items = con.execute("""
                SELECT id, user_id, kind, item, recipient, status
                FROM requests ORDER BY id DESC LIMIT 20
            """).fetchall()
        text = "🖼 ПОСЛЕДНИЕ ЗАЯВКИ\n\n"
        text += "\n".join(
            f"#{x['id']} · {x['user_id']} · {x['kind']} · "
            f"{x['item']} · {x['status']}" for x in items
        ) if items else "Заявок пока нет."
        await show(update, text, admin_menu())
    elif action == "catalog":
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        with database() as con:
            total = con.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
            free = con.execute(
                "SELECT COUNT(*) FROM numbers WHERE owner IS NULL"
            ).fetchone()[0]
        await show(update,
                   f"📱 КАТАЛОГ\nВсего тестовых номеров: {total}\nСвободно: {free}",
                   admin_menu())
    elif action == "stats":
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        with database() as con:
            users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            nums = con.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
            reqs = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        await show(update,
                   f"📊 СТАТИСТИКА\nПользователей: {users}\n"
                   f"Тестовых номеров: {nums}\nЗаявок: {reqs}",
                   admin_menu())
    elif action == "logs":
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        with database() as con:
            logs = con.execute(
                "SELECT admin_id, action, target, created "
                "FROM logs ORDER BY id DESC LIMIT 15"
            ).fetchall()
        text = "📜 ЖУРНАЛ\n\n" + (
            "\n".join(
                f"{x['created']} · {x['admin_id']} · "
                f"{x['action']} · {x['target']}" for x in logs
            ) if logs else "Записей пока нет."
        )
        await show(update, text, admin_menu())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if not user or not msg or not msg.text:
        return
    register_user(user)
    value = msg.text.strip()

    kind = context.user_data.pop("request_kind", None)
    if kind:
        if not value or len(value) > 100:
            await msg.reply_text("Неверный формат.")
            return
        with database() as con:
            con.execute("""
                INSERT INTO requests(user_id, kind, item)
                VALUES(?, ?, ?)
            """, (user.id, kind, value.lstrip("@")))
        await msg.reply_text(
            "✅ Заявка сохранена.\n"
            "Передача реального коллекционного актива не выполняется автоматически.",
            reply_markup=main_menu(user.id)
        )
        return

    action = context.user_data.pop("admin_action", None)
    if not action:
        return
    if not is_admin(user.id):
        await msg.reply_text("⛔ Нет доступа.")
        return

    parts = value.split(maxsplit=2)
    try:
        target = int(parts[0].lstrip("@"))
    except (ValueError, IndexError):
        await msg.reply_text(
            "Для этой операции укажи числовой ID. "
            "Поиск по @username доступен среди известных боту пользователей."
        )
        return

    with database() as con:
        exists = con.execute(
            "SELECT id, username, frozen, label, stars FROM users WHERE id=?",
            (target,)
        ).fetchone()
        if action == "find":
            if not exists:
                await msg.reply_text("Пользователь не найден в базе.")
                return
            await msg.reply_text(
                f"🔎 Пользователь\nID: {exists['id']}\n"
                f"Username: @{exists['username'] or 'не указан'}\n"
                f"Блокировка: {bool(exists['frozen'])}\n"
                f"Метка: {exists['label'] or 'нет'}\n"
                f"Демо Stars: {exists['stars']}"
            )
        elif not exists:
            await msg.reply_text("Пользователь не найден. Он должен запустить бота.")
        elif action == "labels" and len(parts) >= 2:
            con.execute("UPDATE users SET label=? WHERE id=?",
                        (parts[1], target))
            con.execute("INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                        (user.id, "label", str(target)))
            await msg.reply_text("✅ Метка обновлена.")
        elif action == "freeze" and len(parts) >= 2:
            state = parts[1].lower()
            if state not in ("block", "unblock"):
                await msg.reply_text("Укажи block или unblock.")
                return
            con.execute("UPDATE users SET frozen=? WHERE id=?",
                        (int(state == "block"), target))
            con.execute("INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                        (user.id, state, str(target)))
            await msg.reply_text("✅ Внутренняя блокировка обновлена.")
        elif action == "credits" and len(parts) >= 2:
            try:
                amount = int(parts[1])
                if amount < 0:
                    raise ValueError
            except ValueError:
                await msg.reply_text("Укажи неотрицательное число.")
                return
            con.execute("UPDATE users SET stars=? WHERE id=?",
                        (amount, target))
            con.execute("INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                        (user.id, "demo_stars", f"{target}:{amount}"))
            await msg.reply_text("✅ Демо-баланс сохранён. Это не настоящие Stars.")
        elif action == "punish" and len(parts) >= 3:
            allowed = ("warn", "mute", "tempban", "ban", "unban")
            if parts[1].lower() not in allowed:
                await msg.reply_text("Тип: warn, mute, tempban, ban, unban.")
                return
            con.execute("""
                INSERT INTO punishments(user_id, kind, reason, admin_id)
                VALUES(?, ?, ?, ?)
            """, (target, parts[1].lower(), parts[2], user.id))
            if parts[1].lower() in ("ban", "tempban"):
                con.execute("UPDATE users SET frozen=1 WHERE id=?", (target,))
            elif parts[1].lower() == "unban":
                con.execute("UPDATE users SET frozen=0 WHERE id=?", (target,))
            con.execute("INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                        (user.id, "punishment:" + parts[1], str(target)))
            await msg.reply_text("✅ Запись наказания сохранена.")
        else:
            await msg.reply_text("Не хватает данных. Открой нужный раздел заново.")

def main():
    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в GitHub Secrets")
    database().close()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
