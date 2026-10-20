# Образ приложения «Соседи».
# Один и тот же образ используется на staging и в проде — отличаются только переменные окружения.
#
# Порядок шагов важен для скорости сборки: сначала то, что меняется редко
# (пользователь, библиотеки), в конце — код, который меняется часто.

FROM python:3.12-slim

# Не создавать .pyc и сразу выводить логи (их собирает Docker)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Хостинг (Timeweb) проверяет /healthz/ изнутри контейнера командой curl или wget.
# Настоящие curl и wget через apt ставились ~9 минут, поэтому вместо них —
# маленький скрипт на Python (docker/http_probe.py), который делает то же самое.
# Здесь же создаём пользователя без прав root, от которого работает gunicorn.
COPY docker/http_probe.py /usr/local/bin/curl
RUN chmod 755 /usr/local/bin/curl \
    && ln -s /usr/local/bin/curl /usr/local/bin/wget \
    && useradd --create-home appuser

# Библиотеки. Этот шаг кэшируется, пока не изменится requirements.txt.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Затем копируем код
COPY . .

# Собираем статику на этапе сборки образа (ключ нужен только формально).
# Владельцем делаем appuser только папки, куда сайт пишет, — без копирования всего проекта.
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=0 python manage.py collectstatic --noinput \
    && mkdir -p /app/media \
    && chown appuser:appuser /app /app/media

EXPOSE 8000

# Адрес проверки здоровья для хостинга: /healthz/ (см. config/middleware.py)

# Что происходит при старте (миграции, администратор, gunicorn) — см. docker-entrypoint.sh.
# Контейнер стартует от root только чтобы подготовить папку для фото на подключённом диске хостинга,
# сам сайт работает от appuser.
CMD ["sh", "/app/docker-entrypoint.sh"]
