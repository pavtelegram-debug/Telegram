import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DB_PATH = os.getenv("TELEFOST_DB_PATH", "bot/data.sqlite3")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_TOKEN = os.getenv("TELEFOST_ADMIN_TOKEN", "").strip()
CODE_TTL_SECONDS = 300
CODE_COOLDOWN_SECONDS = 30
app = FastAPI(title="Telefost API", version="1.0.0")
_bot_process = None


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    return con


@contextmanager
def database():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with database() as con:
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
        CREATE TABLE IF NOT EXISTS app_users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            stars INTEGER NOT NULL DEFAULT 1000,
            premium TEXT NOT NULL DEFAULT '',
            blocked INTEGER NOT NULL DEFAULT 0,
            label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_codes(
            phone TEXT PRIMARY KEY,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            used_at TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS app_sessions(
            token_hash TEXT PRIMARY KEY,
            app_user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_punishments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            reason TEXT NOT NULL,
            until TEXT DEFAULT '',
            admin TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
        for name, definition in (
            ("phone", "TEXT DEFAULT ''"),
            ("frozen", "INTEGER DEFAULT 0"),
            ("stars", "INTEGER DEFAULT 0"),
            ("premium", "TEXT DEFAULT ''"),
            ("label", "TEXT DEFAULT ''"),
        ):
            if name not in cols:
                con.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")


def normalize_phone(phone: str) -> str:
    value = re.sub(r"[\s()\-]", "", phone)
    if not re.fullmatch(r"\+79\d{9}", value):
        raise HTTPException(status_code=422, detail="Номер Telefost должен иметь формат +79XXXXXXXXX.")
    return value


def send_bot_message(chat_id: int, message: str):
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Бот не настроен: отсутствует BOT_TOKEN.")
    body = urllib.parse.urlencode({"chat_id": str(chat_id), "text": message}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            import json
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError("Telegram Bot API rejected sendMessage")
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Не удалось доставить код в чат бота. Открой бота и нажми /start.",
        )


def admin_auth(authorization: Optional[str] = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Админ-токен сервера не настроен.")
    expected = "Bearer " + ADMIN_TOKEN
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=403, detail="Нет доступа администратора.")
    return "admin"


def current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Нужен токен сессии Telefost.")
    token = authorization[7:].strip()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with database() as con:
        row = con.execute("""
            SELECT u.* FROM app_sessions s
            JOIN app_users u ON u.id=s.app_user_id
            WHERE s.token_hash=? AND s.expires_at>?
        """, (token_hash, iso(now()))).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Сессия истекла. Войди снова.")
    if row["blocked"]:
        raise HTTPException(status_code=403, detail="Аккаунт Telefost заблокирован.")
    return dict(row)


class CodeRequest(BaseModel):
    phone: str = Field(min_length=12, max_length=12)


class CodeVerify(BaseModel):
    phone: str = Field(min_length=12, max_length=12)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    username: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=80)


class ProfileUpdate(BaseModel):
    username: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=80)


class AdminUpdate(BaseModel):
    blocked: Optional[bool] = None
    stars: Optional[int] = Field(default=None, ge=0, le=1_000_000_000)
    premium: Optional[str] = Field(default=None, max_length=40)
    label: Optional[str] = Field(default=None, max_length=32)


class RequestCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    item: str = Field(min_length=1, max_length=100)
    recipient: str = Field(default="", max_length=100)


@app.on_event("startup")
def startup():
    global _bot_process
    init_db()
    if BOT_TOKEN and os.getenv("TELEFOST_START_BOT", "1") == "1":
        env = os.environ.copy()
        env["TELEFOST_DB_PATH"] = DB_PATH
        _bot_process = subprocess.Popen(
            [sys.executable, "-m", "bot.main"],
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )


@app.on_event("shutdown")
def shutdown():
    global _bot_process
    if _bot_process and _bot_process.poll() is None:
        _bot_process.terminate()
        try:
            _bot_process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _bot_process.kill()
    _bot_process = None


@app.get("/health")
def health():
    with database() as con:
        con.execute("SELECT 1").fetchone()
    return {"ok": True, "service": "telefost-api", "time": iso(now())}


@app.post("/v1/auth/request-code")
def request_code(body: CodeRequest):
    phone = normalize_phone(body.phone)
    with database() as con:
        number = con.execute(
            "SELECT number, owner FROM numbers WHERE number=? AND owner IS NOT NULL",
            (phone,),
        ).fetchone()
        if not number:
            raise HTTPException(status_code=404, detail="Номер не найден. Сначала получи его у бота Telefost.")
        owner = con.execute("SELECT id FROM users WHERE id=?", (number["owner"],)).fetchone()
        if not owner:
            raise HTTPException(status_code=409, detail="Владелец номера не найден в базе бота.")
        previous = con.execute(
            "SELECT requested_at FROM auth_codes WHERE phone=?", (phone,)
        ).fetchone()
        if previous:
            try:
                last = datetime.fromisoformat(previous["requested_at"])
                if (now() - last).total_seconds() < CODE_COOLDOWN_SECONDS:
                    raise HTTPException(status_code=429, detail="Подожди 30 секунд перед новым запросом кода.")
            except ValueError:
                pass
        code = f"{secrets.randbelow(1_000_000):06d}"
        con.execute("""
            INSERT INTO auth_codes(phone, code_hash, expires_at, requested_at, used_at)
            VALUES(?,?,?,?,NULL)
            ON CONFLICT(phone) DO UPDATE SET
                code_hash=excluded.code_hash,
                expires_at=excluded.expires_at,
                requested_at=excluded.requested_at,
                used_at=NULL
        """, (
            phone,
            hashlib.sha256(code.encode()).hexdigest(),
            iso(now() + timedelta(seconds=CODE_TTL_SECONDS)),
            iso(now()),
        ))
        owner_id = int(number["owner"])
    # The code is delivered only to the Telegram user who owns the assigned test number.
    send_bot_message(
        owner_id,
        "🔐 Код входа в Telefost: " + code +
        "\nДействует 5 минут. Никому не пересылай этот код. "
        "Он предназначен только для входа в Telefost, не в Telegram."
    )
    return {"ok": True, "message": "Код отправлен в личный чат бота Telefost.", "expires_in": CODE_TTL_SECONDS}


@app.post("/v1/auth/verify")
def verify_code(body: CodeVerify):
    phone = normalize_phone(body.phone)
    with database() as con:
        row = con.execute(
            "SELECT code_hash, expires_at, used_at FROM auth_codes WHERE phone=?",
            (phone,),
        ).fetchone()
        if not row or row["used_at"]:
            raise HTTPException(status_code=400, detail="Код не запрашивался или уже использован.")
        if row["expires_at"] <= iso(now()):
            raise HTTPException(status_code=400, detail="Код истёк. Запроси новый.")
        candidate = hashlib.sha256(body.code.encode()).hexdigest()
        if not hmac.compare_digest(row["code_hash"], candidate):
            raise HTTPException(status_code=400, detail="Неверный код.")
        number = con.execute(
            "SELECT owner FROM numbers WHERE number=? AND owner IS NOT NULL", (phone,)
        ).fetchone()
        if not number:
            raise HTTPException(status_code=404, detail="Номер больше не назначен.")
        con.execute("UPDATE auth_codes SET used_at=? WHERE phone=?", (iso(now()), phone))
        con.execute("""
            INSERT INTO app_users(phone, username, display_name, stars, created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(phone) DO UPDATE SET
                username=CASE WHEN excluded.username='' THEN app_users.username ELSE excluded.username END,
                display_name=CASE WHEN excluded.display_name='' THEN app_users.display_name ELSE excluded.display_name END
        """, (phone, body.username.lstrip("@").lower(), body.display_name, 1000, iso(now())))
        app_user = con.execute("SELECT * FROM app_users WHERE phone=?", (phone,)).fetchone()
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        con.execute(
            "INSERT INTO app_sessions(token_hash, app_user_id, expires_at, created_at) VALUES(?,?,?,?)",
            (token_hash, app_user["id"], iso(now() + timedelta(days=30)), iso(now())),
        )
        con.execute(
            "INSERT INTO app_logs(actor, action, target, details, created_at) VALUES(?,?,?,?,?)",
            ("system", "login", str(app_user["id"]), "phone=" + phone, iso(now())),
        )
    return {
        "ok": True,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 30 * 24 * 3600,
        "user": {
            "id": app_user["id"],
            "phone": app_user["phone"],
            "username": app_user["username"],
            "display_name": app_user["display_name"],
            "stars": app_user["stars"],
            "premium": app_user["premium"],
        },
    }


@app.get("/v1/me")
def me(user=Depends(current_user)):
    return {"ok": True, "user": {
        "id": user["id"], "phone": user["phone"], "username": user["username"],
        "display_name": user["display_name"], "stars": user["stars"],
        "premium": user["premium"], "label": user["label"], "created_at": user["created_at"],
    }}


@app.patch("/v1/me")
def update_me(body: ProfileUpdate, user=Depends(current_user)):
    username = body.username.lstrip("@").strip().lower()
    if username and not re.fullmatch(r"[a-z0-9_]{5,32}", username):
        raise HTTPException(status_code=422, detail="Username: 5–32 символа, латиница, цифры и подчёркивание.")
    with database() as con:
        con.execute("UPDATE app_users SET username=?, display_name=? WHERE id=?",
                    (username, body.display_name.strip(), user["id"]))
        con.execute(
            "INSERT INTO app_logs(actor, action, target, details, created_at) VALUES(?,?,?,?,?)",
            (str(user["id"]), "profile_update", str(user["id"]), "", iso(now())),
        )
    return {"ok": True}


@app.get("/v1/users/search")
def search_users(q: str, user=Depends(current_user)):
    query = q.strip()
    if not query or len(query) > 100:
        raise HTTPException(status_code=422, detail="Введи @username или номер Telefost.")
    if query.startswith("@"):
        rows_query = "SELECT id, phone, username, display_name, stars, premium, label FROM app_users WHERE lower(username)=? LIMIT 20"
        args = (query[1:].lower(),)
    else:
        phone = re.sub(r"[\s()\-]", "", query)
        rows_query = "SELECT id, phone, username, display_name, stars, premium, label FROM app_users WHERE phone=? LIMIT 20"
        args = (phone,)
    with database() as con:
        rows = con.execute(rows_query, args).fetchall()
    return {"ok": True, "users": [dict(r) for r in rows]}


@app.post("/v1/requests")
def create_request(body: RequestCreate, user=Depends(current_user)):
    if body.kind not in ("nft_user", "nft_number", "gift", "support"):
        raise HTTPException(status_code=422, detail="Неизвестный тип заявки.")
    with database() as con:
        cur = con.execute(
            "INSERT INTO requests(user_id, kind, item, recipient, status) VALUES(?,?,?,?,?)",
            (user["id"], body.kind, body.item.strip(), body.recipient.strip(), "Новая"),
        )
        request_id = cur.lastrowid
        con.execute(
            "INSERT INTO app_logs(actor, action, target, details, created_at) VALUES(?,?,?,?,?)",
            (str(user["id"]), "request_created", str(request_id), body.kind, iso(now())),
        )
    return {"ok": True, "request_id": request_id, "status": "Новая"}


@app.get("/v1/me/requests")
def my_requests(user=Depends(current_user)):
    with database() as con:
        rows = con.execute(
            "SELECT id, kind, item, recipient, status, created FROM requests WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "requests": [dict(r) for r in rows]}


@app.get("/v1/admin/stats", dependencies=[Depends(admin_auth)])
def admin_stats():
    with database() as con:
        app_users = con.execute("SELECT COUNT(*) FROM app_users").fetchone()[0]
        bot_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_numbers = con.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
        free_numbers = con.execute("SELECT COUNT(*) FROM numbers WHERE owner IS NULL").fetchone()[0]
        requests = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        blocked = con.execute("SELECT COUNT(*) FROM app_users WHERE blocked=1").fetchone()[0]
    return {"ok": True, "app_users": app_users, "bot_users": bot_users,
            "total_numbers": total_numbers, "free_numbers": free_numbers,
            "requests": requests, "blocked_app_users": blocked}


@app.get("/v1/admin/users", dependencies=[Depends(admin_auth)])
def admin_users(q: str = ""):
    q = q.strip()
    with database() as con:
        if q.startswith("@"):
            rows = con.execute(
                "SELECT id, phone, username, display_name, stars, premium, blocked, label, created_at FROM app_users WHERE lower(username)=? ORDER BY id DESC LIMIT 100",
                (q[1:].lower(),),
            ).fetchall()
        elif q:
            rows = con.execute(
                "SELECT id, phone, username, display_name, stars, premium, blocked, label, created_at FROM app_users WHERE phone=? ORDER BY id DESC LIMIT 100",
                (q,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, phone, username, display_name, stars, premium, blocked, label, created_at FROM app_users ORDER BY id DESC LIMIT 100"
            ).fetchall()
    return {"ok": True, "users": [dict(r) for r in rows]}


@app.patch("/v1/admin/users/{user_id}", dependencies=[Depends(admin_auth)])
def admin_update_user(user_id: int, body: AdminUpdate):
    allowed_labels = {"", "vip", "verified", "scam", "bot", "other", "fake", "hold", "major"}
    if body.label is not None and body.label.lower() not in allowed_labels:
        raise HTTPException(status_code=422, detail="Недопустимая метка.")
    with database() as con:
        row = con.execute("SELECT id FROM app_users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Пользователь не найден.")
        updates, values = [], []
        if body.blocked is not None:
            updates.append("blocked=?"); values.append(int(body.blocked))
        if body.stars is not None:
            updates.append("stars=?"); values.append(body.stars)
        if body.premium is not None:
            updates.append("premium=?"); values.append(body.premium)
        if body.label is not None:
            updates.append("label=?"); values.append(body.label.lower())
        if updates:
            values.append(user_id)
            con.execute("UPDATE app_users SET " + ", ".join(updates) + " WHERE id=?", values)
        con.execute(
            "INSERT INTO app_logs(actor, action, target, details, created_at) VALUES(?,?,?,?,?)",
            ("admin", "user_update", str(user_id), str(body.model_dump(exclude_none=True)), iso(now())),
        )
    return {"ok": True}


@app.get("/v1/admin/logs", dependencies=[Depends(admin_auth)])
def admin_logs():
    with database() as con:
        rows = con.execute(
            "SELECT actor, action, target, details, created_at FROM app_logs ORDER BY id DESC LIMIT 200"
        ).fetchall()
    return {"ok": True, "logs": [dict(r) for r in rows]}


@app.get("/v1/admin/requests", dependencies=[Depends(admin_auth)])
def admin_requests():
    with database() as con:
        rows = con.execute(
            "SELECT id, user_id, kind, item, recipient, status, created FROM requests ORDER BY id DESC LIMIT 200"
        ).fetchall()
    return {"ok": True, "requests": [dict(r) for r in rows]}


@app.patch("/v1/admin/requests/{request_id}", dependencies=[Depends(admin_auth)])
def admin_update_request(request_id: int, status: str):
    if status not in ("Новая", "В работе", "Одобрена", "Отклонена", "Завершена"):
        raise HTTPException(status_code=422, detail="Недопустимый статус заявки.")
    with database() as con:
        cur = con.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")
        con.execute(
            "INSERT INTO app_logs(actor, action, target, details, created_at) VALUES(?,?,?,?,?)",
            ("admin", "request_status", str(request_id), status, iso(now())),
        )
    return {"ok": True}
