# Telefost API

This service implements **Telefost-owned accounts**, not Telegram accounts.

## Deploy on Render
1. Push this repository and create a Blueprint from `render.yaml`.
2. In the Render service environment, set `BOT_TOKEN` to the token of your Telefost bot.
3. Keep `TELEFOST_ADMIN_TOKEN` private. Render generates it when creating the service.
4. The service stores data on the persistent disk at `/var/data/telefost.sqlite3` and starts the bot as a child process.
5. Check `/health` and `/docs`.

## Internal login flow
1. The user requests a virtual `+79XXXXXXXXX` number from the bot.
2. In the Telefost app, the client must call `POST /v1/auth/request-code` with `{"phone":"+79XXXXXXXXX"}`.
3. The server checks that the number was assigned by the bot and sends a short-lived code to the same user's private bot chat.
4. The client calls `POST /v1/auth/verify` with phone and code. The code expires in 5 minutes and can be used once.
5. Successful registration creates a Telefost-owned profile and grants 1000 internal Stars only on first account creation. The response includes a session token.

The code is only for Telefost's own service. It does not authenticate with Telegram, does not arrive from Telegram, and must not be forwarded to an administrator.

## Important
The current Android client is based on Telegram's MTProto client. Its existing login and messaging screens still authenticate against Telegram's servers. They have **not** been switched to this API; the API endpoints alone do not make Telegram's existing client into a standalone messenger. The Android login and data layer must be implemented against this API before the custom Telefost login flow works in the APK.
