"""Тесты страниц: доступ, ключевые сценарии через HTTP, чат и жалобы."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.listings.models import Listing
from apps.matching.models import Match, Swipe
from apps.matching.services import record_swipe
from apps.messaging.models import Message
from apps.moderation.models import Report

pytestmark = pytest.mark.django_db


def _make_match(seeker, listing) -> Match:
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    return record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE).match


# --- Публичные страницы и регистрация ---------------------------------------


def test_home_and_healthcheck(client):
    assert client.get(reverse("home")).status_code == 200
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.content.strip() == b"ok"


def test_private_pages_require_login(client):
    for name in ["matching:feed", "matching:matches", "listings:my", "accounts:profile_edit"]:
        response = client.get(reverse(name))
        assert response.status_code == 302
        assert reverse("accounts:login") in response["Location"]


def test_signup_creates_user_with_profile(client):
    response = client.post(
        reverse("accounts:signup"),
        {
            "email": "New@Test.local",
            "password1": "Strong-pass-123",
            "password2": "Strong-pass-123",
            "accept_terms": "on",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(email="new@test.local")  # email сохранён в нижнем регистре
    assert user.profile is not None


def test_signup_requires_consent(client):
    client.post(
        reverse("accounts:signup"),
        {"email": "x@test.local", "password1": "Strong-pass-123", "password2": "Strong-pass-123"},
    )
    assert not User.objects.filter(email="x@test.local").exists()


def test_feed_redirects_to_profile_if_incomplete(client, db):
    user = User.objects.create_user(email="empty@test.local", password="pass12345!")
    client.force_login(user)
    response = client.get(reverse("matching:feed"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:profile_edit")


def test_profile_rejects_underage(client, seeker, city):
    client.force_login(seeker)
    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Юный",
            "birth_year": date.today().year - 15,
            "gender": "o",
            "city": city.pk,
            "schedule": "flex",
        },
    )
    assert response.status_code == 200  # форма вернулась с ошибкой
    seeker.profile.refresh_from_db()
    assert seeker.profile.display_name != "Юный"


# --- Сквозной сценарий: объявление → свайпы → мэтч → чат --------------------


def test_full_flow_listing_swipes_match_chat(client, make_user, city):
    owner = make_user(is_seeking=False)
    seeker = make_user()

    # Владелец публикует объявление
    client.force_login(owner)
    response = client.post(
        reverse("listings:create"),
        {
            "title": "Комната у Курской",
            "city": city.pk,
            "room_type": "room",
            "rent": 30000,
            "deposit": 0,
            "available_from": (date.today() + timedelta(days=3)).isoformat(),
            "min_term_months": 1,
            "flatmates_count": 1,
            "preferred_gender": "any",
            "description": "Светлая комната",
        },
    )
    assert response.status_code == 302
    listing = Listing.objects.get(title="Комната у Курской")
    assert listing.status == Listing.Status.ACTIVE

    # Ищущий видит объявление в ленте и лайкает через HTMX
    client.force_login(seeker)
    assert "Комната у Курской" in client.get(reverse("matching:feed")).content.decode()
    response = client.post(
        reverse("matching:seeker_swipe", args=[listing.pk]), {"decision": "like"}, HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    assert "Подходящие комнаты закончились" in response.content.decode()

    # Владелец видит входящий лайк и отвечает взаимностью — мэтч
    client.force_login(owner)
    assert (
        seeker.profile.display_name
        in client.get(reverse("matching:incoming_likes", args=[listing.pk])).content.decode()
    )
    response = client.post(
        reverse("matching:owner_swipe", args=[listing.pk, seeker.pk]), {"decision": "like"}, HTTP_HX_REQUEST="true"
    )
    match = Match.objects.get(listing=listing, seeker=seeker)
    # HTMX получает команду перейти на экран «Это мэтч!»
    assert response["HX-Redirect"] == reverse("matching:match", args=[match.pk])
    assert "Это мэтч" in client.get(response["HX-Redirect"]).content.decode()

    # Переписка
    client.post(reverse("messaging:send", args=[match.pk]), {"text": "Привет! Когда можно посмотреть?"})
    client.force_login(seeker)
    page = client.get(reverse("messaging:chat", args=[match.pk])).content.decode()
    assert "Когда можно посмотреть" in page
    assert Message.objects.get().read_at is not None  # прочитано при открытии


def test_premoderation_puts_listing_on_review(client, make_user, city, settings):
    settings.LISTINGS_PREMODERATION = True
    owner = make_user()
    client.force_login(owner)
    client.post(
        reverse("listings:create"),
        {
            "title": "На проверку",
            "city": city.pk,
            "room_type": "room",
            "rent": 30000,
            "deposit": 0,
            "available_from": date.today().isoformat(),
            "min_term_months": 1,
            "flatmates_count": 1,
            "preferred_gender": "any",
            "description": "Текст",
        },
    )
    assert Listing.objects.get(title="На проверку").status == Listing.Status.PENDING


def test_first_like_turns_on_seeking(client, make_user, listing):
    """Анкета становится видимой владельцам, как только человек начал лайкать."""
    user = make_user(is_seeking=False)
    client.force_login(user)
    client.post(reverse("matching:seeker_swipe", args=[listing.pk]), {"decision": "like"})
    user.profile.refresh_from_db()
    assert user.profile.is_seeking


# --- Доступ к чужим данным ---------------------------------------------------


def test_stranger_cannot_open_chat(client, make_user, seeker, listing):
    match = _make_match(seeker, listing)
    client.force_login(make_user())
    assert client.get(reverse("messaging:chat", args=[match.pk])).status_code == 404
    assert client.post(reverse("messaging:send", args=[match.pk]), {"text": "спам"}).status_code == 404
    assert not Message.objects.exists()


def test_cannot_write_to_closed_match(client, seeker, listing):
    match = _make_match(seeker, listing)
    client.force_login(seeker)
    client.post(reverse("messaging:close", args=[match.pk]))
    client.post(reverse("messaging:send", args=[match.pk]), {"text": "ещё одно"})
    assert not Message.objects.exists()


def test_cannot_edit_or_feed_foreign_listing(client, make_user, listing):
    client.force_login(make_user())
    assert client.get(reverse("listings:edit", args=[listing.pk])).status_code == 404
    assert client.get(reverse("matching:owner_feed", args=[listing.pk])).status_code == 404


def test_listing_has_no_address_only_metro_minutes(client, seeker, make_listing):
    from apps.listings.models import Listing

    assert "address" not in {f.name for f in Listing._meta.get_fields()}
    listing = make_listing(metro="Таганская", metro_walk_minutes=7, metro_transport_minutes=3)
    client.force_login(seeker)
    html = client.get(reverse("listings:detail", args=[listing.pk])).content.decode()
    assert "Таганская · 7 мин пешком · 3 мин на транспорте" in html
    assert "сообщит в чате" in html


def test_chat_shows_address_safety_note(client, seeker, make_listing):
    listing = make_listing(metro="Таганская", metro_walk_minutes=7)
    match = _make_match(seeker, listing)
    client.force_login(seeker)
    html = client.get(reverse("messaging:chat", args=[match.pk])).content.decode()
    assert "Хозяин сообщит адрес" in html
    client.force_login(listing.owner)
    html = client.get(reverse("messaging:chat", args=[match.pk])).content.decode()
    assert "Адрес сообщайте, только когда" in html
    assert "Давайте договоримся о просмотре. Адрес:" in html


def test_metro_minutes_are_validated(client, make_user, city):
    owner = make_user()
    client.force_login(owner)
    response = client.post(
        reverse("listings:create"),
        {
            "title": "Комната",
            "city": city.pk,
            "metro": "Таганская",
            "metro_walk_minutes": 500,
            "room_type": "room",
            "rent": 30000,
            "deposit": 0,
            "available_from": "2026-11-01",
            "min_term_months": 1,
            "flatmates_count": 1,
            "preferred_gender": "any",
            "description": "Хорошая комната",
        },
    )
    assert response.status_code == 200
    assert "metro_walk_minutes" in response.context["form"].errors


# --- Жалобы ------------------------------------------------------------------


def test_report_and_auto_hide(client, make_user, listing, settings):
    settings.AUTO_HIDE_AFTER_REPORTS = 2
    target = listing.owner
    for _ in range(2):
        client.force_login(make_user())
        client.post(
            reverse("moderation:report_user", args=[target.pk]),
            {"reason": "scam", "comment": "Просит предоплату", "listing": listing.pk},
        )
    assert Report.objects.filter(reported_user=target, listing=listing).count() == 2
    target.profile.refresh_from_db()
    assert target.profile.is_hidden


def test_one_user_cannot_hide_someone_alone(client, make_user, listing, settings):
    settings.AUTO_HIDE_AFTER_REPORTS = 2
    client.force_login(make_user())
    for _ in range(3):
        client.post(reverse("moderation:report_user", args=[listing.owner.pk]), {"reason": "spam"})
    listing.owner.profile.refresh_from_db()
    assert not listing.owner.profile.is_hidden
