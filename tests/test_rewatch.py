"""«Посмотреть ещё раз»: пропущенные карточки возвращаются в ленту, лайкнутые — нет."""

import pytest
from django.urls import reverse

from apps.matching.models import Swipe
from apps.matching.services import owner_feed, record_swipe, seeker_feed

pytestmark = pytest.mark.django_db


def test_seeker_rewatch_returns_passed_but_not_liked(client, seeker, make_listing):
    passed = make_listing(title="Пропущенная")
    liked = make_listing(title="Лайкнутая")
    record_swipe(seeker, passed, seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)
    record_swipe(seeker, liked, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    assert seeker_feed(seeker) == []

    client.force_login(seeker)
    html = client.get(reverse("matching:feed")).content.decode()
    assert "Посмотреть ещё раз" in html

    client.post(reverse("matching:rewatch_feed"))
    seeker.profile.refresh_from_db()
    titles = [listing.title for listing in seeker_feed(seeker)]
    assert titles == ["Пропущенная"]


def test_passing_again_after_rewatch_hides_card_again(seeker, make_listing, client):
    listing = make_listing()
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)
    client.force_login(seeker)
    client.post(reverse("matching:rewatch_feed"))
    seeker.profile.refresh_from_db()
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)
    assert seeker_feed(seeker) == []


def test_no_rewatch_button_when_nothing_was_passed(client, seeker):
    client.force_login(seeker)
    html = client.get(reverse("matching:feed")).content.decode()
    assert "закончились" in html
    assert "Посмотреть ещё раз" not in html


def test_owner_rewatch_per_listing(client, make_user, listing):
    person = make_user(display_name="Пропущенный")
    record_swipe(listing.owner, listing, person, Swipe.Side.OWNER, Swipe.Decision.PASS)
    assert person not in owner_feed(listing.owner, listing)

    client.force_login(listing.owner)
    html = client.get(reverse("matching:owner_feed", args=[listing.pk])).content.decode()
    assert "Посмотреть ещё раз" in html
    client.post(reverse("matching:rewatch_owner_feed", args=[listing.pk]))
    listing.refresh_from_db()
    assert person in owner_feed(listing.owner, listing)


def test_cannot_rewatch_foreign_listing(client, make_user, listing):
    client.force_login(make_user())
    assert client.post(reverse("matching:rewatch_owner_feed", args=[listing.pk])).status_code == 404
