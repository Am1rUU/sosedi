"""«Вас лайкнули»: ищущий видит комнаты, хозяева которых лайкнули его анкету."""

import pytest
from django.urls import reverse

from apps.matching.models import Match, Swipe
from apps.matching.services import incoming_likes_for_seeker, record_swipe
from apps.moderation.services import block_user

pytestmark = pytest.mark.django_db


def _owner_likes(listing, seeker):
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)


def test_owner_like_shows_up_and_badge_counts(client, seeker, listing):
    _owner_likes(listing, seeker)
    assert list(incoming_likes_for_seeker(seeker)) == [listing]

    client.force_login(seeker)
    html = client.get(reverse("matching:matches")).content.decode()
    assert "Вас лайкнули" in html and listing.title in html
    assert 'class="tab-badge" aria-label="новых: 1"' in html


def test_like_back_from_list_creates_match_and_clears_it(client, seeker, listing):
    _owner_likes(listing, seeker)
    client.force_login(seeker)
    response = client.post(reverse("matching:seeker_swipe", args=[listing.pk]), {"decision": "like", "next": "matches"})
    match = Match.objects.get()
    assert response.url == reverse("matching:match", args=[match.pk])
    assert not incoming_likes_for_seeker(seeker).exists()


def test_pass_from_list_returns_to_matches_and_clears_it(client, seeker, listing):
    _owner_likes(listing, seeker)
    client.force_login(seeker)
    response = client.post(reverse("matching:seeker_swipe", args=[listing.pk]), {"decision": "pass", "next": "matches"})
    assert response.url == reverse("matching:matches") + "?role=seeker"
    assert not incoming_likes_for_seeker(seeker).exists()


def test_earlier_pass_does_not_hide_owner_like(seeker, listing):
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)
    Swipe.objects.filter(side=Swipe.Side.SEEKER).update(created_at="2026-01-01T00:00:00Z")
    _owner_likes(listing, seeker)
    assert list(incoming_likes_for_seeker(seeker)) == [listing]


def test_hidden_for_inactive_listing_and_blocked_owner(seeker, make_listing):
    paused = make_listing()
    blocked = make_listing()
    for listing in (paused, blocked):
        record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)
    paused.status = "paused"  # хозяин поставил объявление на паузу уже после лайка
    paused.save()
    block_user(seeker, blocked.owner)
    assert not incoming_likes_for_seeker(seeker).exists()
