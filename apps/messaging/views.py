"""Чат между участниками мэтча.

В MVP новые сообщения подгружаются HTMX-запросом раз в несколько секунд
(поллинг). Это проще и надёжнее WebSocket на старте; когда переписка станет
активной, можно перейти на Django Channels, не меняя модели данных.
"""

from django.conf import settings
from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.matching.models import Match
from apps.moderation.services import is_blocked_between
from apps.notifications.services import notify_message
from config import ratelimit

from .models import Message

# Готовые первые фразы — помогают начать разговор сразу после мэтча
QUICK_PHRASES_FOR_SEEKER = [
    "Здравствуйте! Когда можно посмотреть комнату?",
    "Привет! Расскажу немного о себе: ",
]
QUICK_PHRASES_FOR_OWNER = [
    "Здравствуйте! Когда вам удобно посмотреть комнату?",
    "Привет! Расскажу немного о квартире и соседях: ",
    "Давайте договоримся о просмотре. Адрес: ",
]

# Ограничение на длину сообщения (совпадает с моделью)
MAX_MESSAGE_LENGTH = 2000


def _get_match_for_user(request, match_id: int) -> Match:
    """Возвращает мэтч, только если текущий пользователь — его участник."""
    match = get_object_or_404(
        Match.objects.select_related("listing", "listing__owner__profile", "seeker__profile"), pk=match_id
    )
    if request.user.pk not in match.participants():
        # Не раскрываем существование чужого чата — отвечаем «не найдено»
        raise Http404
    if is_blocked_between(match.seeker, match.listing.owner):
        # После блокировки чат исчезает у обоих
        raise Http404
    return match


def _mark_read(match: Match, reader) -> None:
    """Отмечает прочитанными все входящие сообщения собеседника."""
    match.messages.filter(read_at__isnull=True).exclude(sender=reader).update(read_at=timezone.now())


@login_required
def chat(request, match_id: int):
    """Страница переписки."""
    match = _get_match_for_user(request, match_id)
    _mark_read(match, request.user)
    chat_messages = match.messages.select_related("sender")
    i_am_owner = match.listing.owner_id == request.user.pk
    context = {
        "match": match,
        "other": match.other_side(request.user),
        "i_am_owner": i_am_owner,
        "chat_messages": chat_messages,
        # Текст, выбранный на экране мэтча, подставляется в поле ввода
        "prefill": (request.GET.get("text") or "")[:300],
        # Подсказки первых фраз показываем, только пока переписка пустая
        "quick_phrases": []
        if chat_messages.exists()
        else (QUICK_PHRASES_FOR_OWNER if i_am_owner else QUICK_PHRASES_FOR_SEEKER),
    }
    return render(request, "messaging/chat.html", context)


@login_required
def chat_messages(request, match_id: int):
    """Фрагмент со списком сообщений — его периодически запрашивает HTMX."""
    match = _get_match_for_user(request, match_id)
    _mark_read(match, request.user)
    return render(
        request, "messaging/_messages.html", {"match": match, "chat_messages": match.messages.select_related("sender")}
    )


@login_required
@require_POST
def send_message(request, match_id: int):
    """Отправка сообщения. Писать в закрытый мэтч нельзя."""
    match = _get_match_for_user(request, match_id)
    text = (request.POST.get("text") or "").strip()[:MAX_MESSAGE_LENGTH]

    error = ""
    if match.is_closed:
        error = "Этот мэтч закрыт, отправка сообщений недоступна."
    elif text and not request.user.can_interact:
        error = "Подтвердите почту, чтобы писать сообщения, — ссылка в письме, которое мы отправили."
    elif text:
        # Защита от рассылки спама: живой человек столько не напишет
        if ratelimit.is_limited("message", str(request.user.pk), settings.MESSAGE_LIMIT_PER_10_MIN, 10 * 60):
            error = "Вы отправляете сообщения слишком часто. Подождите несколько минут."
        else:
            message = Message.objects.create(match=match, sender=request.user, text=text)
            notify_message(message)

    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "messaging/_messages.html",
            {"match": match, "chat_messages": match.messages.select_related("sender"), "error": error},
        )
    if error:
        flash.error(request, error)
    return redirect("messaging:chat", match_id=match.pk)


@login_required
@require_POST
def close_match(request, match_id: int):
    """Закрыть мэтч: переписка остаётся в истории, но писать больше нельзя."""
    match = _get_match_for_user(request, match_id)
    match.is_closed = True
    match.save(update_fields=["is_closed"])
    flash.info(request, "Мэтч закрыт.")
    return redirect("matching:matches")


@login_required
@require_POST
def delete_message(request, match_id: int, message_id: int):
    """Удалить своё сообщение — у обоих собеседников."""
    match = _get_match_for_user(request, match_id)
    message = get_object_or_404(Message, pk=message_id, match=match, sender=request.user)
    if not message.is_deleted:
        message.deleted_at = timezone.now()
        message.save(update_fields=["deleted_at"])
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "messaging/_messages.html",
            {"match": match, "chat_messages": match.messages.select_related("sender")},
        )
    return redirect("messaging:chat", match_id=match.pk)
