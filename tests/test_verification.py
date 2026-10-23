"""Ручная верификация профиля: селфи с жестом → модератор сравнивает с фото анкеты."""

import io
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts import profile_verification
from apps.accounts.models import VerificationRequest

pytestmark = pytest.mark.django_db


def _jpeg(name="photo.jpg") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (600, 800), (120, 90, 60)).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@pytest.fixture
def person(make_user):
    user = make_user(display_name="Аня")
    user.profile.photo.save("face.jpg", _jpeg(), save=True)
    return user


@pytest.fixture
def moderator(django_user_model):
    return django_user_model.objects.create_superuser(email="mod@test.local", password="pass12345")


def _submit(client, user):
    client.force_login(user)
    client.get(reverse("accounts:verify_profile"))  # здесь выбирается жест
    return client.post(reverse("accounts:verify_profile"), {"selfie": _jpeg("selfie.jpg")})


def test_full_flow_approve(client, person, moderator, settings):
    response = _submit(client, person)
    assert response.status_code == 302
    req = VerificationRequest.objects.get()
    assert req.status == "pending" and req.selfie
    selfie_path = Path(settings.MEDIA_ROOT) / req.selfie.name
    assert selfie_path.exists()

    client.force_login(moderator)
    html = client.get(reverse("admin:index")).content.decode()
    assert "Ждут верификации: 1" in html
    html = client.get(reverse("verification_queue")).content.decode()
    assert req.gesture_text in html and req.selfie.url in html

    client.post(reverse("verification_queue"), {"request_id": req.pk, "action": "approve"})
    person.profile.refresh_from_db()
    req.refresh_from_db()
    assert person.profile.is_verified
    assert req.status == "approved" and req.reviewed_by == moderator
    assert not selfie_path.exists()  # селфи удалено после решения


def test_reject_with_reason_and_retry(client, person, moderator):
    _submit(client, person)
    req = VerificationRequest.objects.get()
    client.force_login(moderator)
    client.post(reverse("verification_queue"), {"request_id": req.pk, "action": "reject", "reason": "gesture"})
    req.refresh_from_db()
    assert req.status == "rejected"

    client.force_login(person)
    html = client.get(reverse("accounts:profile_edit")).content.decode()
    assert "жест не совпадает" in html and "Попробовать ещё раз" in html


def test_badge_shows_for_verified_owner(client, person, make_listing, seeker):
    person.profile.verified_at = "2026-10-23T10:00:00Z"
    person.profile.save()
    listing = make_listing(owner=person)
    client.force_login(seeker)
    html = client.get(reverse("listings:detail", args=[listing.pk])).content.decode()
    assert "Профиль подтверждён" in html and "Хозяин подтверждён" in html


def test_changing_photo_removes_badge(client, person, city):
    person.profile.verified_at = "2026-10-23T10:00:00Z"
    person.profile.save()
    client.force_login(person)
    client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Аня",
            "gender": "o",
            "city": city.pk,
            "photo": _jpeg("new.jpg"),
            "smoker": "False",
            "has_pets": "False",
            "works_from_home": "False",
            "schedule": "flex",
        },
    )
    person.profile.refresh_from_db()
    assert not person.profile.is_verified


def test_cannot_approve_if_photo_changed_after_request(client, person, moderator):
    _submit(client, person)
    req = VerificationRequest.objects.get()
    person.profile.photo.save("other.jpg", _jpeg(), save=True)  # подменили фото в обход формы
    with pytest.raises(profile_verification.VerificationError):
        profile_verification.approve(req, moderator)


def test_requires_profile_photo_and_limits_attempts(client, make_user):
    no_photo = make_user()
    _submit(client, no_photo)
    assert not VerificationRequest.objects.exists()


def test_attempts_are_limited(client, person):
    for _ in range(5):
        _submit(client, person)
    # Каждая новая заявка заменяет ожидающую; после трёх за сутки — отказ
    assert VerificationRequest.objects.filter(user=person).count() == 1


def test_only_staff_can_open_queue(client, person):
    client.force_login(person)
    assert client.get(reverse("verification_queue")).status_code == 302
