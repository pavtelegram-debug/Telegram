# Telefost API

FastAPI starter backend deployed on Render from the `telefost-server` directory.

## Endpoints

- `GET /` — service status
- `GET /health` — process health
- `GET /v1/status` — API version and Firebase Admin configuration status
- `GET /v1/db/health` — checks `DATABASE_URL` and creates the profile table if needed
- `POST /v1/profiles` — stores a profile in PostgreSQL
- `POST /v1/echo` — diagnostic only; never send secrets, passwords, or Telegram login codes

### Create a profile

Send JSON to `POST /v1/profiles`:

```json
{
  "username": "sample_user",
  "display_name": "Sample User",
  "phone": null
}
```

Usernames must be 5–32 characters, start with a letter, and contain only letters, numbers, and underscores. Username and phone values are unique.

**Security limitation:** this profile endpoint does not verify ownership of a phone number and is not an authentication endpoint. Do not use it to log users in or store passwords/one-time codes. A real registration flow still requires a trusted phone/SMS verification provider and rate limiting.

## Render configuration

- Web Service
- Runtime: Docker
- Root Directory: `telefost-server`
- Branch: `master`
- Environment variable: `DATABASE_URL` set to the PostgreSQL database's **Internal Database URL** from the same Render region.

The API normalizes Render's `postgres://` prefix when needed. The database URL is a secret; do not commit it to GitHub or share it in screenshots.

For Firebase Admin, `FIREBASE_SERVICE_ACCOUNT_JSON` must be a private service-account JSON from Firebase Console / Google Cloud IAM. It is not the same as Android's `google-services.json`; never commit the private key.

This API does not replace Telegram servers or implement Telegram login/chat transport.
