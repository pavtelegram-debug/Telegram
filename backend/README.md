# FlostGram API foundation

This is the first server-side foundation for FlostGram's own user directory,
admin tools, and number inventory. It is not yet connected to the Android UI
or the Telegram bot.

## Run locally
```bash
cd backend
python -m venv .venv
# activate the venv, then:
pip install -r requirements.txt
export FLOSTGRAM_ADMIN_TOKEN='use-a-long-random-secret'
uvicorn main:app --host 127.0.0.1 --port 8000
```
Open `/docs` to inspect the API. Health check: `/health`.

## Main endpoints
- `POST /v1/users` create a FlostGram directory user
- `GET /v1/users/search?q=username-or-phone` search by username or phone
- `GET /v1/users/{id}` read one directory entry
- `POST /v1/admin/numbers` add a provisioned phone number to inventory
- `GET /v1/admin/numbers` list number inventory
- `PATCH /v1/admin/users/{id}/status` block/unblock a FlostGram user
- `GET /v1/admin/stats` statistics
- `GET /v1/admin/audit` recent admin actions

Admin endpoints require the `X-Admin-Token` header. Use HTTPS in production,
keep the token in the hosting provider's secret manager, and rotate it if exposed.
This simple token is a bootstrap mechanism, not a substitute for production
authentication, role-based authorization, rate limiting, or abuse monitoring.

## Important limits
A generated string beginning with +79 is not automatically a real phone number.
Only add numbers you control or are authorized to use. This API does not read
SMS, intercept Telegram login codes, register third-party Telegram accounts,
or freeze/block Telegram accounts. Real phone verification must use an authorized
SMS/voice provider and must never be used to collect another service's login code.
