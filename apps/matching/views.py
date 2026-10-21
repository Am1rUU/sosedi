"""Страницы ленты, свайпов и мэтчей.

Свайп отправляется через HTMX: жест или кнопка «Нравится» / «Пропустить» делает POST,
а сервер в ответ присылает HTML следующей карточки. Если возник мэтч, сервер
просит браузер перейти на экран «Это мэтч!» (заголовок HX-Redirect).
Если HTMX не сработал (например, отключён JS), форма отправляется обычным
образом и страница перезагружается.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.listings.models import Listing
from apps.messaging.views import QUICK_PHRASES_FOR_OWNER, QUICK_PHRASES_FOR_SEEKER
from apps.moderation.services import is_blocked_between

from . import outcomes, services
from .models import Match, Swipe


def _is_htmx(request) -> bool:
    """Запрос пришёл от HTMX (нужно вернуть фрагмент страницы, а не всю страницу)."""
    return request.headers.get("HX-Request") == "true"


def _redirect_to_match(match: Match) -> HttpResponse:
    """Ответ HTMX: перейти на экран «Это мэтч!»."""
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("matching:match", args=[match.pk])
    return response


# --- Лента ищущего ----------------------------------------------------------


@login_required
def feed(request):
    """Лента объявлений для ищущего: одна карточка за раз (и следующая — под ней)."""
    profile = request.user.profile
    if not profile.is_complete:
        messages.info(request, "Чтобы смотреть комнаты, укажите имя и город в анкете.")
        return redirect("accounts:profile_edit")

    listings = services.seeker_feed(request.user, limit=2)
    context = {
        "listing": listings[0] if listings else None,
        "has_next": len(listings) > 1,
        "can_rewatch": not listings and services.has_passed_seeker(request.user),
    }
    return render(request, "matching/feed.html", context)


@login_required
@require_POST
def seeker_swipe(request, listing_id: int):
    """Ищущий лайкнул или пропустил объявление."""
    listing = get_object_or_404(Listing, pk=listing_id)
    decision = request.POST.get("decision", "")
    new_match = None
    error = ""
    try:
        result = services.record_swipe(
            actor=request.user, listing=listing, seeker=request.user, side=Swipe.Side.SEEKER, decision=decision
        )
        new_match = result.match
    except (ValidationError, PermissionDenied) as exc:
        error = _error_text(exc)

    # Чтобы владелец увидел анкету, она должна быть «в поиске» — включаем при первом лайке
    if not error and decision == Swipe.Decision.LIKE and not request.user.profile.is_seeking:
        request.user.profile.is_seeking = True
        request.user.profile.save(update_fields=["is_seeking"])

    if not _is_htmx(request):
        if error:
            messages.error(request, error)
        if new_match:
            return redirect("matching:match", match_id=new_match.pk)
        return redirect("matching:feed")

    if new_match:
        return _redirect_to_match(new_match)
    listings = services.seeker_feed(request.user, limit=2)
    return render(
        request,
        "matching/_listing_card.html",
        {
            "listing": listings[0] if listings else None,
            "has_next": len(listings) > 1,
            "swipe_error": error,
            "can_rewatch": not listings and services.has_passed_seeker(request.user),
        },
    )


# --- Лента владельца --------------------------------------------------------


@login_required
def owner_feed(request, listing_id: int):
    """Лента анкет ищущих для конкретного объявления владельца."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    if listing.status != Listing.Status.ACTIVE:
        messages.info(request, "Лента доступна только для активного объявления.")
        return redirect("listings:my")

    people = services.owner_feed(request.user, listing, limit=2)
    context = {
        "listing": listing,
        "person": people[0] if people else None,
        "has_next": len(people) > 1,
        "waiting_count": services.incoming_likes_for_listing(listing).count(),
        "can_rewatch": not people and services.has_passed_owner(listing),
    }
    return render(request, "matching/owner_feed.html", context)


@login_required
@require_POST
def owner_swipe(request, listing_id: int, seeker_id: int):
    """Владелец лайкнул или пропустил анкету ищущего для своего объявления."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    seeker = get_object_or_404(User, pk=seeker_id, is_active=True)
    decision = request.POST.get("decision", "")
    new_match = None
    error = ""
    try:
        result = services.record_swipe(
            actor=request.user, listing=listing, seeker=seeker, side=Swipe.Side.OWNER, decision=decision
        )
        new_match = result.match
    except (ValidationError, PermissionDenied) as exc:
        error = _error_text(exc)

    # Со страницы «Кто лайкнул» возвращаемся обратно в список
    next_url = request.POST.get("next")
    if not _is_htmx(request):
        if error:
            messages.error(request, error)
        if new_match:
            return redirect("matching:match", match_id=new_match.pk)
        if next_url == "likes":
            return redirect("matching:incoming_likes", listing_id=listing.pk)
        return redirect("matching:owner_feed", listing_id=listing.pk)

    if new_match:
        return _redirect_to_match(new_match)
    people = services.owner_feed(request.user, listing, limit=2)
    return render(
        request,
        "matching/_person_card.html",
        {
            "listing": listing,
            "person": people[0] if people else None,
            "has_next": len(people) > 1,
            "swipe_error": error,
            "can_rewatch": not people and services.has_passed_owner(listing),
        },
    )


@login_required
def incoming_likes(request, listing_id: int):
    """Кто лайкнул объявление и ждёт ответа. В MVP бесплатно для всех."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    people = services.incoming_likes_for_listing(listing)
    return render(request, "matching/incoming_likes.html", {"listing": listing, "people": people})


# --- Мэтчи ------------------------------------------------------------------


@login_required
def match_page(request, match_id: int):
    """Экран «Это мэтч!» с быстрыми первыми фразами."""
    match = get_object_or_404(
        Match.objects.select_related("listing", "listing__city", "listing__owner__profile", "seeker__profile"),
        pk=match_id,
        is_closed=False,
    )
    if request.user.pk not in match.participants() or is_blocked_between(match.seeker, match.listing.owner):
        raise Http404
    i_am_owner = match.listing.owner_id == request.user.pk
    return render(
        request,
        "matching/match.html",
        {
            "match": match,
            "other": match.other_side(request.user),
            "i_am_owner": i_am_owner,
            "quick_phrases": QUICK_PHRASES_FOR_OWNER if i_am_owner else QUICK_PHRASES_FOR_SEEKER,
            "continue_url": reverse("matching:owner_feed", args=[match.listing_id])
            if i_am_owner
            else reverse("matching:feed"),
        },
    )


@login_required
def matches(request):
    """Мэтчи пользователя: вкладки «Я ищу» и «Я сдаю», новые — отдельно сверху."""
    role = request.GET.get("role")
    as_seeker, as_owner = [], []
    for match in services.user_matches(request.user):
        item = {
            "match": match,
            "other": match.other_side(request.user),
            "last_message": match.messages.order_by("-created_at").first(),
            "unread": match.messages.filter(read_at__isnull=True).exclude(sender=request.user).count(),
            "i_am_owner": match.listing.owner_id == request.user.pk,
        }
        (as_owner if item["i_am_owner"] else as_seeker).append(item)

    # Вкладка по умолчанию — та, где есть мэтчи (сначала «Я ищу»)
    if role not in ("seeker", "owner"):
        role = "owner" if as_owner and not as_seeker else "seeker"
    items = as_owner if role == "owner" else as_seeker
    return render(
        request,
        "matching/matches.html",
        {
            "role": role,
            "seeker_count": len(as_seeker),
            "owner_count": len(as_owner),
            "new_items": [i for i in items if i["last_message"] is None],
            "chat_items": [i for i in items if i["last_message"] is not None],
        },
    )


def _error_text(error: Exception) -> str:
    """Человекочитаемый текст ошибки валидации или доступа."""
    if isinstance(error, ValidationError):
        return " ".join(error.messages)
    return str(error) or "Действие недоступно"


# --- «Нашли соседа / комнату?» ---------------------------------------------


@login_required
def found(request):
    """Ответ на вопрос «Нашли?».

    С параметром ?listing=<id> — хозяин отмечает, что сдал комнату по объявлению.
    Без параметра — ищущий отмечает, что нашёл жильё.
    Можно выбрать, с кем договорились (из мэтчей), или «в другом месте».
    """
    listing = None
    listing_id = request.GET.get("listing") or request.POST.get("listing")
    if listing_id:
        listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    options = list(outcomes.answer_options(request.user, listing))

    if request.method == "POST":
        choice = request.POST.get("choice", "")
        if choice == "not_yet":
            outcomes.snooze(request.user)
            messages.info(request, "Хорошо, удачи в поиске! Спросим позже.")
            return redirect("matching:matches")
        match = None
        if choice != "elsewhere":
            match = next((m for m in options if str(m.pk) == choice), None)
            if match is None:
                messages.error(request, "Выберите вариант из списка")
                return redirect(request.get_full_path())
        outcomes.record_found(request.user, listing, match)
        if listing:
            messages.success(request, "Поздравляем! Объявление больше не показывается в ленте. Чаты остаются.")
            return redirect("listings:my")
        messages.success(
            request,
            "Поздравляем с новым жильём! Хозяева больше не видят вашу анкету. "
            "Если снова начнёте искать — просто лайкните комнату в ленте.",
        )
        return redirect("matching:matches")

    return render(request, "matching/found.html", {"listing": listing, "options": options})


@login_required
@require_POST
def found_snooze(request):
    """Кнопка «Пока нет» в баннере."""
    outcomes.snooze(request.user)
    return redirect(request.POST.get("next") or "matching:feed")


@login_required
@require_POST
def listing_confirm(request, listing_id: int):
    """Кнопка «Да, ещё свободна» в баннере."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    outcomes.confirm_listing_available(request.user, listing)
    messages.success(request, "Спасибо! Объявление продолжает показываться.")
    return redirect(request.POST.get("next") or "listings:my")


# --- «Посмотреть ещё раз» -------------------------------------------------


@login_required
@require_POST
def rewatch_feed(request):
    """Вернуть в ленту все пропущенные комнаты."""
    services.rewatch_seeker_feed(request.user)
    messages.info(request, "Показываем пропущенные комнаты ещё раз")
    return redirect("matching:feed")


@login_required
@require_POST
def rewatch_owner_feed(request, listing_id: int):
    """Вернуть в ленту анкет все пропущенные анкеты по объявлению."""
    listing = get_object_or_404(Listing, pk=listing_id, owner=request.user)
    services.rewatch_owner_feed(listing)
    messages.info(request, "Показываем пропущенные анкеты ещё раз")
    return redirect("matching:owner_feed", listing_id=listing.pk)
