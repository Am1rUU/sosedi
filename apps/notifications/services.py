"""Уведомления о мэтче и новом сообщении — на почту и в Telegram.

Отправка идёт в фоновом потоке после сохранения в базу: страница не ждёт
почтовый сервер, а ошибка отправки не ломает лайк или сообщение.

Чтобы не заваливать человека письмами во время живой переписки, о новых
сообщениях в одном чате сообщаем не чаще раза в NOTIFY_MESSAGES_EVERY_MINUTES.
"""

import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connections, transaction
from django.urls import reverse

from . import telegram
from .models import NotificationSettings

logger = logging.getLogger(__name__)


def settings_for(user) -> NotificationSettings:
    obj, _ = NotificationSettings.objects.get_or_create(user=user)
    return obj


def run_in_background(func, *args) -> None:
    """Выполнить после фиксации транзакции и (в проде) в отдельном потоке."""

    if not settings.NOTIFICATIONS_ASYNC:  # тесты: сразу, чтобы результат был виден
        _safe(func, *args)
        return

    def in_thread():
        try:
            _safe(func, *args)
        finally:
            connections.close_all()  # у потока своё соединение с базой — закрываем

    def start():
        threading.Thread(target=in_thread, daemon=True).start()

    # Поток стартует, только когда данные уже сохранены в базе
    transaction.on_commit(start)


def _safe(func, *args):
    try:
        func(*args)
    except Exception:  # уведомление не должно ронять сайт
        logger.exception("Не удалось отправить уведомление")


def email_configured() -> bool:
    return bool(settings.EMAIL_HOST)


def _absolute(path: str) -> str:
    return f"{settings.SITE_URL}{path}"


def deliver(user, subject: str, text: str, url: str, button_text: str) -> dict:
    """Отправить уведомление человеку всеми включёнными способами. Возвращает, куда ушло."""
    prefs = settings_for(user)
    sent = {"email": False, "telegram": False}

    if prefs.email_enabled and user.email_verified_at and user.is_active:
        settings_url = _absolute(reverse("accounts:profile_edit") + "#notifications")
        body = f"{text}\n\n{button_text}: {url}\n\n—\nСоседи. Отключить уведомления можно в анкете: {settings_url}"
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
            sent["email"] = True
        except Exception:
            logger.exception("Письмо-уведомление не отправлено (%s)", user.pk)

    if prefs.telegram_enabled and prefs.telegram_chat_id and telegram.is_configured():
        try:
            telegram.send_message(prefs.telegram_chat_id, text, button_text, url)
            sent["telegram"] = True
        except telegram.TelegramError as exc:
            logger.warning("Уведомление в Telegram не отправлено (%s): %s", user.pk, exc)
            # Человек заблокировал бота — отвязываем, чтобы не стучаться впустую
            if "blocked" in str(exc).lower() or "chat not found" in str(exc).lower():
                NotificationSettings.objects.filter(pk=prefs.pk).update(telegram_chat_id=None, telegram_username="")
    return sent


# --- События ----------------------------------------------------------------


def notify_match(match, actor) -> None:
    """Мэтч случился. Тот, кто поставил второй лайк, и так видит экран «Это мэтч!» —
    уведомляем вторую сторону."""
    run_in_background(_send_match, match.pk, actor.pk)


def _send_match(match_id: int, actor_id: int) -> None:
    from apps.matching.models import Match

    match = Match.objects.select_related("listing__owner__profile", "seeker__profile").get(pk=match_id)
    recipient = match.seeker if match.listing.owner_id == actor_id else match.listing.owner
    other = match.listing.owner if recipient.pk == match.seeker_id else match.seeker
    name = other.profile.display_name or "Человек"
    if recipient.pk == match.seeker_id:
        text = f"Взаимный интерес! {name} тоже хочет, чтобы вы жили в комнате «{match.listing.title}». Напишите первым."
    else:
        text = f"Взаимный интерес! {name} хочет в вашу комнату «{match.listing.title}», и вы тоже его лайкнули."
    url = _absolute(reverse("messaging:chat", args=[match.pk]))
    deliver(recipient, "У вас мэтч на «Соседях»", text, url, "Открыть чат")


def notify_message(message) -> None:
    run_in_background(_send_message, message.pk)


def _send_message(message_id: int) -> None:
    from apps.messaging.models import Message

    message = Message.objects.select_related("sender__profile", "match__listing__owner", "match__seeker").get(
        pk=message_id
    )
    match = message.match
    recipient = match.other_side(message.sender)
    if message.read_at:  # уже прочитал, пока мы собирались отправить
        return

    # Не чаще раза в N минут на один чат: первое сообщение — уведомляем, следующие — молчим
    throttle_key = f"notify:message:{match.pk}:{recipient.pk}"
    if not cache.add(throttle_key, 1, settings.NOTIFY_MESSAGES_EVERY_MINUTES * 60):
        return

    name = message.sender.profile.display_name or "Собеседник"
    preview = message.text if len(message.text) <= 140 else message.text[:137] + "…"
    text = f"Новое сообщение от {name}:\n«{preview}»"
    url = _absolute(reverse("messaging:chat", args=[match.pk]))
    deliver(recipient, f"Новое сообщение от {name} — Соседи", text, url, "Ответить")
