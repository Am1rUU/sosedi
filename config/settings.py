"""
Настройки проекта «Соседи» — MVP сервиса поиска сожителей.

Все параметры, которые различаются между окружениями (локально, staging, прод),
читаются из переменных окружения по принципу 12-factor. Значения по умолчанию
подобраны для локальной разработки, в проде их обязательно переопределить.
"""

import os
from pathlib import Path

import dj_database_url

# Корень проекта (папка, где лежит manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    """Читает булево значение из переменной окружения ("1", "true", "yes" = True)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# --- Безопасность ---------------------------------------------------------

# Секретный ключ: в проде задаётся через переменную окружения, никогда не коммитится
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")

# Режим отладки: включён только локально
DEBUG = env_bool("DJANGO_DEBUG", default=True)

# Домены, с которых разрешено обращаться к сайту (через запятую)
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]

# Доверенные источники для CSRF-проверки (нужны в проде за HTTPS)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# --- Приложения -----------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # 34 000 вместо 34000
    # Модули проекта (модульный монолит: каждый модуль отвечает за свою область)
    "apps.accounts",  # пользователи и анкеты
    "apps.geo",  # города
    "apps.listings",  # объявления о комнатах
    "apps.matching",  # свайпы, мэтчи, лента
    "apps.messaging",  # чат после мэтча
    "apps.moderation",  # жалобы и модерация
]

MIDDLEWARE = [
    # Проверка здоровья для хостинга — первой, до проверок домена и https
    "config.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise раздаёт статику без отдельного nginx — упрощает деплой MVP
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Запрет индексации на время закрытого теста (управляется SITE_NOINDEX)
    "config.middleware.NoIndexMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.site_flags",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- База данных ----------------------------------------------------------

# Локально по умолчанию SQLite (ничего не нужно ставить),
# в Docker и проде — PostgreSQL через переменную DATABASE_URL.
try:
    DATABASES = {
        "default": dj_database_url.config(
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
            conn_max_age=600,
        )
    }
except dj_database_url.ParseError as error:
    # Частая ошибка: в пароле есть символы ? # @ / : + ) и т.п. — в адресе их нужно кодировать
    # (? → %3F, + → %2B, ) → %29, @ → %40, # → %23, / → %2F, : → %3A).
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Не удалось разобрать DATABASE_URL. Скорее всего, в пароле есть спецсимволы "
        "(? # @ / : + и другие) — их нужно закодировать, например ? → %3F, + → %2B, ) → %29. "
        "Закодировать пароль: python -c \"from urllib.parse import quote; print(quote('ПАРОЛЬ', safe=''))\""
    ) from error

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Пользователи ---------------------------------------------------------

# Собственная модель пользователя: вход по email, а не по логину
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Хэширование паролей: Argon2 — современный стандарт (победитель Password Hashing
# Competition). Остальные алгоритмы оставлены, чтобы старые пароли продолжали
# работать: при следующем входе Django сам перехэширует их в Argon2.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "matching:feed"
LOGOUT_REDIRECT_URL = "home"

# --- Локализация ----------------------------------------------------------

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True  # интерфейс готов к переводу на языки СНГ
USE_TZ = True  # время в базе хранится в UTC

# --- Статика и загружаемые файлы ------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Фото пользователей. Папку можно переопределить через DJANGO_MEDIA_ROOT —
# например, на Amvera это /data/media: папка /data там не стирается при обновлении.
# Позже можно перейти на S3-совместимое хранилище через django-storages.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # В тестах и DEBUG используем простое хранилище, в проде — сжатие и кэш-бастинг
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Максимальный размер загружаемого фото (10 МБ — фото с современных телефонов
# бывают тяжёлыми). После загрузки фото всё равно сжимается и уменьшается.
MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
# До какого размера по длинной стороне уменьшать фото
MAX_PHOTO_SIDE_PX = 1600
# Раздавать фото самим приложением (пока нет S3). Выключить после подключения хранилища.
SERVE_MEDIA = env_bool("SERVE_MEDIA", default=True)

# --- Кэш ------------------------------------------------------------------

# Кэш нужен для ограничения частоты действий (попытки входа, свайпы, сообщения).
# Файловый кэш общий для всех процессов gunicorn в одном контейнере и не требует
# отдельного сервиса. Когда появится Redis, достаточно поменять BACKEND.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("DJANGO_CACHE_DIR", "/tmp/sosedi-cache"),
    }
}

# --- Продуктовые настройки ------------------------------------------------

# Премодерация: если True, новые объявления попадают в ленту только после
# одобрения модератором в админке. На старте удобно держать выключенной.
LISTINGS_PREMODERATION = env_bool("LISTINGS_PREMODERATION", default=False)

# Через сколько дней пропущенная карточка снова может появиться в ленте
# (важно для маленьких городов, где лента быстро заканчивается)
FEED_RESURFACE_PASSED_AFTER_DAYS = int(os.environ.get("FEED_RESURFACE_PASSED_AFTER_DAYS", "14"))

# Сколько карточек отдавать в ленту за один запрос
FEED_BATCH_SIZE = 20

# Сколько жалоб на пользователя автоматически скрывают его до проверки
AUTO_HIDE_AFTER_REPORTS = int(os.environ.get("AUTO_HIDE_AFTER_REPORTS", "3"))

# --- Закрытый тест --------------------------------------------------------

# Регистрация только по приглашению. Для публичного запуска выключить: INVITE_ONLY=0
INVITE_ONLY = env_bool("INVITE_ONLY", default=True)
# Запрет индексации поисковиками (robots.txt, заголовок X-Robots-Tag, meta noindex)
SITE_NOINDEX = env_bool("SITE_NOINDEX", default=True)
# Адрес сайта — нужен, чтобы собирать полные ссылки-приглашения (в проде: https://ваш-домен)
SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8000")

# --- Защита от подбора пароля и спама -------------------------------------

# Не продажа лимитов, а защита: обычный человек эти пороги не заметит,
# а бот или скрипт упрётся в них сразу.
LOGIN_MAX_FAILURES = 5  # неудачных попыток входа
LOGIN_LOCKOUT_SECONDS = 15 * 60  # после этого вход блокируется на 15 минут
SWIPE_LIMIT_PER_HOUR = int(os.environ.get("SWIPE_LIMIT_PER_HOUR", "300"))
MESSAGE_LIMIT_PER_10_MIN = int(os.environ.get("MESSAGE_LIMIT_PER_10_MIN", "40"))

# --- Безопасность в проде -------------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Логирование ----------------------------------------------------------

# Пишем логи в stdout: их собирает Docker / облако. Для ошибок в проде
# рекомендуется подключить Sentry (sentry-sdk).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
