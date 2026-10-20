"""Проверка состояния сайта для администратора: база, хранилище фото, настройки.

Позволяет понять, сохранятся ли данные после обновления сайта, не делая
тестовый редеплой. Значения секретов (пароли, ключи) нигде не показываются.
"""

import os
import time
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.shortcuts import render


@dataclass
class Check:
    title: str
    ok: bool
    summary: str
    details: list[str] = field(default_factory=list)


def check_database() -> Check:
    """Куда подключён сайт и сохранятся ли данные после обновления."""
    db = connection.settings_dict
    vendor = connection.vendor
    details = []

    if vendor == "sqlite":
        details.append("Файл: " + str(db.get("NAME")))
        details.append("Это временная база внутри контейнера: при каждом обновлении сайта она создаётся заново.")
    else:
        details.append(f"Сервер: {db.get('HOST')}:{db.get('PORT') or '5432'}")
        details.append(f"База: {db.get('NAME')}, пользователь: {db.get('USER')}")

    try:
        started = time.monotonic()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        ms = round((time.monotonic() - started) * 1000)
        details.append(f"Соединение есть, ответ за {ms} мс")
    except Exception as exc:  # показываем причину, чтобы её можно было прислать разработчику
        return Check("База данных", False, f"Не удалось подключиться к {vendor}", [*details, f"Ошибка: {exc}"])

    from django.contrib.auth import get_user_model

    from apps.accounts.models import Invite

    details.append(f"Пользователей: {get_user_model().objects.count()}, приглашений: {Invite.objects.count()}")

    if vendor == "sqlite":
        return Check("База данных", False, "Временная база SQLite — данные пропадут при обновлении сайта", details)
    return Check("База данных", True, "PostgreSQL подключена — данные сохраняются", details)


def check_storage() -> Check:
    """Куда сохраняются фото: пробуем записать, прочитать и удалить маленький файл."""
    backend = settings.STORAGES["default"]["BACKEND"]
    is_s3 = "s3" in backend.lower()
    details = []
    if is_s3:
        options = settings.STORAGES["default"].get("OPTIONS", {})
        details.append(f"Бакет: {options.get('bucket_name')}, адрес: {options.get('endpoint_url')}")
    else:
        details.append(f"Папка: {settings.MEDIA_ROOT}")

    name = f"status-check/{uuid.uuid4().hex}.txt"
    try:
        saved = default_storage.save(name, ContentFile(b"ok"))
        with default_storage.open(saved) as f:
            assert f.read() == b"ok"
        default_storage.delete(saved)
        details.append("Тестовый файл записан, прочитан и удалён")
    except Exception as exc:
        hints = [f"Ошибка: {exc}"]
        text = str(exc)
        if "403" in text or "Forbidden" in text or "AccessDenied" in text or "SignatureDoesNotMatch" in text:
            hints.append(
                "403 — хранилище не принимает ключи. Проверьте в панели бакета (раздел подключения): "
                "S3_ACCESS_KEY и S3_SECRET_KEY скопированы целиком и не перепутаны местами, "
                "а S3_BUCKET совпадает с точным именем бакета (у Timeweb оно может начинаться с префикса)."
            )
        elif "404" in text or "NoSuchBucket" in text:
            hints.append("404 — бакета с таким именем нет. Проверьте точное имя бакета в S3_BUCKET.")
        if is_s3:
            hints.append(_visible_buckets_hint())
        return Check("Хранилище фото", False, "Не удалось записать тестовый файл", [*details, *hints])

    if is_s3:
        return Check("Хранилище фото", True, "S3 работает — фото сохраняются", details)
    details.append("Фото лежат внутри контейнера и пропадут при обновлении сайта, если не подключён S3.")
    return Check("Хранилище фото", False, "Локальная папка — фото пропадут при обновлении сайта", details)


def _visible_buckets_hint() -> str:
    """Какие бакеты видны с этими ключами — сразу понятно, ключи неверны или имя бакета."""
    try:
        client = default_storage.connection.meta.client
        names = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    except Exception as exc:
        return f"Список бакетов по этим ключам получить не удалось — скорее всего, неверны сами ключи ({exc})"
    if not names:
        return "Ключи принимаются, но бакетов по ним не видно."
    current = settings.STORAGES["default"].get("OPTIONS", {}).get("bucket_name")
    if current in names:
        return f"Ключи видят бакет {current} — значит, у ключей нет прав на запись в него."
    return "Ключи работают и видят бакеты: " + ", ".join(names) + ". Впишите нужное имя в S3_BUCKET."


def check_settings() -> Check:
    """Основные настройки окружения (только имена переменных, без значений)."""
    db_vars = sorted(k for k in os.environ if k.startswith(("DATABASE", "DB_", "POSTGRES", "PG")))
    details = [
        "Переменные базы, которые видит сайт: " + (", ".join(db_vars) or "нет ни одной"),
        f"Адрес сайта (SITE_URL): {settings.SITE_URL}",
        f"Режим отладки: {'включён' if settings.DEBUG else 'выключен'}",
        f"Регистрация только по приглашениям: {'да' if settings.INVITE_ONLY else 'нет'}",
    ]
    problems = []
    if settings.DEBUG:
        problems.append("режим отладки включён")
    if "127.0.0.1" in settings.SITE_URL or "localhost" in settings.SITE_URL:
        problems.append("SITE_URL не задан — ссылки-приглашения будут вести на 127.0.0.1")
    summary = "Всё в порядке" if not problems else "Проверьте: " + "; ".join(problems)
    return Check("Настройки", not problems, summary, details)


def check_activity() -> Check:
    """Активность и итоги поиска — без проверки на ошибки, просто цифры."""
    try:
        from apps.matching.outcomes import stats

        s = stats()
    except Exception as exc:  # база недоступна — об этом уже скажет проверка базы
        return Check("Активность", False, "Не удалось посчитать", [f"Ошибка: {exc}"])
    return Check(
        "Активность",
        True,
        f"Нашли соседа или комнату: {s['outcomes_total']} (через «Соседей»: {s['outcomes_via_service']})",
        [
            f"Заходили за последние {settings.ACTIVITY_FRESH_DAYS} дн.: {s['active_recent']}",
            f"Не заходили дольше {settings.ACTIVITY_HIDE_DAYS} дн. (скрыты из лент): {s['hidden_inactive']}",
        ],
    )


def run_all_checks() -> list[Check]:
    return [check_database(), check_storage(), check_settings(), check_activity()]


@staff_member_required
def status_view(request):
    from django.contrib import admin

    checks = run_all_checks()
    context = {
        **admin.site.each_context(request),  # шапка и меню админки
        "checks": checks,
        "all_ok": all(c.ok for c in checks),
        "title": "Состояние сайта",
    }
    return render(request, "admin/status.html", context)
