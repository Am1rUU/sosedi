"""Вспомогательная логика модуля пользователей."""

from django.conf import settings
from django.urls import reverse

from .models import Invite


def invite_url(invite: Invite) -> str:
    """Полная ссылка-приглашение, которую можно отправить человеку."""
    return f"{settings.SITE_URL.rstrip('/')}{reverse('accounts:signup')}?invite={invite.code}"


def create_invites(count: int, note: str = "") -> list[Invite]:
    """Создаёт несколько приглашений сразу."""
    return [Invite.objects.create(note=note) for _ in range(count)]
