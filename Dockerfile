# Образ приложения «Соседи».
# Один и тот же образ используется на staging и в проде — отличаются только переменные окружения.
#
# Порядок шагов важен для скорости сборки: сначала то, что меняется редко
# (системные утилиты, пользователь, библиотеки), в конце — код, который меняется часто.

FROM python:3.12-slim

# Не создавать .pyc и сразу выводить логи (их собирает Docker)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=0

WORKDIR /app

# curl и wget нужны хостингу (Timeweb), чтобы проверять /healthz/ изнутри контейнера.
# Здесь же создаём пользователя без прав root, от которого работает gunicorn.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl wget \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home appuser

# Библиотеки ставим через uv — он делает то же, что pip, но в разы быстрее.
# Этот шаг кэшируется, пока не изменится requirements.txt.
COPY requirements.txt .
RUN pip install uv==0.12.24 \
    && uv pip install --system -r requirements.txt \
    && pip uninstall -y uv

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
