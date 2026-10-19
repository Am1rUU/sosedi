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

python manage.py migrate --noinput

if [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
    python manage.py createsuperuser --noinput || echo "Администратор уже существует, пропускаю"
fi

# Порты: основной — из PORT (по умолчанию 8000). Дополнительно слушаем 8080:
# на него по умолчанию стучится Timeweb App Platform, если не распознал порт сам.
MAIN_PORT="${PORT:-8000}"
EXTRA_BIND=""
if [ "$MAIN_PORT" != "8080" ]; then
    EXTRA_BIND="--bind 0.0.0.0:8080"
fi

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:$MAIN_PORT" $EXTRA_BIND \
    --workers 3 \
    $RUN_AS \
    --access-logfile -
