#!/bin/sh
# Запуск контейнера «Соседи».
# 1. Готовим папки для фото и кэша и отдаём их пользователю appuser.
# 2. Применяем миграции базы.
# 3. Если заданы DJANGO_SUPERUSER_EMAIL и DJANGO_SUPERUSER_PASSWORD — создаём администратора
#    (удобно на хостинге без консоли; если он уже есть — шаг пропускается).
# 4. Запускаем gunicorn. Рабочие процессы работают не от root.
set -e

MEDIA_DIR="${DJANGO_MEDIA_ROOT:-/app/media}"
CACHE_DIR="${DJANGO_CACHE_DIR:-/tmp/sosedi-cache}"
mkdir -p "$MEDIA_DIR" "$CACHE_DIR"
chown -R appuser:appuser "$MEDIA_DIR" "$CACHE_DIR" 2>/dev/null || true

# Если хранилище хостинга не дало сменить владельца, работаем от root, чтобы фото всё равно сохранялись
if su appuser -s /bin/sh -c "test -w '$MEDIA_DIR'"; then
    RUN_AS="--user appuser --group appuser"
else
    echo "Внимание: папка $MEDIA_DIR недоступна для appuser, gunicorn запускается от root"
    RUN_AS=""
fi

# Диагностика: какие переменные базы видит контейнер (только имена и длина, без значений)
echo "Переменные базы в контейнере: $(env | cut -d= -f1 | grep -E '^(DATABASE|DB_|POSTGRES|PG)' | tr '\n' ' ')"
echo "Длина DATABASE_URL: ${#DATABASE_URL} символов"
python manage.py shell -c "from django.db import connection as c; print('Используемая база:', c.vendor, c.settings_dict.get('HOST') or c.settings_dict.get('NAME'))" 2>/dev/null | tail -1 || true

if [ -z "$DATABASE_URL" ] && [ -z "$DB_HOST" ]; then
    echo "ВНИМАНИЕ: не задан ни DATABASE_URL, ни DB_HOST — используется файл SQLite внутри контейнера."
    echo "ВНИМАНИЕ: все данные (пользователи, анкеты, приглашения) пропадут при следующем обновлении сайта."
    echo "ВНИМАНИЕ: подключите PostgreSQL через DATABASE_URL или переменные DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD."
fi

python manage.py migrate --noinput

if [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
    python manage.py createsuperuser --noinput || echo "Администратор уже существует, пропускаю"
fi

# Telegram-бот для уведомлений: сообщаем Telegram адрес сайта (если задан TELEGRAM_BOT_TOKEN)
# Запускается в фоне, чтобы медленный ответ Telegram не задерживал старт сайта и проверку здоровья
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    # От имени appuser (как и сайт): иначе файлы кэша станут доступны только root и сайт не сможет их прочитать
    if [ -n "$RUN_AS" ]; then
        (sleep 5; su -p appuser -s /bin/sh -c "python manage.py telegram_setup" || echo "Не удалось подключить Telegram-бота") &
    else
        (sleep 5; python manage.py telegram_setup || echo "Не удалось подключить Telegram-бота") &
    fi
fi

# Фейковые пользователи для закрытого теста (10 ищущих + 10 хозяев): SEED_FAKE_USERS=1.
# Убрать их: задать SEED_FAKE_USERS=delete и перезапустить, затем удалить переменную.
if [ "$SEED_FAKE_USERS" = "1" ]; then
    python manage.py seed_fake_users || echo "Не удалось создать фейковых пользователей, продолжаю запуск"
elif [ "$SEED_FAKE_USERS" = "delete" ]; then
    python manage.py seed_fake_users --delete || true
fi

# Миграции выполнялись от root. Если база — файл SQLite, отдаём его appuser,
# иначе сайт сможет только читать базу, а вход и любые изменения упадут с ошибкой 500
# («attempt to write a readonly database»).
if [ -z "$DATABASE_URL" ] && [ -z "$DB_HOST" ] && [ -n "$RUN_AS" ]; then
    chown appuser:appuser /app /app/db.sqlite3* 2>/dev/null || true
fi

# Порт: хостинг может передать свой через PORT, иначе 8000
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 3 \
    $RUN_AS \
    --access-logfile -
