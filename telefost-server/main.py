import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Telefost API", version="0.2.0")

allowed_origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

_firebase_status = "not_configured"
try:
    credentials_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if credentials_json:
        import firebase_admin
        from firebase_admin import credentials
        if not firebase_admin._apps:
            credentials_obj = credentials.Certificate(json.loads(credentials_json))
            firebase_admin.initialize_app(credentials_obj)
        _firebase_status = "initialized"
except Exception:
    _firebase_status = "configuration_error"


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    # Render may provide postgres://; psycopg accepts postgresql://.
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
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(32) NOT NULL UNIQUE,
                phone VARCHAR(32) UNIQUE,
                display_name VARCHAR(80) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


class ProfileCreate(BaseModel):
    username: str = Field(min_length=5, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
    display_name: str = Field(default="", max_length=80)
    phone: str | None = Field(default=None, max_length=32)


@app.get("/")
def root():
    return {"service": "Telefost API", "status": "ok", "firebase": _firebase_status}


@app.get("/health")
def health():
    return {"status": "ok", "service": "telefost-api"}


@app.get("/v1/status")
def status():
    return {"service": "Telefost API", "version": "0.2.0", "firebase": _firebase_status}


@app.get("/v1/db/health")
def database_health():
    try:
        ensure_schema()
        with db_connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception:
        # Do not leak connection strings or database errors to public clients.
        raise HTTPException(status_code=503, detail="Database unavailable or DATABASE_URL misconfigured")


@app.post("/v1/profiles", status_code=201)
def create_profile(profile: ProfileCreate):
    """Create a profile after identity/phone verification has been completed elsewhere.

    This endpoint is not a phone-verification or login endpoint. Do not use it
    to authenticate a user until a trusted verification provider is integrated.
    """
    try:
        ensure_schema()
        with db_connection() as conn:
            row = conn.execute(
                """INSERT INTO user_profiles (username, phone, display_name)
                   VALUES (%s, %s, %s)
                   RETURNING id, username, display_name, created_at""",
                (profile.username, profile.phone, profile.display_name),
            ).fetchone()
        return {
            "ok": True,
            "profile": {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "created_at": row["created_at"].isoformat(),
            },
        }
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Username or phone is already registered")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Could not save profile; check database configuration")


@app.post("/v1/echo")
def echo(payload: dict):
    # Diagnostic endpoint only; do not send passwords, login codes, or personal data.
    if len(json.dumps(payload, ensure_ascii=False)) > 4096:
        raise HTTPException(status_code=413, detail="Payload too large")
    return {"ok": True, "received": True}
