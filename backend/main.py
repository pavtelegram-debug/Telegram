"""FlostGram API foundation.

This service manages FlostGram's own user directory and admin operations.
It does not create real phone numbers, receive Telegram login codes, or control
third-party Telegram accounts. Production deployments should use HTTPS and
replace the development admin token with a proper identity provider.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header, Query
from pydantic import BaseModel, Field

DB_PATH = os.getenv("FLOSTGRAM_DB", "data/flostgram.sqlite3")
ADMIN_TOKEN = os.getenv("FLOSTGRAM_ADMIN_TOKEN", "")
app = FastAPI(title="FlostGram API", version="0.1.0")

@contextmanager
def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          phone TEXT NOT NULL DEFAULT '',
          display_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
        CREATE TABLE IF NOT EXISTS number_inventory(
          phone TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'available',
          assigned_user_id INTEGER,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          target TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """)
        con.commit()
        yield con
        con.commit()
    finally:
        con.close()

def now():
    return datetime.now(timezone.utc).isoformat()

def admin_guard(token):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Set FLOSTGRAM_ADMIN_TOKEN on the server first")
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(403, "Admin access denied")

def audit(con, actor, action, target):
    con.execute("INSERT INTO audit_log(actor,action,target,created_at) VALUES(?,?,?,?)",
                (actor, action, target, now()))

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    phone: str = Field(default="", max_length=20)
    display_name: str = Field(default="", max_length=80)

class NumberCreate(BaseModel):
    phone: str = Field(min_length=4, max_length=20, pattern=r"^\+[0-9]{4,19}$")

class StatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(active|blocked)$")

@app.get("/health")
def health():
    return {"ok": True, "service": "FlostGram API"}

@app.post("/v1/users", status_code=201)
def create_user(payload: UserCreate):
    with db() as con:
        try:
            cur = con.execute(
                "INSERT INTO users(username,phone,display_name,created_at) VALUES(?,?,?,?)",
                (payload.username, payload.phone, payload.display_name, now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Username already exists")
        row = con.execute("SELECT id,username,phone,display_name,status,created_at FROM users WHERE id=?",
                          (cur.lastrowid,)).fetchone()
        return dict(row)

@app.get("/v1/users/search")
def search_users(q: str = Query(min_length=1, max_length=100)):
    term = q.strip().lstrip("@")
    with db() as con:
        rows = con.execute("""
          SELECT id,username,phone,display_name,status,created_at FROM users
          WHERE username LIKE ? COLLATE NOCASE OR phone LIKE ?
          ORDER BY username LIMIT 50
        """, (f"%{term}%", f"%{q.strip()}%")).fetchall()
        return {"users": [dict(r) for r in rows]}

@app.get("/v1/users/{user_id}")
def get_user(user_id: int):
    with db() as con:
        row = con.execute(
          "SELECT id,username,phone,display_name,status,created_at FROM users WHERE id=?",
          (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return dict(row)

@app.post("/v1/admin/numbers", status_code=201)
def add_number(payload: NumberCreate, x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    # Inventory only: adding a number does not claim that it is active or can receive SMS.
    with db() as con:
        try:
            con.execute("INSERT INTO number_inventory(phone,status,created_at) VALUES(?,'available',?)",
                        (payload.phone, now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Number already in inventory")
        audit(con, "admin", "number_added", payload.phone)
        return {"phone": payload.phone, "status": "available"}

@app.get("/v1/admin/numbers")
def list_numbers(x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    with db() as con:
        rows = con.execute("SELECT phone,status,assigned_user_id,created_at FROM number_inventory ORDER BY created_at DESC LIMIT 500").fetchall()
        return {"numbers": [dict(r) for r in rows]}

@app.patch("/v1/admin/users/{user_id}/status")
def update_user_status(user_id: int, payload: StatusUpdate,
                       x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    with db() as con:
        cur = con.execute("UPDATE users SET status=? WHERE id=?", (payload.status, user_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "User not found")
        audit(con, "admin", "user_status_" + payload.status, str(user_id))
        return {"id": user_id, "status": payload.status}

@app.get("/v1/admin/stats")
def stats(x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    with db() as con:
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = con.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0]
        blocked = con.execute("SELECT COUNT(*) FROM users WHERE status='blocked'").fetchone()[0]
        numbers = con.execute("SELECT COUNT(*) FROM number_inventory").fetchone()[0]
        available = con.execute("SELECT COUNT(*) FROM number_inventory WHERE status='available'").fetchone()[0]
        return {"users_total": users, "users_active": active, "users_blocked": blocked,
                "numbers_total": numbers, "numbers_available": available}

@app.get("/v1/admin/audit")
def audit_log(x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    with db() as con:
        rows = con.execute("SELECT actor,action,target,created_at FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
        return {"events": [dict(r) for r in rows]}
