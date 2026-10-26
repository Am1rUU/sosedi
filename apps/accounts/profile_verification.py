"""Ручная верификация профиля: живое селфи с жестом → модератор сравнивает с фото анкеты.

Селфи — чувствительные данные, поэтому храним его только до решения модератора,
затем удаляем файл. В базе остаётся лишь факт проверки (кто, когда, итог).
"""

import secrets

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from config import ratelimit
from config.images import process_photo

from .models import VERIFICATION_GESTURES, Profile, User, VerificationRequest

SESSION_GESTURE_KEY = "verification_gesture"
# Сколько заявок можно подать за сутки (защита от перебора и спама модераторов)
SUBMITS_PER_DAY = 3


class VerificationError(Exception):
    pass


def pick_gesture(request) -> str:
    """Жест для селфи. Запоминаем в сессии, чтобы при отправке проверить тот же жест."""
    gesture = request.session.get(SESSION_GESTURE_KEY)
    if gesture not in VERIFICATION_GESTURES:
        gesture = secrets.choice(list(VERIFICATION_GESTURES))
        request.session[SESSION_GESTURE_KEY] = gesture
    return gesture


def state(user: User) -> dict:
    """Что показать в анкете: подтверждён, на проверке, отклонён или ещё не подавал."""
    profile = user.profile
    if profile.is_verified:
        return {"status": "verified"}
    last = user.verification_requests.order_by("-created_at").first()
    if last and last.status == VerificationRequest.Status.PENDING:
        return {"status": "pending", "request": last}
    if last and last.status == VerificationRequest.Status.REJECTED:
        return {"status": "rejected", "request": last}
    return {"status": "none"}


@transaction.atomic
def submit(user: User, selfie, gesture: str) -> VerificationRequest:
    profile = user.profile
    if profile.is_verified:
        raise VerificationError("Профиль уже подтверждён")
    if not profile.photo:
        raise VerificationError("Сначала добавьте в анкету фото, где хорошо видно лицо")
    if gesture not in VERIFICATION_GESTURES:
        raise VerificationError("Обновите страницу и попробуйте ещё раз")
    if ratelimit.is_limited("verification", str(user.pk), SUBMITS_PER_DAY, 24 * 60 * 60):
        raise VerificationError("Слишком много попыток за сутки. Попробуйте завтра.")
    if selfie.size > settings.MAX_PHOTO_SIZE_BYTES:
        raise VerificationError("Фото слишком большое, максимум 10 МБ")

    # Новая заявка заменяет ожидающую старую
    for old in user.verification_requests.filter(status=VerificationRequest.Status.PENDING):
        _discard(old)

    request_obj = VerificationRequest(user=user, gesture=gesture, profile_photo_name=profile.photo.name)
    request_obj.selfie.save(f"{secrets.token_hex(8)}.jpg", process_photo(selfie), save=False)
    request_obj.save()
    return request_obj


def _discard(request_obj: VerificationRequest) -> None:
    if request_obj.selfie:
        request_obj.selfie.delete(save=False)
    request_obj.delete()


def _close(request_obj: VerificationRequest, moderator: User, status: str, reason: str = "") -> None:
    if request_obj.selfie:
        request_obj.selfie.delete(save=False)  # селфи больше не нужно — удаляем из хранилища
    request_obj.status = status
    request_obj.reject_reason = reason
    request_obj.reviewed_at = timezone.now()
    request_obj.reviewed_by = moderator
    request_obj.save()


@transaction.atomic
def approve(request_obj: VerificationRequest, moderator: User) -> None:
    profile = Profile.objects.select_for_update().get(user=request_obj.user)
    if not profile.photo or profile.photo.name != request_obj.profile_photo_name:
        raise VerificationError("Человек сменил фото анкеты после подачи заявки — сравнивать не с чем. Отклоните.")
    _close(request_obj, moderator, VerificationRequest.Status.APPROVED)
    profile.verified_at = timezone.now()
    profile.save(update_fields=["verified_at", "updated_at"])
    _notify(
        request_obj.user,
        "Профиль подтверждён — Соседи",
        "Ваш профиль подтверждён ✓ Теперь рядом с вашим именем стоит отметка — так хозяева и соседи доверяют больше.",
    )


@transaction.atomic
def reject(request_obj: VerificationRequest, moderator: User, reason: str) -> None:
    if reason not in VerificationRequest.RejectReason.values:
        raise VerificationError("Выберите причину отказа")
    _close(request_obj, moderator, VerificationRequest.Status.REJECTED, reason)
    _notify(
        request_obj.user,
        "Профиль не подтверждён — Соседи",
        f"Не получилось подтвердить профиль: {request_obj.get_reject_reason_display().lower()}. "
        "Попробуйте ещё раз в анкете.",
    )


def on_profile_photo_changed(profile: Profile) -> bool:
    """Фото анкеты сменилось: отметка снимается, ожидающие заявки теряют смысл.

    Возвращает True, если отметка была и её сняли (чтобы предупредить человека).
    """
    was_verified = profile.is_verified
    if was_verified:
        profile.verified_at = None
        profile.save(update_fields=["verified_at", "updated_at"])
    for pending in profile.user.verification_requests.filter(status=VerificationRequest.Status.PENDING):
        _discard(pending)
    return was_verified


def pending_count() -> int:
    return VerificationRequest.objects.filter(status=VerificationRequest.Status.PENDING).count()


def _notify(user: User, subject: str, text: str) -> None:
    from apps.notifications.models import InAppNotification
    from apps.notifications.services import deliver, inapp, run_in_background

    inapp(user, InAppNotification.Kind.VERIFICATION, text, reverse("accounts:profile_edit") + "#verification")

    url = f"{settings.SITE_URL}{reverse('accounts:profile_edit')}#verification"
    run_in_background(deliver, user, subject, text, url, "Открыть анкету")
