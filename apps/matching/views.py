"""Страницы ленты, свайпов и мэтчей.

Свайп отправляется через HTMX: кнопка «Лайк» / «Пропустить» делает POST,
а сервер в ответ присылает HTML следующей карточки. Без JavaScript-фреймворка
получается поведение, похожее на мобильное приложение. Если HTMX не сработал
(например, отключён JS), форма отправляется обычным образом и страница
перезагружается.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.listings.models import Listing

from . import services
from .models import Swipe


def _is_htmx(request) -> bool:
    """Запрос пришёл от HTMX (нужно вернуть фрагмент страницы, а не всю страницу)."""
    return request.headers.get("HX-Request") == "true"


# --- Лента ищущего ----------------------------------------------------------


@login_required
def feed(request):
    """Лента объявлений для ищущего: одна карточка за раз."""
    profile = request.user.profile
    if not profile.is_complete:
        messages.info(request, "Чтобы смотреть комнаты, укажите имя и город в анкете.")
        return redirect("accounts:profile_edit")

    listings = services.seeker_feed(request.user, limit=1)
    context = {"listing": listings[0] if listings else None}
    return render(request, "matching/feed.html", context)


@login_required
@require_POST
def seeker_swipe(request, listing_id: int):
    """Ищущий лайкнул или пропустил объявление."""
    listing = get_object_or_404(Listing, pk=listing_id)
    decision = request.POST.get("decision", "")
    new_match = None
    try:
        result = services.record_swipe(
            actor=request.user, listing=listing, seeker=request.user, side=Swipe.Side.SEEKER, decision=decision
        )
        new_match = result.match
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _error_text(error))

    # Чтобы владелец увидел анкету, она должна быть «в поиске» — включаем при первом лайке
    if decision == Swipe.Decision.LIKE and not request.user.profile.is_seeking:
        request.user.profile.is_seeking = True
        request.user.profile.save(update_fields=["is_seeking"])

    if not _is_htmx(request):
        if new_match:
            messages.success(request, "Это мэтч! Можно начинать переписку.")
        return redirect("matching:feed")

    listings = services.seeker_feed(request.user, limit=1)
    return render(
        request,
        "matching/_listing_card.html",
        {"listing": listings[0] if listings else None, "new_match": new_match},
    )


# --- Лента владельца --------------------------------------------------------


@login_required
def owner_feed(request, listing_id: int):
    """Лента анкет ищущих для конкретного объявления владельца."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    if listing.status != Listing.Status.ACTIVE:
        messages.info(request, "Лента доступна только для активного объявления.")
        return redirect("listings:my")

    people = services.owner_feed(request.user, listing, limit=1)
    context = {"listing": listing, "person": people[0] if people else None}
    return render(request, "matching/owner_feed.html", context)


@login_required
@require_POST
def owner_swipe(request, listing_id: int, seeker_id: int):
    """Владелец лайкнул или пропустил анкету ищущего для своего объявления."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    seeker = get_object_or_404(User, pk=seeker_id, is_active=True)
    decision = request.POST.get("decision", "")
    new_match = None
    try:
        result = services.record_swipe(
            actor=request.user, listing=listing, seeker=seeker, side=Swipe.Side.OWNER, decision=decision
        )
        new_match = result.match
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _error_text(error))

    # Со страницы «Кто лайкнул» возвращаемся обратно в список
    next_url = request.POST.get("next")
    if not _is_htmx(request):
        if new_match:
            messages.success(request, "Это мэтч! Можно начинать переписку.")
        if next_url == "likes":
            return redirect("matching:incoming_likes", listing_id=listing.pk)
        return redirect("matching:owner_feed", listing_id=listing.pk)

    people = services.owner_feed(request.user, listing, limit=1)
    return render(
        request,
        "matching/_person_card.html",
        {"listing": listing, "person": people[0] if people else None, "new_match": new_match},
    )


@login_required
def incoming_likes(request, listing_id: int):
    """Кто лайкнул объявление и ждёт ответа. В MVP бесплатно для всех."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    people = services.incoming_likes_for_listing(listing)
    return render(request, "matching/incoming_likes.html", {"listing": listing, "people": people})


# --- Мэтчи ------------------------------------------------------------------


@login_required
def matches(request):
    """Все открытые мэтчи пользователя с последним сообщением."""
    items = []
    for match in services.user_matches(request.user):
        items.append(
            {
                "match": match,
                "other": match.other_side(request.user),
                "last_message": match.messages.order_by("-created_at").first(),
                "unread": match.messages.filter(read_at__isnull=True).exclude(sender=request.user).count(),
                "i_am_owner": match.listing.owner_id == request.user.pk,
            }
        )
    return render(request, "matching/matches.html", {"items": items})


def _error_text(error: Exception) -> str:
    """Человекочитаемый текст ошибки валидации или доступа."""
    if isinstance(error, ValidationError):
        return " ".join(error.messages)
    return str(error) or "Действие недоступно"
