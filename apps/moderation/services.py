"""Логика модерации."""

from django.conf import settings
from django.db.models import Q

from apps.accounts.models import User
from apps.listings.models import Listing

from .models import Block, Report


def blocked_user_ids(user: User) -> set[int]:
    """ID всех, с кем у пользователя блокировка — в любую сторону."""
    made = Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    received = Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    return set(made) | set(received)


def is_blocked_between(a: User, b: User) -> bool:
    """Есть ли блокировка между двумя пользователями (в любую сторону)."""
    return Block.objects.filter(Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)).exists()


def block_user(blocker: User, blocked: User) -> Block:
    """Блокирует пользователя и закрывает все общие мэтчи."""
    from apps.matching.models import Match

    if blocker.pk == blocked.pk:
        raise ValueError("Нельзя заблокировать самого себя")
    block, _ = Block.objects.get_or_create(blocker=blocker, blocked=blocked)
    Match.objects.filter(Q(seeker=blocker, listing__owner=blocked) | Q(seeker=blocked, listing__owner=blocker)).update(
        is_closed=True
    )
    return block


def file_report(reporter: User, reported_user: User, reason: str, comment: str = "", listing: Listing | None = None):
    """Создаёт жалобу и при необходимости автоматически скрывает нарушителя.

    Автоскрытие срабатывает, когда на пользователя поступило
    AUTO_HIDE_AFTER_REPORTS открытых жалоб от РАЗНЫХ людей — так один
    недовольный пользователь не может скрыть кого угодно.
    """
    if reporter.pk == reported_user.pk:
        raise ValueError("Нельзя пожаловаться на самого себя")

    report = Report.objects.create(
        reporter=reporter, reported_user=reported_user, listing=listing, reason=reason, comment=comment
    )

    distinct_reporters = (
        Report.objects.filter(reported_user=reported_user, status=Report.Status.OPEN)
        .values("reporter")
        .distinct()
        .count()
    )
    if distinct_reporters >= settings.AUTO_HIDE_AFTER_REPORTS:
        profile = reported_user.profile
        if not profile.is_hidden:
            profile.is_hidden = True
            profile.save(update_fields=["is_hidden"])
    return report
