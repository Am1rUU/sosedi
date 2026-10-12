#!/bin/bash
# =============================================================================
#  Запуск «Соседей» на Mac в один клик.
#
#  Что делает:
#    1. Находит Python 3.10 или новее (если нет — подскажет, где скачать).
#    2. Первый раз создаёт отдельное окружение .venv и ставит зависимости.
#    3. Создаёт базу данных и наполняет её демо-данными.
#    4. Запускает сайт и открывает его в браузере.
#
#  Остановить сайт: закрыть это окно Терминала или нажать Ctrl+C.
#  Начать с чистыми демо-данными: удалить файл db.sqlite3 и запустить снова.
# =============================================================================

set -e

# Работаем из папки, где лежит этот файл (двойной клик запускает его из домашней папки)
cd "$(dirname "$0")"

echo ""
echo "  Соседи — запуск на этом компьютере"
echo "  ----------------------------------"
echo ""

# --- 1. Ищем подходящий Python ----------------------------------------------

python_ok() {
  # Django 5.2 работает на Python 3.10 и новее
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

PYTHON=""
# Сначала — Python с python.org и из Homebrew
for candidate in \
  /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3; do
  if [ -x "$candidate" ] && python_ok "$candidate"; then
    PYTHON="$candidate"
  fi
done

# Системный python3 трогаем, только если установлены инструменты разработчика,
# иначе macOS покажет окно с предложением их установить
if [ -z "$PYTHON" ] && xcode-select -p >/dev/null 2>&1 && python_ok python3; then
  PYTHON="python3"
fi

if [ -z "$PYTHON" ]; then
  echo "  Не найден Python 3.10 или новее."
  echo ""
  echo "  Что сделать:"
  echo "    1. Откроется страница python.org — скачайте установщик для macOS и установите его."
  echo "    2. Снова дважды щёлкните по start.command."
  echo ""
  open "https://www.python.org/downloads/macos/" 2>/dev/null || true
  read -r -p "  Нажмите Enter, чтобы закрыть..."
  exit 1
fi

echo "  Python: $("$PYTHON" --version)"

# --- 2. Окружение и зависимости ---------------------------------------------

if [ ! -x ".venv/bin/python" ]; then
  echo "  Первый запуск: готовлю окружение (1–3 минуты, нужен интернет)..."
  "$PYTHON" -m venv .venv
fi

VENV_PY=".venv/bin/python"

# Ставим зависимости только если requirements.txt изменился с прошлого раза
if ! cmp -s requirements.txt .venv/.installed-requirements 2>/dev/null; then
  echo "  Устанавливаю зависимости..."
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
  cp requirements.txt .venv/.installed-requirements
fi

# --- 3. База данных и демо-данные -------------------------------------------

FIRST_RUN=0
[ -f db.sqlite3 ] || FIRST_RUN=1

"$VENV_PY" manage.py migrate --noinput -v 0

if [ "$FIRST_RUN" = "1" ]; then
  echo "  Создаю демо-данные..."
  "$VENV_PY" manage.py seed_demo
fi

# --- 4. Запуск сайта ---------------------------------------------------------

# Берём первый свободный порт начиная с 8000 (вдруг 8000 чем-то занят)
PORT=$("$VENV_PY" -c '
import socket
for port in range(8000, 8100):
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            print(port)
            break
')
URL="http://127.0.0.1:$PORT"

echo ""
echo "  Сайт: $URL"
echo "  Админка: $URL/admin/"
echo ""
echo "  Демо-аккаунты (пароль у всех: demo12345):"
echo "    seeker5@sosedi.local  — лайкните первую комнату, сразу будет мэтч"
echo "    seeker1@sosedi.local  — уже есть мэтч и чат"
echo "    owner2@sosedi.local   — владелец, на его комнату есть входящий лайк"
echo "    admin@sosedi.local    — модератор, вход в админку"
echo ""
echo "  Чтобы остановить сайт — закройте это окно или нажмите Ctrl+C."
echo ""

# Открываем браузер, когда сервер успеет стартовать
( sleep 2; open "$URL" 2>/dev/null || true ) &

exec "$VENV_PY" manage.py runserver "127.0.0.1:$PORT"
