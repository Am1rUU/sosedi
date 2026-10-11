"""Логика модерации."""

from django.conf import settings

from apps.accounts.models import User
from apps.listings.models import Listing

from .models import Report


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
