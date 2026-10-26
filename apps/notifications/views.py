"""Настройки уведомлений и привязка Telegram-бота."""

import hmac
import json
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import telegram
from .models import NotificationSettings
from .services import settings_for

logger = logging.getLogger(__name__)

# Сколько живёт код привязки из ссылки t.me/бот?start=КОД
LINK_CODE_TTL = timedelta(hours=1)

PROFILE_ANCHOR = "/accounts/profile/#notifications"


@login_required
@require_POST
def update_preferences(request):
    """Галочки «на почту» и «в Telegram» в анкете."""
    prefs = settings_for(request.user)
    prefs.email_enabled = request.POST.get("email_enabled") == "on"
    if prefs.telegram_connected:  # галочка Telegram видна, только когда бот подключён
        prefs.telegram_enabled = request.POST.get("telegram_enabled") == "on"
    prefs.save(update_fields=["email_enabled", "telegram_enabled"])
    messages.success(request, "Настройки уведомлений сохранены")
    return redirect(PROFILE_ANCHOR)


@login_required
@require_POST
def telegram_connect(request):
    """Выдаём одноразовый код и отправляем человека в бота: t.me/бот?start=КОД."""
    if not telegram.is_configured():
        messages.error(request, "Уведомления в Telegram пока не настроены")
        return redirect(PROFILE_ANCHOR)
    try:
        username = telegram.bot_username()
    except telegram.TelegramError:
        logger.exception("Не удалось узнать имя Telegram-бота")
        messages.error(request, "Telegram сейчас недоступен, попробуйте позже")
        return redirect(PROFILE_ANCHOR)

    prefs = settings_for(request.user)
    prefs.telegram_link_code = secrets.token_urlsafe(16)[:24]
    prefs.telegram_link_created_at = timezone.now()
    prefs.save(update_fields=["telegram_link_code", "telegram_link_created_at"])
    return redirect(f"https://t.me/{username}?start={prefs.telegram_link_code}")


@login_required
@require_POST
def telegram_disconnect(request):
    prefs = settings_for(request.user)
    chat_id = prefs.telegram_chat_id
    prefs.telegram_chat_id = None
    prefs.telegram_username = ""
    prefs.save(update_fields=["telegram_chat_id", "telegram_username"])
    if chat_id and telegram.is_configured():
        try:
            telegram.send_message(chat_id, "Уведомления «Соседей» отключены. Подключить снова можно в анкете на сайте.")
        except telegram.TelegramError:
            pass
    messages.success(request, "Telegram отключён")
    return redirect(PROFILE_ANCHOR)


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Сюда Telegram присылает сообщения, которые люди пишут боту.

    Понимаем две команды: /start КОД — привязать чат к аккаунту, /stop — отвязать.
    Всегда отвечаем 200, иначе Telegram будет повторять запрос.
    """
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(token, settings.TELEGRAM_WEBHOOK_SECRET):
        return HttpResponseForbidden()

    try:
        update = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse()
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or chat.get("type") != "private":
        return HttpResponse()

    try:
        reply = _handle_command(chat_id, text, chat.get("username") or "")
        if reply:
            telegram.send_message(chat_id, reply)
    except telegram.TelegramError as exc:
        logger.warning("Не удалось ответить в Telegram: %s", exc)
    return HttpResponse()


def _handle_command(chat_id: int, text: str, username: str) -> str:
    if text.startswith("/start"):
        code = text.removeprefix("/start").strip()
        if not code:
            return (
                "Привет! Это бот уведомлений «Соседей».\n"
                "Чтобы получать сообщения о мэтчах и новых сообщениях, нажмите "
                "«Подключить Telegram» в анкете на сайте."
            )
        prefs = NotificationSettings.objects.filter(
            telegram_link_code=code, telegram_link_created_at__gte=timezone.now() - LINK_CODE_TTL
        ).first()
        if prefs is None:
            return "Ссылка устарела. Нажмите «Подключить Telegram» в анкете на сайте ещё раз."
        # Один чат — один аккаунт: если этот Telegram был привязан к другому аккаунту, отвязываем
        NotificationSettings.objects.filter(telegram_chat_id=chat_id).exclude(pk=prefs.pk).update(
            telegram_chat_id=None, telegram_username=""
        )
        prefs.telegram_chat_id = chat_id
        prefs.telegram_username = username[:64]
        prefs.telegram_enabled = True
        prefs.telegram_link_code = ""
        prefs.save()
        return "Готово! Сюда будут приходить уведомления о мэтчах и новых сообщениях. Отключить: /stop"

    if text.startswith("/stop"):
        updated = NotificationSettings.objects.filter(telegram_chat_id=chat_id).update(
            telegram_chat_id=None, telegram_username=""
        )
        if updated:
            return "Уведомления отключены. Подключить снова можно в анкете на сайте."
        return "Уведомления и так не подключены."

    return "Я умею только присылать уведомления. Команды: /stop — отключить уведомления."


@login_required
def inbox(request):
    """Колокольчик: лайки, мэтчи и сообщения сервиса для активной роли.

    Открыли страницу — показанные уведомления считаются прочитанными
    (новые всё равно подсвечены до следующего захода).
    """
    from django.db.models import Q
    from django.shortcuts import render

    from apps.accounts import roles

    from .models import InAppNotification

    qs = InAppNotification.objects.filter(user=request.user)
    role = roles.role_of(request.user) if roles.active(request.user) else ""
    if role:
        qs = qs.filter(Q(role=role) | Q(role=""))
    items = list(qs[:50])
    unread_ids = [n.pk for n in items if n.read_at is None]
    if unread_ids:
        InAppNotification.objects.filter(pk__in=unread_ids).update(read_at=timezone.now())
    return render(request, "notifications/inbox.html", {"items": items, "unread_ids": set(unread_ids)})
