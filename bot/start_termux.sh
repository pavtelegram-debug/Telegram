#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Telefost bot launcher for Termux. The token is kept in this shell session,
# not written into the repository or source files.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

if ! command -v python >/dev/null 2>&1; then
  echo "Python не найден. Выполни: pkg update && pkg install python git"
  exit 1
fi

if [ ! -d ".venv-bot" ]; then
  python -m venv .venv-bot
fi
source .venv-bot/bin/activate
python -m pip install --upgrade pip
python -m pip install "python-telegram-bot==22.5"

if [ -z "${BOT_TOKEN:-}" ]; then
  read -r -s -p "Вставь токен бота от BotFather (ввод скрыт): " BOT_TOKEN
  echo
fi

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "Ошибка: токен пустой."
  exit 1
fi

export BOT_TOKEN
export ADMIN_IDS="${ADMIN_IDS:-7955873453,8803652423,8868524848}"
export TELEFOST_DB_PATH="${TELEFOST_DB_PATH:-$REPO_DIR/bot/data.sqlite3}"

echo "Запускаю Telefost-бота. Для остановки нажми Ctrl+C."
exec python "$REPO_DIR/bot/main.py"
