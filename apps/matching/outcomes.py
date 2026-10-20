"""Итоги поиска: «Нашли соседа/комнату?» и «Комната ещё свободна?».

Анкету и объявление не убираем сразу после мэтча: мэтчей обычно несколько,
и многие договорённости срываются. Вместо этого через несколько дней после
мэтча с перепиской сайт спрашивает, нашёл ли человек то, что искал.
Ответ «да» убирает анкету или объявление из лент, но чаты остаются.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.listings.models import Listing
from apps.messaging.models import Message

from .models import Match, Outcome


@dataclass
class Prompt:
    """Какой вопрос показать человеку вверху страницы."""

    kind: str  # "owner_found" | "seeker_found" | "listing_confirm"
    listing: Listing | None = None


def _talked_matches() -> QuerySet[Match]:
    """Открытые мэтчи старше N дней, в которых была переписка."""
    cutoff = timezone.now() - timedelta(days=settings.FOUND_PROMPT_AFTER_DAYS)
    has_messages = Message.objects.filter(match=OuterRef("pk"))
    return Match.objects.filter(is_closed=False, created_at__lte=cutoff).filter(Exists(has_messages))


def pending_prompt(user: User) -> Prompt | None:
    """Нужно ли сейчас о чём-то спросить человека и о чём именно."""
    profile = user.profile
    if profile.found_prompt_snoozed_until and profile.found_prompt_snoozed_until > timezone.now():
        return None

    talked = _talked_matches()

    # Хозяин: активное объявление, по которому уже переписывались
    listing = (
        Listing.objects.filter(owner=user, status=Listing.Status.ACTIVE)
        .filter(Exists(talked.filter(listing=OuterRef("pk"))))
        .order_by("-updated_at")
        .first()
    )
    if listing:
        return Prompt("owner_found", listing)

    # Ищущий: всё ещё ищет и уже переписывался с хозяевами
    if profile.is_seeking and talked.filter(seeker=user).exists():
        return Prompt("seeker_found")

    # Хозяин: объявление давно не менялось — комната ещё свободна?
    stale_before = timezone.now() - timedelta(days=settings.LISTING_CONFIRM_AFTER_DAYS)
    stale = (
        Listing.objects.filter(owner=user, status=Listing.Status.ACTIVE, updated_at__lte=stale_before)
        .order_by("updated_at")
        .first()
    )
    if stale:
        return Prompt("listing_confirm", stale)
    return None


def snooze(user: User) -> None:
    """«Пока нет» — не спрашивать какое-то время."""
    profile = user.profile
    profile.found_prompt_snoozed_until = timezone.now() + timedelta(days=settings.FOUND_PROMPT_SNOOZE_DAYS)
    profile.save(update_fields=["found_prompt_snoozed_until", "updated_at"])


def answer_options(user: User, listing: Listing | None) -> QuerySet[Match]:
    """С кем мог договориться человек: его открытые мэтчи (по объявлению — для хозяина)."""
    qs = Match.objects.filter(is_closed=False).select_related("seeker__profile", "listing__owner__profile", "listing")
    if listing is not None:
        return qs.filter(listing=listing).order_by("-created_at")
    return qs.filter(seeker=user).order_by("-created_at")


@transaction.atomic
def record_found(user: User, listing: Listing | None, match: Match | None) -> Outcome:
    """Человек нашёл: хозяин сдал комнату или ищущий нашёл жильё.

    Объявление получает статус «Сдано», анкета ищущего перестаёт показываться
    хозяевам. Мэтчи и чаты не закрываем — договорённости часто дорабатываются в чате.
    """
    if listing is not None:
        if listing.owner_id != user.pk:
            raise PermissionError("Можно отметить только своё объявление")
        if match is not None and match.listing_id != listing.pk:
            raise ValueError("Мэтч относится к другому объявлению")
        listing.status = Listing.Status.RENTED
        listing.save(update_fields=["status", "updated_at"])
        role = Outcome.Role.OWNER
    else:
        if match is not None and match.seeker_id != user.pk:
            raise PermissionError("Можно выбрать только свой мэтч")
        profile = user.profile
        profile.is_seeking = False
        profile.save(update_fields=["is_seeking", "updated_at"])
        role = Outcome.Role.SEEKER
        listing = match.listing if match else None

    return Outcome.objects.create(user=user, role=role, listing=listing, match=match)


def confirm_listing_available(user: User, listing: Listing) -> None:
    """«Комната ещё свободна» — продлеваем объявление, вопрос пропадает на месяц."""
    if listing.owner_id != user.pk:
        raise PermissionError("Можно подтвердить только своё объявление")
    listing.save(update_fields=["updated_at"])


def stats() -> dict:
    """Цифры для страницы «Состояние сайта»."""
    now = timezone.now()
    seen = Q(last_seen_at__gte=now - timedelta(days=settings.ACTIVITY_FRESH_DAYS))
    hidden = Q(last_seen_at__lt=now - timedelta(days=settings.ACTIVITY_HIDE_DAYS)) | Q(
        last_seen_at__isnull=True, date_joined__lt=now - timedelta(days=settings.ACTIVITY_HIDE_DAYS)
    )
    users = User.objects.filter(is_active=True)
    return {
        "active_recent": users.filter(seen).count(),
        "hidden_inactive": users.filter(hidden).count(),
        "outcomes_total": Outcome.objects.count(),
        "outcomes_via_service": Outcome.objects.filter(match__isnull=False).count(),
    }
