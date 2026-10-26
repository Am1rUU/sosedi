"""Минимальный клиент Telegram Bot API (без сторонних библиотек)."""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def call(method: str, payload: dict | None = None, timeout: int = 10) -> dict:
    """Вызов метода Bot API. Возвращает поле result или бросает TelegramError."""
    if not is_configured():
        raise TelegramError("Не задан TELEGRAM_BOT_TOKEN")
    request = urllib.request.Request(
        API_URL.format(token=settings.TELEGRAM_BOT_TOKEN, method=method),
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read())
        except Exception:
            raise TelegramError(f"HTTP {exc.code}") from exc
    except Exception as exc:  # нет связи с api.telegram.org
        raise TelegramError(str(exc)) from exc
    if not data.get("ok"):
        raise TelegramError(data.get("description") or "Telegram вернул ошибку")
    return data.get("result")


def bot_username() -> str:
    """Имя бота (для ссылки t.me/имя). Узнаём один раз и запоминаем на сутки."""
    try:
        name = cache.get("telegram:bot_username")
    except OSError:  # кэш недоступен (например, права на файл) — просто спросим Telegram
        name = None
    if not name:
        name = call("getMe")["username"]
        try:
            cache.set("telegram:bot_username", name, 24 * 60 * 60)
        except OSError:
            pass
    return name


def send_message(chat_id: int, text: str, button_text: str = "", button_url: str = "") -> None:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    # Кнопка-ссылка работает только с https-адресом (локально — просто текст со ссылкой)
    if button_text and button_url.startswith("https://"):
        payload["reply_markup"] = {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
    elif button_url:
        payload["text"] = f"{text}\n\n{button_url}"
    call("sendMessage", payload)


def webhook_url() -> str:
    return f"{settings.SITE_URL}/telegram/webhook/"


def set_webhook() -> None:
    """Сообщаем Telegram, куда присылать сообщения боту."""
    call(
        "setWebhook",
        {
            "url": webhook_url(),
            "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
        },
    )
