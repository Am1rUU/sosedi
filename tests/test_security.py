"""Тесты закрытого режима и защиты: приглашения, запрет индексации, вход,
удаление аккаунта, блокировки, ограничения частоты и очистка фото."""

import io
from datetime import date, timedelta

import pytest
from django.conf import settings as django_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from PIL import Image

from apps.accounts.models import Invite, User
from apps.listings.models import Listing, ListingPhoto
from apps.matching.models import Match, Swipe
from apps.matching.services import owner_feed, record_swipe, seeker_feed
from apps.messaging.models import Message
from apps.moderation.models import Block

pytestmark = pytest.mark.django_db

SIGNUP = {"password1": "Strong-pass-123", "password2": "Strong-pass-123", "accept_terms": "on"}


def _make_match(seeker, listing) -> Match:
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    return record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE).match


def _jpeg_with_gps() -> bytes:
    """JPEG с EXIF-метаданными, включая GPS-координаты (как снимок с телефона)."""
    img = Image.new("RGB", (3000, 2000), (120, 160, 140))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # производитель камеры
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (55.0, 45.0, 0.0)  # широта Москвы
    gps[3] = "E"
    gps[4] = (37.0, 37.0, 0.0)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


# --- Приглашения ---------------------------------------------------------------


def test_signup_requires_invite_in_closed_mode(client, settings):
    settings.INVITE_ONLY = True
    client.post(reverse("accounts:signup"), {"email": "a@test.local", **SIGNUP})
    assert not User.objects.filter(email="a@test.local").exists()

    client.post(reverse("accounts:signup"), {"email": "a@test.local", "invite_code": "WRONG123", **SIGNUP})
    assert not User.objects.filter(email="a@test.local").exists()


def test_invite_link_prefills_code_and_is_single_use(client, settings):
    settings.INVITE_ONLY = True
    invite = Invite.objects.create(note="Маша")
    page = client.get(reverse("accounts:signup") + f"?invite={invite.code.lower()}").content.decode()
    assert invite.code in page  # код из ссылки подставлен в форму

    client.post(reverse("accounts:signup"), {"email": "masha@test.local", "invite_code": invite.code, **SIGNUP})
    invite.refresh_from_db()
    assert invite.used_by.email == "masha@test.local"
    assert invite.used_at is not None

    # Второй человек по тому же коду зарегистрироваться не может
    client.logout()
    client.post(reverse("accounts:signup"), {"email": "petya@test.local", "invite_code": invite.code, **SIGNUP})
    assert not User.objects.filter(email="petya@test.local").exists()


def test_revoked_invite_does_not_work(client, settings):
    settings.INVITE_ONLY = True
    invite = Invite.objects.create(is_active=False)
    client.post(reverse("accounts:signup"), {"email": "b@test.local", "invite_code": invite.code, **SIGNUP})
    assert not User.objects.filter(email="b@test.local").exists()


def test_create_invites_command_prints_links(settings, capsys):
    settings.SITE_URL = "https://sosedi.example"
    call_command("create_invites", 3, note="друзья")
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    assert all(line.startswith("https://sosedi.example/accounts/signup/?invite=") for line in lines)
    assert Invite.objects.filter(note="друзья").count() == 3


def test_invite_code_is_easy_to_read():
    codes = {Invite.objects.create().code for _ in range(20)}
    assert len(codes) == 20
    assert all(len(code) == 8 and not set(code) & set("01OIL") for code in codes)


# --- Запрет индексации ---------------------------------------------------------


def test_noindex_header_meta_and_robots(client, settings):
    settings.SITE_NOINDEX = True
    response = client.get(reverse("home"))
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert 'name="robots" content="noindex' in response.content.decode()
    assert client.get("/robots.txt").content.decode() == "User-agent: *\nDisallow: /\n"


def test_indexing_can_be_enabled(client, settings):
    settings.SITE_NOINDEX = False
    response = client.get(reverse("home"))
    assert "X-Robots-Tag" not in response
    assert "Disallow: /admin/" in client.get("/robots.txt").content.decode()


# --- Вход и пароли --------------------------------------------------------------


def test_argon2_is_the_main_password_hasher():
    # В тестах хэшер подменён на быстрый, поэтому проверяем исходную настройку проекта
    from config import settings as project_settings

    assert project_settings.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    assert django_settings.LOGIN_MAX_FAILURES == 5


def test_login_locks_after_too_many_failures(client, make_user):
    user = make_user()
    url = reverse("accounts:login")
    for _ in range(5):
        client.post(url, {"username": user.email, "password": "wrong-password"})
    # Даже с верным паролем — блокировка на 15 минут
    response = client.post(url, {"username": user.email, "password": "pass12345!"})
    assert "Слишком много неудачных попыток" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_successful_login_resets_counter(client, make_user):
    user = make_user()
    url = reverse("accounts:login")
    for _ in range(3):
        client.post(url, {"username": user.email, "password": "wrong-password"})
    response = client.post(url, {"username": user.email, "password": "pass12345!"})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


# --- Удаление аккаунта ----------------------------------------------------------


def test_delete_account_requires_password(client, make_user):
    user = make_user()
    client.force_login(user)
    client.post(reverse("accounts:delete"), {"password": "wrong"})
    assert User.objects.filter(pk=user.pk).exists()


def test_delete_account_removes_everything(client, make_user, make_listing):
    owner = make_user()
    listing = make_listing(owner=owner)
    photo = ListingPhoto.objects.create(listing=listing, image=SimpleUploadedFile("room.jpg", _jpeg_with_gps()))
    photo_path = photo.image.path
    seeker = make_user()
    match = _make_match(seeker, listing)
    Message.objects.create(match=match, sender=owner, text="Привет")

    client.force_login(owner)
    response = client.post(reverse("accounts:delete"), {"password": "pass12345!"})
    assert response.status_code == 302
    assert not User.objects.filter(pk=owner.pk).exists()
    assert not Listing.objects.filter(pk=listing.pk).exists()
    assert not Match.objects.exists() and not Message.objects.exists()
    import os

    assert not os.path.exists(photo_path)  # файл фото стёрт с диска
    assert "_auth_user_id" not in client.session


# --- Блокировка -----------------------------------------------------------------


def test_block_closes_match_hides_chat_and_feeds(client, seeker, listing):
    match = _make_match(seeker, listing)
    client.force_login(seeker)
    client.post(reverse("moderation:block", args=[listing.owner.pk]))

    match.refresh_from_db()
    assert match.is_closed
    assert Block.objects.filter(blocker=seeker, blocked=listing.owner).exists()
    # Чат недоступен обоим
    assert client.get(reverse("messaging:chat", args=[match.pk])).status_code == 404
    client.force_login(listing.owner)
    assert client.get(reverse("messaging:chat", args=[match.pk])).status_code == 404
    # Друг друга в лентах больше не видят, анкета недоступна
    assert listing not in seeker_feed(seeker)
    assert seeker not in owner_feed(listing.owner, listing)
    assert client.get(reverse("accounts:profile_detail", args=[seeker.pk])).status_code == 404


def test_blocked_users_cannot_match_again(seeker, listing):
    Block.objects.create(blocker=listing.owner, blocked=seeker)
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)


def test_report_can_also_block(client, make_user, listing):
    reporter = make_user()
    client.force_login(reporter)
    client.post(reverse("moderation:report_user", args=[listing.owner.pk]), {"reason": "scam", "also_block": "on"})
    assert Block.objects.filter(blocker=reporter, blocked=listing.owner).exists()


# --- Защита от спама ------------------------------------------------------------


def test_swipe_rate_limit(settings, make_user, make_listing):
    settings.SWIPE_LIMIT_PER_HOUR = 3
    seeker = make_user()
    listings = [make_listing() for _ in range(4)]
    from django.core.exceptions import ValidationError

    for listing in listings[:3]:
        record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)
    with pytest.raises(ValidationError):
        record_swipe(seeker, listings[3], seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)


def test_message_rate_limit(client, settings, seeker, listing):
    settings.MESSAGE_LIMIT_PER_10_MIN = 2
    match = _make_match(seeker, listing)
    client.force_login(seeker)
    for i in range(4):
        response = client.post(reverse("messaging:send", args=[match.pk]), {"text": f"msg {i}"}, HTTP_HX_REQUEST="true")
    assert Message.objects.count() == 2
    assert "слишком часто" in response.content.decode()


# --- Фото ----------------------------------------------------------------------


def _read_uploaded(field) -> Image.Image:
    field.open("rb")
    img = Image.open(io.BytesIO(field.read()))
    field.close()
    return img


def test_listing_photos_lose_gps_and_get_smaller(client, make_user, city):
    owner = make_user()
    client.force_login(owner)
    original = _jpeg_with_gps()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825)  # GPS в исходнике есть

    client.post(
        reverse("listings:create"),
        {
            "title": "С фото",
            "city": city.pk,
            "room_type": "room",
            "rent": 30000,
            "deposit": 0,
            "available_from": date.today().isoformat(),
            "min_term_months": 1,
            "flatmates_count": 1,
            "preferred_gender": "any",
            "description": "Текст",
            "photos": [SimpleUploadedFile("IMG_ivanov_home.jpg", original, content_type="image/jpeg")],
        },
    )
    photo = Listing.objects.get(title="С фото").photos.get()
    img = _read_uploaded(photo.image)
    assert not img.getexif()  # метаданных нет совсем
    assert max(img.size) == django_settings.MAX_PHOTO_SIDE_PX  # уменьшено
    assert "ivanov" not in photo.image.name  # исходное имя файла не сохраняется


def test_profile_photo_is_cleaned(client, seeker, city):
    client.force_login(seeker)
    client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Аня",
            "gender": "f",
            "city": city.pk,
            "schedule": "flex",
            "smoker": "False",
            "has_pets": "False",
            "works_from_home": "True",
            "photo": SimpleUploadedFile("me.jpg", _jpeg_with_gps(), content_type="image/jpeg"),
        },
    )
    seeker.profile.refresh_from_db()
    assert seeker.profile.works_from_home is True
    assert not _read_uploaded(seeker.profile.photo).getexif()


def test_not_an_image_is_rejected(client, make_user, city):
    owner = make_user()
    client.force_login(owner)
    response = client.post(
        reverse("listings:create"),
        {
            "title": "Вирус",
            "city": city.pk,
            "room_type": "room",
            "rent": 30000,
            "deposit": 0,
            "available_from": (date.today() + timedelta(days=1)).isoformat(),
            "min_term_months": 1,
            "flatmates_count": 1,
            "preferred_gender": "any",
            "description": "Текст",
            "photos": [SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")],
        },
    )
    assert response.status_code == 200
    assert not Listing.objects.filter(title="Вирус").exists()


def test_healthcheck_answers_on_internal_http(client, settings):
    """Проверка здоровья отвечает 200 даже на внутренний http-запрос с чужим хостом.

    Так стучится Timeweb App Platform: без https и с внутренним адресом.
    Обычные страницы в таком случае дали бы редирект или ошибку 400.
    """
    settings.ALLOWED_HOSTS = ["sosedi.example"]
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/healthz/", HTTP_HOST="10.0.0.5:8000")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_admin_index_has_invite_shortcut(client, make_user):
    admin_user = User.objects.create_superuser("boss@test.local", "pass12345!")
    client.force_login(admin_user)
    html = client.get("/admin/").content.decode()
    assert "Создать приглашение" in html
    assert "/admin/accounts/invite/add/" in html
    assert "Пользователи" in html  # стандартный список разделов на месте


def test_invite_link_hides_code_field_when_valid(client, settings):
    settings.INVITE_ONLY = True
    invite = Invite.objects.create()
    html = client.get(reverse("accounts:signup") + f"?invite={invite.code}").content.decode()
    assert "Приглашение действует" in html
    assert f'type="hidden" name="invite_code" value="{invite.code}"' in html
    assert 'id="id_invite_code"' not in html  # видимого поля для кода нет

    # Регистрация проходит, хотя человек код не вводил
    client.post(
        reverse("accounts:signup") + f"?invite={invite.code}",
        {"email": "link@test.local", "invite_code": invite.code, **SIGNUP},
    )
    assert User.objects.filter(email="link@test.local").exists()


def test_stale_invite_link_warns_immediately(client, settings):
    settings.INVITE_ONLY = True
    html = client.get(reverse("accounts:signup") + "?invite=STALE123").content.decode()
    assert "не найдено или уже использовано" in html
    assert 'id="id_invite_code"' in html  # можно ввести другой код


def test_site_url_becomes_trusted_origin_and_host(monkeypatch):
    """Домен из SITE_URL сам попадает в ALLOWED_HOSTS и CSRF_TRUSTED_ORIGINS."""
    import importlib

    import config.settings as project_settings

    monkeypatch.setenv("SITE_URL", "https://am1ruu-sosedi.example/")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "localhost")
    monkeypatch.delenv("DJANGO_CSRF_TRUSTED_ORIGINS", raising=False)
    try:
        reloaded = importlib.reload(project_settings)
        assert reloaded.SITE_URL == "https://am1ruu-sosedi.example"
        assert "am1ruu-sosedi.example" in reloaded.ALLOWED_HOSTS
        assert "https://am1ruu-sosedi.example" in reloaded.CSRF_TRUSTED_ORIGINS
    finally:
        monkeypatch.undo()
        importlib.reload(project_settings)


def test_signup_behind_proxy_without_https_header(settings):
    """Хостинг не передал X-Forwarded-Proto: форма всё равно принимается, если домен доверенный."""
    from django.test import Client

    settings.INVITE_ONLY = True
    settings.ALLOWED_HOSTS = ["site.example"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://site.example"]
    invite = Invite.objects.create()
    browser = Client(enforce_csrf_checks=True, HTTP_HOST="site.example")
    browser.get(reverse("accounts:signup") + f"?invite={invite.code}")
    token = browser.cookies["csrftoken"].value
    response = browser.post(
        reverse("accounts:signup") + f"?invite={invite.code}",
        {"csrfmiddlewaretoken": token, "email": "proxy@test.local", "invite_code": invite.code, **SIGNUP},
        HTTP_ORIGIN="https://site.example",
    )
    assert response.status_code == 302
    assert User.objects.filter(email="proxy@test.local").exists()


def test_stale_form_shows_friendly_page(settings):
    from django.test import Client

    settings.INVITE_ONLY = True
    invite = Invite.objects.create()
    browser = Client(enforce_csrf_checks=True)
    browser.get(reverse("accounts:signup") + f"?invite={invite.code}")
    response = browser.post(
        reverse("accounts:signup") + f"?invite={invite.code}",
        {"csrfmiddlewaretoken": "устаревший-токен", "email": "s@test.local", "invite_code": invite.code, **SIGNUP},
    )
    html = response.content.decode()
    assert response.status_code == 403
    assert "Страница устарела" in html
    assert f"?invite={invite.code}" in html  # кнопка ведёт обратно на ту же ссылку-приглашение
