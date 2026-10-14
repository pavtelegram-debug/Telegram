# Telefost API

Minimal diagnostic API service for deployment on Render.

- `GET /health` health check
- `GET /v1/status` reports whether Firebase Admin credentials were configured
- `POST /v1/echo` diagnostic only; never send secrets, passwords, or Telegram login codes

Render settings: Web Service, Docker, branch `master`, Root Directory `telefost-server`, Free instance. Do not configure `FIREBASE_SERVICE_ACCOUNT_JSON` with `google-services.json`: they are different credentials. Firebase Admin requires a private service-account JSON from Firebase Console / Google Cloud IAM, stored as a Render secret. Do not commit that private key to GitHub.

This API does not replace Telegram servers or implement Telegram login/chat transport. It is a starter backend for Telefost-specific services.
