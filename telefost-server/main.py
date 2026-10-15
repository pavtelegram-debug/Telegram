import hashlib
import hmac
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Telefost API", version="0.3.0")
allowed_origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Telefost-Bot-Key"],
)

def now():
    return datetime.now(timezone.utc)

def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url

@contextmanager
def db_connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(get_database_url(), connect_timeout=8, row_factory=dict_row) as conn:
        yield conn

def ensure_schema() -> None:
    with db_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id BIGSERIAL PRIMARY KEY, username VARCHAR(32) NOT NULL UNIQUE,
            phone VARCHAR(32) UNIQUE, display_name VARCHAR(80) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS telefost_numbers (
            number VARCHAR(32) PRIMARY KEY, owner BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS telefost_auth_codes (
            phone VARCHAR(32) PRIMARY KEY, code_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL, requested_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS telefost_sessions (
            token_hash VARCHAR(64) PRIMARY KEY, phone VARCHAR(32) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS telefost_messages (
            id BIGSERIAL PRIMARY KEY, sender_phone VARCHAR(32) NOT NULL,
            recipient_phone VARCHAR(32) NOT NULL, body TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), read_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS telefost_messages_pair_idx
            ON telefost_messages(sender_phone, recipient_phone, id);
        """)

def normalize_phone(phone: str) -> str:
    phone = re.sub(r"[\s()\-]", "", phone.strip())
    if not re.fullmatch(r"\+79\d{9}", phone):
        raise HTTPException(status_code=422, detail="Введи номер Telefost в формате +79XXXXXXXXX.")
    return phone

def bot_send_message(chat_id: int, text: str) -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Бот не настроен на сервере.")
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            result = json.loads(response.read().decode())
        if not result.get("ok"):
            raise RuntimeError("Telegram Bot API rejected message")
    except Exception:
        raise HTTPException(status_code=503, detail="Не удалось отправить код в бот Telefost.")

def bot_key(x_telefost_bot_key: str | None = Header(default=None)):
    expected = os.getenv("TELEFOST_BOT_API_KEY", "").strip()
    if not expected or not x_telefost_bot_key or not hmac.compare_digest(expected, x_telefost_bot_key):
        raise HTTPException(status_code=403, detail="Bot API key rejected")

def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Сначала войди в аккаунт Telefost.")
    token = authorization[7:].strip()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    ensure_schema()
    with db_connection() as conn:
        row = conn.execute("""
            SELECT s.phone, s.expires_at, p.username, p.display_name, p.created_at
            FROM telefost_sessions s JOIN user_profiles p ON p.phone=s.phone
            WHERE s.token_hash=%s
        """, (token_hash,)).fetchone()
    if not row or row["expires_at"] <= now():
        raise HTTPException(status_code=401, detail="Сессия истекла. Войди снова.")
    return dict(row)

class ProfileCreate(BaseModel):
    username: str = Field(min_length=5, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
    display_name: str = Field(default="", max_length=80)
    phone: str | None = Field(default=None, max_length=32)

class CodeRequest(BaseModel):
    phone: str

class CodeVerify(BaseModel):
    phone: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    username: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=80)

class NumberSync(BaseModel):
    number: str
    owner: int = Field(gt=0)

class ProfileUpdate(BaseModel):
    username: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=80)

@app.on_event("startup")
def startup():
    try:
        ensure_schema()
    except Exception:
        # Keep health/status endpoints available so Render reports the real DB issue.
        pass

@app.get("/")
def root():
    return {"service": "Telefost API", "status": "ok", "version": "0.3.0"}

@app.get("/health")
def health():
    return {"status": "ok", "service": "telefost-api"}

@app.get("/v1/status")
def status():
    return {"service": "Telefost API", "version": "0.3.0"}

@app.get("/v1/db/health")
def database_health():
    try:
        ensure_schema()
        with db_connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable or DATABASE_URL misconfigured")

@app.post("/v1/bot/numbers", dependencies=[Depends(bot_key)])
def sync_number(body: NumberSync):
    """Synchronize a number allocated by the Telefost bot with the app API."""
    number = normalize_phone(body.number)
    ensure_schema()
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO telefost_numbers(number, owner) VALUES(%s, %s)
            ON CONFLICT(number) DO UPDATE SET owner=EXCLUDED.owner
        """, (number, body.owner))
    return {"ok": True}

@app.post("/v1/auth/request-code")
def request_code(body: CodeRequest):
    phone = normalize_phone(body.phone)
    ensure_schema()
    with db_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM telefost_numbers WHERE number=%s", (phone,)
        ).fetchone()
        if not owner:
            raise HTTPException(status_code=404, detail="Номер не синхронизирован с ботом. Получи номер заново в боте Telefost.")
        previous = conn.execute(
            "SELECT requested_at FROM telefost_auth_codes WHERE phone=%s", (phone,)
        ).fetchone()
        if previous and (now() - previous["requested_at"]).total_seconds() < 30:
            raise HTTPException(status_code=429, detail="Подожди 30 секунд перед новым запросом кода.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        conn.execute("""
            INSERT INTO telefost_auth_codes(phone, code_hash, expires_at, requested_at, used_at)
            VALUES(%s,%s,%s,%s,NULL)
            ON CONFLICT(phone) DO UPDATE SET code_hash=EXCLUDED.code_hash,
                expires_at=EXCLUDED.expires_at, requested_at=EXCLUDED.requested_at, used_at=NULL
        """, (phone, hashlib.sha256(code.encode()).hexdigest(), now()+timedelta(minutes=5), now()))
        owner_id = int(owner["owner"])
    bot_send_message(owner_id, "🔐 Код входа в Telefost: " + code +
        "\nДействует 5 минут. Никому не пересылай код. Это только для Telefost, не для входа в Telegram.")
    return {"ok": True, "message": "Код отправлен в личный чат бота Telefost.", "expires_in": 300}

@app.post("/v1/auth/verify")
def verify_code(body: CodeVerify):
    phone = normalize_phone(body.phone)
    ensure_schema()
    with db_connection() as conn:
        row = conn.execute(
            "SELECT code_hash, expires_at, used_at FROM telefost_auth_codes WHERE phone=%s", (phone,)
        ).fetchone()
        if not row or row["used_at"]:
            raise HTTPException(status_code=400, detail="Код не запрашивался или уже использован.")
        if row["expires_at"] <= now():
            raise HTTPException(status_code=400, detail="Код истёк. Запроси новый.")
        if not hmac.compare_digest(row["code_hash"], hashlib.sha256(body.code.encode()).hexdigest()):
            raise HTTPException(status_code=400, detail="Неверный код.")
        if not conn.execute("SELECT 1 FROM telefost_numbers WHERE number=%s", (phone,)).fetchone():
            raise HTTPException(status_code=404, detail="Номер больше не назначен.")
        username = body.username.lstrip("@").strip().lower()
        if username and not re.fullmatch(r"[a-z][a-z0-9_]{4,31}", username):
            raise HTTPException(status_code=422, detail="Username: 5–32 символа, латиница, цифры и подчёркивание.")
        existing = conn.execute("SELECT username FROM user_profiles WHERE phone=%s", (phone,)).fetchone()
        if existing:
            conn.execute("UPDATE user_profiles SET username=CASE WHEN %s='' THEN username ELSE %s END, display_name=%s WHERE phone=%s",
                         (username, username, body.display_name.strip(), phone))
        else:
            if not username:
                username = "user_" + re.sub(r"\D", "", phone)[-9:]
            conn.execute("INSERT INTO user_profiles(phone, username, display_name) VALUES(%s,%s,%s)",
                         (phone, username, body.display_name.strip()))
        conn.execute("UPDATE telefost_auth_codes SET used_at=%s WHERE phone=%s", (now(), phone))
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO telefost_sessions(token_hash, phone, expires_at) VALUES(%s,%s,%s)",
                     (hashlib.sha256(token.encode()).hexdigest(), phone, now()+timedelta(days=30)))
        profile = conn.execute("SELECT id, phone, username, display_name, created_at FROM user_profiles WHERE phone=%s", (phone,)).fetchone()
    return {"ok": True, "access_token": token, "token_type": "Bearer", "expires_in": 2592000, "user": dict(profile)}

@app.get("/v1/me")
def me(user=Depends(current_user)):
    return {"ok": True, "user": {"phone": user["phone"], "username": user["username"],
        "display_name": user["display_name"], "created_at": user["created_at"].isoformat()}}

@app.patch("/v1/me")
def update_me(body: ProfileUpdate, user=Depends(current_user)):
    username = body.username.lstrip("@").strip().lower()
    if username and not re.fullmatch(r"[a-z][a-z0-9_]{4,31}", username):
        raise HTTPException(status_code=422, detail="Username: 5–32 символа, латиница, цифры и подчёркивание.")
    ensure_schema()
    try:
        with db_connection() as conn:
            conn.execute("UPDATE user_profiles SET username=CASE WHEN %s='' THEN username ELSE %s END, display_name=%s WHERE phone=%s",
                         (username, username, body.display_name.strip(), user["phone"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Этот username уже занят.")
    return {"ok": True}

@app.get("/v1/users/search")
def search_users(q: str, user=Depends(current_user)):
    query = q.strip()
    ensure_schema()
    with db_connection() as conn:
        if query.startswith("@"):
            rows = conn.execute("SELECT id, phone, username, display_name FROM user_profiles WHERE lower(username)=%s LIMIT 20",
                                (query[1:].lower(),)).fetchall()
        else:
            phone = normalize_phone(query)
            rows = conn.execute("SELECT id, phone, username, display_name FROM user_profiles WHERE phone=%s LIMIT 20",
                                (phone,)).fetchall()
    return {"ok": True, "users": [dict(row) for row in rows]}

@app.post("/v1/profiles", status_code=201)
def create_profile(profile: ProfileCreate):
    """Compatibility endpoint for profile creation; not an authentication mechanism."""
    ensure_schema()
    try:
        with db_connection() as conn:
            row = conn.execute(
                "INSERT INTO user_profiles (username, phone, display_name) VALUES (%s,%s,%s) RETURNING id, username, display_name, created_at",
                (profile.username, profile.phone, profile.display_name),
            ).fetchone()
        return {"ok": True, "profile": {**dict(row), "created_at": row["created_at"].isoformat()}}
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Username or phone is already registered")

@app.post("/v1/echo")
def echo(payload: dict):
    if len(json.dumps(payload, ensure_ascii=False)) > 4096:
        raise HTTPException(status_code=413, detail="Payload too large")
    return {"ok": True, "received": True}


class SendMessage(BaseModel):
    to: str
    text: str = Field(min_length=1, max_length=4000)

@app.get("/v1/chats")
def list_chats(user=Depends(current_user)):
    """Return recent conversations for the signed-in Telefost account."""
    ensure_schema()
    with db_connection() as conn:
        rows = conn.execute("""
            WITH conversation_messages AS (
                SELECT CASE WHEN sender_phone=%s THEN recipient_phone ELSE sender_phone END AS peer,
                       body, created_at, id,
                       ROW_NUMBER() OVER (PARTITION BY CASE WHEN sender_phone=%s THEN recipient_phone ELSE sender_phone END
                                          ORDER BY id DESC) AS rn
                FROM telefost_messages
                WHERE sender_phone=%s OR recipient_phone=%s
            )
            SELECT c.peer, c.body AS last_message, c.created_at AS last_message_at,
                   p.username, p.display_name
            FROM conversation_messages c
            LEFT JOIN user_profiles p ON p.phone=c.peer
            WHERE c.rn=1 ORDER BY c.id DESC LIMIT 100
        """, (user["phone"], user["phone"], user["phone"], user["phone"])).fetchall()
    return {"ok": True, "chats": [{**dict(row), "last_message_at": row["last_message_at"].isoformat()} for row in rows]}

@app.get("/v1/chats/{peer}")
def get_chat(peer: str, user=Depends(current_user)):
    """Fetch the latest 200 messages with a Telefost number or exact @username."""
    if peer.startswith("@"):
        lookup = peer[1:].lower()
        with db_connection() as conn:
            profile = conn.execute("SELECT phone FROM user_profiles WHERE lower(username)=%s", (lookup,)).fetchone()
        if not profile:
            raise HTTPException(status_code=404, detail="Пользователь не найден.")
        peer_phone = profile["phone"]
    else:
        peer_phone = normalize_phone(peer)
    if peer_phone == user["phone"]:
        raise HTTPException(status_code=422, detail="Нельзя открыть чат с самим собой.")
    ensure_schema()
    with db_connection() as conn:
        rows = conn.execute("""
            SELECT id, sender_phone, recipient_phone, body, created_at, read_at
            FROM telefost_messages
            WHERE (sender_phone=%s AND recipient_phone=%s) OR (sender_phone=%s AND recipient_phone=%s)
            ORDER BY id DESC LIMIT 200
        """, (user["phone"], peer_phone, peer_phone, user["phone"])).fetchall()
        conn.execute("UPDATE telefost_messages SET read_at=NOW() WHERE sender_phone=%s AND recipient_phone=%s AND read_at IS NULL",
                     (peer_phone, user["phone"]))
    messages = [dict(row) for row in reversed(rows)]
    for message in messages:
        message["created_at"] = message["created_at"].isoformat()
        message["read_at"] = message["read_at"].isoformat() if message["read_at"] else None
    return {"ok": True, "peer": peer_phone, "messages": messages}

@app.post("/v1/chats/{peer}/messages", status_code=201)
def send_chat_message(peer: str, body: SendMessage, user=Depends(current_user)):
    """Store a plain-text message between two Telefost accounts."""
    if peer.startswith("@"):
        with db_connection() as conn:
            profile = conn.execute("SELECT phone FROM user_profiles WHERE lower(username)=%s", (peer[1:].lower(),)).fetchone()
        if not profile:
            raise HTTPException(status_code=404, detail="Пользователь не найден.")
        peer_phone = profile["phone"]
    else:
        peer_phone = normalize_phone(peer)
    if peer_phone == user["phone"]:
        raise HTTPException(status_code=422, detail="Нельзя отправить сообщение самому себе.")
    ensure_schema()
    with db_connection() as conn:
        if not conn.execute("SELECT 1 FROM user_profiles WHERE phone=%s", (peer_phone,)).fetchone():
            raise HTTPException(status_code=404, detail="Аккаунт Telefost получателя не найден.")
        row = conn.execute("""
            INSERT INTO telefost_messages(sender_phone, recipient_phone, body)
            VALUES(%s,%s,%s) RETURNING id, sender_phone, recipient_phone, body, created_at
        """, (user["phone"], peer_phone, body.text.strip())).fetchone()
    result = dict(row)
    result["created_at"] = result["created_at"].isoformat()
    return {"ok": True, "message": result}
