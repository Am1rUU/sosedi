"""Подтверждение почты: письмо со ссылкой после регистрации.

Ссылка содержит подписанный токен (id пользователя + email), поэтому
отдельная таблица не нужна. Если человек сменит почту, старые ссылки перестанут работать.
"""

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

SALT = "sosedi.email-verification"


def make_token(user) -> str:
    return signing.dumps({"u": user.pk, "e": user.email}, salt=SALT)


def verification_url(user) -> str:
    return f"{settings.SITE_URL}{reverse('accounts:verify_email', args=[make_token(user)])}"


def send_verification_email(user) -> None:
    days = settings.EMAIL_VERIFICATION_DAYS
    body = (
        "Здравствуйте!\n\n"
        "Чтобы подтвердить почту на «Соседях», откройте ссылку:\n"
        f"{verification_url(user)}\n\n"
        f"Ссылка действует {days} дн. Если вы не регистрировались на «Соседях», просто удалите это письмо."
    )
    send_mail("Подтвердите почту — Соседи", body, settings.DEFAULT_FROM_EMAIL, [user.email])


def send_in_background(user) -> None:
    from apps.notifications.services import run_in_background

    run_in_background(_send_by_id, user.pk)


def _send_by_id(user_id: int) -> None:
    from .models import User

    user = User.objects.filter(pk=user_id, email_verified_at__isnull=True).first()
    if user:
        send_verification_email(user)


def confirm(token: str):
    """Проверяет токен и отмечает почту подтверждённой. Возвращает пользователя или None."""
    from .models import User

    try:
        data = signing.loads(token, salt=SALT, max_age=settings.EMAIL_VERIFICATION_DAYS * 24 * 60 * 60)
    except signing.BadSignature:  # подделка или истёк срок
        return None
    user = User.objects.filter(pk=data.get("u"), email=data.get("e"), is_active=True).first()
    if user and not user.email_verified_at:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
    return user
