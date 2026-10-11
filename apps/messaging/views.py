"""Чат между участниками мэтча.

В MVP новые сообщения подгружаются HTMX-запросом раз в несколько секунд
(поллинг). Это проще и надёжнее WebSocket на старте; когда переписка станет
активной, можно перейти на Django Channels, не меняя модели данных.
"""

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.matching.models import Match

from .models import Message

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
    return match


def _mark_read(match: Match, reader) -> None:
    """Отмечает прочитанными все входящие сообщения собеседника."""
    match.messages.filter(read_at__isnull=True).exclude(sender=reader).update(read_at=timezone.now())


@login_required
def chat(request, match_id: int):
    """Страница переписки."""
    match = _get_match_for_user(request, match_id)
    _mark_read(match, request.user)
    context = {
        "match": match,
        "other": match.other_side(request.user),
        "chat_messages": match.messages.select_related("sender"),
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

    if match.is_closed:
        flash.error(request, "Этот мэтч закрыт, отправка сообщений недоступна.")
    elif text:
        Message.objects.create(match=match, sender=request.user, text=text)

    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "messaging/_messages.html",
            {"match": match, "chat_messages": match.messages.select_related("sender")},
        )
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
