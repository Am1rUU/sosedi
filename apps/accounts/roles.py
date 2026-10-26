"""Роли «Ищу комнату» и «Сдаю комнату» (вариант Б: активна одна роль).

Человек видит только то, что относится к активной роли, и показывается другим
только в ней. Вторая роль «в тени»: её мэтчи и чаты сохраняются, но анкета
или комната не показываются в лентах.

Функция включается выключателем FeatureFlag «roles»:
- «только сотрудникам» — новое меню и экраны видят только админы (проверка);
- «всем» — видят все, и ленты начинают учитывать роль.
"""

from django.urls import reverse

from . import features
from .models import Profile

SEEKER = Profile.Role.SEEKER
OWNER = Profile.Role.OWNER


def active(user) -> bool:
    """Видит ли человек новые роли и меню."""
    return features.enabled(user, "roles")


def role_of(user) -> str:
    return user.profile.role or ""


def my_listing(user):
    """Комната человека в роли «Сдаю комнату» (одна; заблокированные не считаем)."""
    from apps.listings.models import Listing

    listings = list(user.listings.exclude(status=Listing.Status.BLOCKED).select_related("city"))
    # Сначала активная, потом на паузе / на модерации, потом сданная; среди равных — самая новая
    order = {Listing.Status.ACTIVE: 0, Listing.Status.PAUSED: 1, Listing.Status.PENDING: 1, Listing.Status.RENTED: 2}
    listings.sort(key=lambda listing: (order.get(listing.status, 3), -listing.created_at.timestamp()))
    return listings[0] if listings else None


def switch(user, role: str) -> None:
    """Сделать роль активной. Вторая роль уходит в тень."""
    if role not in (SEEKER, OWNER):
        raise ValueError("Неизвестная роль")
    profile = user.profile
    profile.role = role
    # Анкету ищущего видят хозяева, только пока активна роль «Ищу комнату»
    profile.is_seeking = role == SEEKER
    profile.save(update_fields=["role", "is_seeking", "updated_at"])


def search_url(user) -> str:
    """Куда ведёт лупа в нижнем меню."""
    role = role_of(user)
    if not role:
        return reverse("accounts:start")
    if role == OWNER:
        listing = my_listing(user)
        if listing is None:
            return reverse("listings:create")
        return reverse("matching:owner_feed", args=[listing.pk])
    return reverse("matching:feed")


def after_profile_url(user) -> str:
    """Куда вести после заполнения анкеты на первом входе."""
    if role_of(user) == OWNER and my_listing(user) is None:
        return reverse("listings:create")
    return search_url(user)
