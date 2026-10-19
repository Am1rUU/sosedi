# Образ приложения «Соседи».
# Один и тот же образ используется на staging и в проде — отличаются только переменные окружения.

FROM python:3.12-slim

# Не создавать .pyc и сразу выводить логи (их собирает Docker)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сначала ставим зависимости — этот слой кэшируется, пока не изменится requirements.txt
COPY requirements.txt .
RUN pip install -r requirements.txt

# Затем копируем код
COPY . .

# Собираем статику на этапе сборки образа (ключ нужен только формально)
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=0 python manage.py collectstatic --noinput

# Пользователь без прав root: от него работают процессы gunicorn
RUN useradd --create-home appuser && mkdir -p /app/media && chown -R appuser /app

EXPOSE 8000
# Запасной порт (см. docker-entrypoint.sh)
EXPOSE 8080

# Адрес проверки здоровья для хостинга: /healthz/ (см. config/middleware.py)

# Что происходит при старте (миграции, администратор, gunicorn) — см. docker-entrypoint.sh.
# Контейнер стартует от root только чтобы подготовить папку для фото на подключённом диске хостинга,
# сам сайт работает от appuser.
CMD ["sh", "/app/docker-entrypoint.sh"]
