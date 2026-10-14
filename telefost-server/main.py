import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Telefost API", version="0.1.0")

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

@app.get("/")
def root():
    return {"service": "Telefost API", "status": "ok", "firebase": _firebase_status}

@app.get("/health")
def health():
    return {"status": "ok", "service": "telefost-api"}

@app.get("/v1/status")
def status():
    return {"service": "Telefost API", "version": "0.1.0", "firebase": _firebase_status}

@app.post("/v1/echo")
def echo(payload: dict):
    # Diagnostic endpoint only; do not send passwords, login codes, or personal data.
    if len(json.dumps(payload, ensure_ascii=False)) > 4096:
        raise HTTPException(status_code=413, detail="Payload too large")
    return {"ok": True, "received": True}
