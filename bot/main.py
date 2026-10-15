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
    for x in os.getenv("ADMIN_IDS", "8868524848").split(",")
    if x.strip().isdigit()
}
DB = os.getenv("TELEFOST_DB_PATH", "bot/data.sqlite3")

def database():
    os.makedirs("bot", exist_ok=True)
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        phone TEXT DEFAULT '',
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
            # Telefost demo numbers use the +79XXXXXXXXX shape.
            number = "+79" + "".join(
                str(secrets.randbelow(10)) for _ in range(9)
            )
            con.execute(
                "INSERT OR IGNORE INTO numbers(number) VALUES(?)",
                (number,)
            )
    # Миграция старой базы без потери данных.
    columns = {row["name"] for row in con.execute("PRAGMA table_info(users)")}
    if "phone" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    # Migrate only unassigned legacy placeholders; never rewrite a number already issued.
    free_rows = con.execute(
        "SELECT number FROM numbers WHERE owner IS NULL"
    ).fetchall()
    for row in free_rows:
        if not re.fullmatch(r"\+79\d{9}", row["number"]):
            replacement = None
            for _ in range(20):
                candidate = "+79" + "".join(str(secrets.randbelow(10)) for _ in range(9))
                if not con.execute("SELECT 1 FROM numbers WHERE number=?", (candidate,)).fetchone():
                    replacement = candidate
                    break
            if replacement:
                con.execute("DELETE FROM numbers WHERE number=? AND owner IS NULL", (row["number"],))
                con.execute("INSERT OR IGNORE INTO numbers(number, owner, code) VALUES(?, NULL, '')",
                            (replacement,))
    con.commit()
    return con

def is_admin(uid):
    return uid in ADMIN_IDS

def main_menu(uid):
    rows = [
        [("📱 Получить один бесплатный номер", "number")],
        [("🔐 Как получить код входа", "repeat_code")],
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
         ("🗑 Удалить запись", "delete")],
        [("⚖️ Наказания", "punish")],
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
        "🔷 TELEFOSTGRAM\n\n"
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
        await show(update, "🔒 Доступ к TelefostGram ограничен.")
        return

    if action == "home":
        await show(update, "🌑 TELEFOSTGRAM\n\nГлавное меню:",
                   main_menu(user.id))
    elif action == "help":
        await show(update,
                   "❓ ПОМОЩЬ\n\nВыбирай раздел кнопками меню.",
                   main_menu(user.id))
    elif action == "number":
        # One test number per user; clicking again returns the same assignment.
        with database() as con:
            owned = con.execute(
                "SELECT number, code FROM numbers WHERE owner=? LIMIT 1", (user.id,)
            ).fetchone()
        if owned:
            await show(
                update,
                f"📱 ТВОЙ ТЕСТОВЫЙ НОМЕР\\n\\n{owned['number']}\\n\\n"
                f"🧪 Тестовый код: {owned['code']}\\n\\n"
                "Это данные только для TelefostGram, не реальный номер и не SMS-код Telegram.",
                main_menu(user.id)
            )
            return
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
            cur = con.execute("""
                UPDATE numbers SET owner=?, code=''
                WHERE number=? AND owner IS NULL
            """, (user.id, number))
            if cur.rowcount != 1:
                await show(update, "Не удалось закрепить номер. Нажми ещё раз.",
                           main_menu(user.id))
                return
        await show(
            update,
            f"📱 ТВОЙ НОМЕР TELEFOST\n\n`{number}`\n\n"
            "Чтобы войти в собственный сервис Telefost, введи этот номер в приложении. "
            "Код подтверждения придёт в этот чат от бота. "
            "Это виртуальный номер Telefost, а не действующий номер мобильной сети "
            "и не код авторизации Telegram.",
            main_menu(user.id)
        )
    elif action == "repeat_code":
        with database() as con:
            owned = con.execute(
                "SELECT number, code FROM numbers WHERE owner=? LIMIT 1", (user.id,)
            ).fetchone()
        if not owned:
            await show(update, "Сначала получи тестовый номер.", main_menu(user.id))
            return
        await show(
            update,
            f"🔁 ТВОЙ НОМЕР TELEFOST\\n\\n{owned['number']}\\n\\n"
            "Запроси код входа в приложении Telefost. Бот пришлёт код сюда. "
            "Это подтверждение только для Telefost, не для Telegram.",
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
        await show(update, "🔐 TELEFOSTGRAM ADMIN\n\nВыбери инструмент:",
                   admin_menu())
    elif action in ("find", "delete", "punish", "labels", "freeze", "credits"):
        if not is_admin(user.id):
            await show(update, "⛔ Нет доступа.")
            return
        context.user_data["admin_action"] = action
        prompts = {
            "find": "🔎 Поиск пользователя\\n\\nОтправь Telegram ID, @username или тестовый номер. Ищутся только пользователи базы TelefostGram.",
            "delete": "🗑 Удаление записи только из базы этого бота\\nОтправь: @username причина или ID причина. Аккаунт Telegram не удаляется.",
            "punish": "⚖️ Отправь: @username тип причина\n"
                      "Типы: warn, mute, tempban, ban, unban.",
            "labels": "🏷 Отправь: @username метка\nНапример: @mvdkit VIP",
            "freeze": "🔒 Отправь: @username block или unblock",
            "credits": "⭐ Отправь: @username количество_демо_Stars [premium|none]. Пример: @username 1000 premium. Это не настоящие Telegram Stars/Premium."
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

    if action == "delete":
        delete_parts = value.split(maxsplit=1)
        if len(delete_parts) != 2 or not delete_parts[1].strip():
            await msg.reply_text("Формат: @username причина или ID причина.")
            return
        key, reason = delete_parts[0].strip(), delete_parts[1].strip()
        with database() as con:
            if key.startswith("@"):
                found = con.execute(
                    "SELECT id, username FROM users WHERE lower(username)=? LIMIT 1",
                    (key[1:].lower(),)
                ).fetchone()
            else:
                try:
                    key_id = int(key)
                except ValueError:
                    await msg.reply_text("Укажи @username или числовой ID.")
                    return
                found = con.execute(
                    "SELECT id, username FROM users WHERE id=? LIMIT 1", (key_id,)
                ).fetchone()
            if not found:
                await msg.reply_text("Пользователь не найден в базе этого бота.")
                return
            target_id = found["id"]
            if target_id == user.id or target_id in ADMIN_IDS:
                await msg.reply_text("Нельзя удалить собственную запись или запись администратора.")
                return
            con.execute("UPDATE numbers SET owner=NULL, code='' WHERE owner=?", (target_id,))
            con.execute(
                "INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                (user.id, "delete_user:" + reason[:100], f"{target_id}:{found['username']}")
            )
            con.execute("DELETE FROM users WHERE id=?", (target_id,))
        await msg.reply_text("Запись удалена из базы TelefostGram. Аккаунт Telegram не затронут.")
        return

    parts = value.split(maxsplit=2)
    target = None
    exists = None
    with database() as con:
        if action == "find":
            query = value.strip()
            if query.startswith("@"):
                username = query[1:].lstrip("@").lower()
                exists = con.execute(
                    "SELECT id, username, phone, frozen, label, stars FROM users WHERE lower(username)=? LIMIT 1",
                    (username,)
                ).fetchone()
            elif query.startswith("+") or query.replace(" ", "").isdigit():
                phone = re.sub(r"[^+0-9]", "", query)
                exists = con.execute("""
                    SELECT u.id, u.username, u.phone, u.frozen, u.label, u.stars,
                           n.number AS owned_number
                    FROM users u LEFT JOIN numbers n ON n.owner=u.id
                    WHERE n.number=? OR u.phone=? LIMIT 1
                """, (phone, phone)).fetchone()
                if not exists and query.isdigit():
                    try:
                        target = int(query)
                    except ValueError:
                        target = None
            else:
                try:
                    target = int(query)
                except ValueError:
                    target = None
            if target is not None:
                exists = con.execute(
                    "SELECT id, username, phone, frozen, label, stars FROM users WHERE id=?",
                    (target,)
                ).fetchone()
        else:
            if not parts:
                await msg.reply_text("Укажи @username, Telegram ID или тестовый номер TelefostGram.")
                return
            key = parts[0].strip()
            if key.startswith("@"):
                exists = con.execute(
                    "SELECT id, username, phone, frozen, label, stars FROM users WHERE lower(username)=? LIMIT 1",
                    (key[1:].lower(),)
                ).fetchone()
            elif key.startswith("+"):
                normalized = re.sub(r"[^+0-9]", "", key)
                exists = con.execute("""
                    SELECT u.id, u.username, u.phone, u.frozen, u.label, u.stars
                    FROM users u LEFT JOIN numbers n ON n.owner=u.id
                    WHERE n.number=? OR u.phone=? LIMIT 1
                """, (normalized, normalized)).fetchone()
            else:
                try:
                    target = int(key)
                except ValueError:
                    target = None
                if target is not None:
                    exists = con.execute(
                        "SELECT id, username, phone, frozen, label, stars FROM users WHERE id=?",
                        (target,)
                    ).fetchone()
            if exists:
                target = exists["id"]
            else:
                await msg.reply_text(
                    "Пользователь не найден среди тех, кто запускал бота. "
                    "Проверь @username или тестовый номер TelefostGram."
                )
                return

        if action == "find":
            if not exists:
                await msg.reply_text("Пользователь не найден в базе.")
                return
            with database() as con:
                owned = con.execute(
                    "SELECT number FROM numbers WHERE owner=? ORDER BY number",
                    (exists["id"],)
                ).fetchall()
            numbers_text = ", ".join(x["number"] for x in owned) or "нет"
            await msg.reply_text(
                f"🔎 ПРОФИЛЬ TELEFOSTGRAM\n\n"
                f"🆔 ID: {exists['id']}\n"
                f"👤 Username: @{exists['username'] or 'не указан'}\n"
                f"📱 Телефон: {exists['phone'] or 'не предоставлен'}\n"
                f"📲 Мои тестовые номера: {numbers_text}\n"
                f"🔒 Блокировка: {'да' if exists['frozen'] else 'нет'}\n"
                f"🏷 Метка: {exists['label'] or 'нет'}\n"
                f"⭐ Демо Stars: {exists['stars']}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔐 Админ-панель", callback_data="admin")
                ]])
            )
        elif not exists:
            await msg.reply_text("Пользователь не найден. Он должен запустить бота.")
        elif action == "labels" and len(parts) >= 2:
            label = parts[1].lower()
            allowed_labels = {"scam", "fake", "hold", "major", "vip", "none"}
            if label not in allowed_labels:
                await msg.reply_text("Допустимые метки: scam, fake, hold, major, vip, none.")
                return
            con.execute("UPDATE users SET label=? WHERE id=?",
                        ("" if label == "none" else label, target))
            con.execute("INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                        (user.id, "label:" + label, str(target)))
            await msg.reply_text("Внутренняя метка TelefostGram обновлена.")
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
            premium = parts[2].lower() if len(parts) >= 3 else "none"
            if premium not in ("premium", "none"):
                await msg.reply_text("Третий параметр: premium или none.")
                return
            con.execute("UPDATE users SET stars=?, premium=? WHERE id=?",
                        (amount, "forever" if premium == "premium" else "", target))
            con.execute("INSERT INTO logs(admin_id, action, target) VALUES(?,?,?)",
                        (user.id, "demo_stars_premium", f"{target}:{amount}:{premium}"))
            await msg.reply_text("Внутренние демо-значения сохранены. Это не реальные Telegram Stars/Premium.")
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
        logger.error("Bot startup aborted: BOT_TOKEN is missing.")
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения Render")
    logger.info("Telefost bot process starting; admin IDs configured: %d", len(ADMIN_IDS))
    try:
        database().close()
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
        logger.info("Telegram bot handlers registered; starting polling.")
        app.run_polling()
    except Exception:
        logger.exception("Telefost bot crashed during startup or polling.")
        raise

if __name__ == "__main__":
    main()
