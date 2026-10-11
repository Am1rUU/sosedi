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

# Запускаем не от root — базовая гигиена безопасности
RUN useradd --create-home appuser && mkdir -p /app/media && chown -R appuser /app
USER appuser

EXPOSE 8000

# При старте применяем миграции и запускаем gunicorn
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -"]
