"""Оповещения об ошибках сайта в Telegram.

Если на сайте случается ошибка (например, 500 на какой-то странице), сотрудникам,
которые подключили Telegram в своей анкете, приходит короткое сообщение:
что сломалось, где и когда. Одна и та же ошибка — не чаще раза в 10 минут.

Подключается в settings.LOGGING как обработчик уровня ERROR.
"""

import hashlib
import logging
import threading
import traceback

from django.conf import settings

THROTTLE_SECONDS = 10 * 60


class TelegramAlertHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        # Ошибки самой отправки в Telegram не пересылаем — иначе замкнутый круг
        if record.name.startswith("apps.notifications") or not getattr(settings, "TELEGRAM_BOT_TOKEN", ""):
            return
        try:
            text, key = self._format(record)
        except Exception:
            return
        if getattr(settings, "NOTIFICATIONS_ASYNC", True):
            threading.Thread(target=_send, args=(text, key), daemon=True).start()
        else:
            _send(text, key)

    def _format(self, record: logging.LogRecord) -> tuple[str, str]:
        request = getattr(record, "request", None)
        where = f"{request.method} {request.path}" if request is not None else record.name
        exc_line = ""
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            exc_line = f"{type(exc).__name__}: {str(exc)[:300]}"
            last = traceback.extract_tb(record.exc_info[2])[-1:] if record.exc_info[2] else []
            if last:
                frame = last[0]
                exc_line += f"\n{frame.filename.split('/app/')[-1]}:{frame.lineno} в {frame.name}"
        message = record.getMessage()[:300]
        text = f"⚠️ Ошибка на сайте «Соседи»\n{where}\n{exc_line or message}"
        if exc_line and message and message not in exc_line:
            text += f"\n({message})"
        text += f"\n{settings.SITE_URL}"
        raw_key = f"{where}:{exc_line.splitlines()[0] if exc_line else message}"
        key = "alert:" + hashlib.sha1(raw_key.encode()).hexdigest()
        return text, key


def _send(text: str, key: str) -> None:
    from django.core.cache import cache
    from django.db import connections

    from . import telegram
    from .models import NotificationSettings

    try:
        if not cache.add(key, 1, THROTTLE_SECONDS):
            return
        chat_ids = NotificationSettings.objects.filter(
            user__is_staff=True, user__is_active=True, telegram_chat_id__isnull=False
        ).values_list("telegram_chat_id", flat=True)
        for chat_id in chat_ids:
            try:
                telegram.send_message(chat_id, text)
            except telegram.TelegramError:
                pass
    except Exception:  # оповещение не должно ронять сайт
        pass
    finally:
        if getattr(settings, "NOTIFICATIONS_ASYNC", True):
            connections.close_all()
