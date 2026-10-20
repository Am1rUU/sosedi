"""Активность аккаунтов и вопрос «Нашли соседа/комнату?»."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.listings.models import Listing
from apps.matching import outcomes
from apps.matching.models import Match, Outcome, Swipe
from apps.matching.services import owner_feed, record_swipe, seeker_feed
from apps.messaging.models import Message

pytestmark = pytest.mark.django_db


def _seen(user, days_ago):
    User.objects.filter(pk=user.pk).update(last_seen_at=timezone.now() - timedelta(days=days_ago))


def _match_with_chat(seeker, listing, days_ago=5) -> Match:
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    match = record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE).match
    Message.objects.create(match=match, sender=seeker, text="Здравствуйте!")
    Match.objects.filter(pk=match.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    match.refresh_from_db()
    return match


# --- Последний визит --------------------------------------------------------


def test_visit_updates_last_seen_not_more_often_than_10_minutes(client, seeker):
    client.force_login(seeker)
    client.get(reverse("accounts:profile_edit"))
    seeker.refresh_from_db()
    first = seeker.last_seen_at
    assert first is not None

    client.get(reverse("accounts:profile_edit"))
    seeker.refresh_from_db()
    assert seeker.last_seen_at == first  # второй клик сразу же — без записи в базу


def test_returning_after_long_absence_shows_welcome_back(client, seeker):
    _seen(seeker, 40)
    client.force_login(seeker)
    html = client.get(reverse("accounts:profile_edit"), follow=True).content.decode()
    assert "С возвращением" in html


# --- Ленты ------------------------------------------------------------------


def test_seeker_feed_hides_owners_gone_for_a_month_and_ranks_active_first(seeker, make_listing):
    active = make_listing(title="Активный хозяин")
    sleepy = make_listing(title="Был две недели назад")
    gone = make_listing(title="Пропал")
    _seen(active.owner, 1)
    _seen(sleepy.owner, 20)
    _seen(gone.owner, 45)

    titles = [listing.title for listing in seeker_feed(seeker)]
    assert "Пропал" not in titles
    assert titles.index("Активный хозяин") < titles.index("Был две недели назад")


def test_owner_feed_hides_inactive_seekers(make_user, listing):
    fresh = make_user(display_name="Свежий")
    gone = make_user(display_name="Пропавший")
    _seen(fresh, 0)
    _seen(gone, 60)
    names = [u.profile.display_name for u in owner_feed(listing.owner, listing)]
    assert "Свежий" in names
    assert "Пропавший" not in names


def test_never_seen_user_counts_from_signup_date(seeker, make_listing):
    listing = make_listing()
    User.objects.filter(pk=listing.owner.pk).update(last_seen_at=None, date_joined=timezone.now() - timedelta(days=60))
    assert listing not in seeker_feed(seeker)


# --- Вопрос «Нашли?» --------------------------------------------------------


def test_no_prompt_right_after_match_or_without_chat(seeker, listing):
    _match_with_chat(seeker, listing, days_ago=1)
    assert outcomes.pending_prompt(seeker) is None
    assert outcomes.pending_prompt(listing.owner) is None


def test_prompts_after_few_days_of_chat(seeker, listing):
    _match_with_chat(seeker, listing, days_ago=5)
    assert outcomes.pending_prompt(listing.owner).kind == "owner_found"
    assert outcomes.pending_prompt(seeker).kind == "seeker_found"


def test_banner_shows_and_snooze_hides_it(client, seeker, listing):
    _match_with_chat(seeker, listing)
    client.force_login(seeker)
    assert "Нашли комнату?" in client.get(reverse("matching:matches")).content.decode()

    client.post(reverse("matching:found_snooze"), {"next": reverse("matching:matches")})
    assert "Нашли комнату?" not in client.get(reverse("matching:matches")).content.decode()
    assert outcomes.pending_prompt(User.objects.get(pk=seeker.pk)) is None


def test_owner_marks_rented_with_match(client, seeker, listing):
    match = _match_with_chat(seeker, listing)
    client.force_login(listing.owner)
    url = reverse("matching:found") + f"?listing={listing.pk}"
    assert seeker.profile.display_name in client.get(url).content.decode()

    client.post(url, {"listing": listing.pk, "choice": match.pk})
    listing.refresh_from_db()
    assert listing.status == Listing.Status.RENTED
    outcome = Outcome.objects.get()
    assert outcome.role == Outcome.Role.OWNER and outcome.match == match and outcome.via_service
    match.refresh_from_db()
    assert not match.is_closed  # чат остаётся
    assert listing not in seeker_feed(seeker)


def test_seeker_found_elsewhere_hides_profile_from_owners(client, seeker, listing):
    _match_with_chat(seeker, listing)
    other_listing = Listing.objects.create(
        owner=listing.owner,
        city=listing.city,
        title="Ещё комната",
        description="-",
        rent=30000,
        available_from=listing.available_from,
    )
    client.force_login(seeker)
    client.post(reverse("matching:found"), {"choice": "elsewhere"})
    seeker.profile.refresh_from_db()
    assert not seeker.profile.is_seeking
    assert Outcome.objects.get().via_service is False
    assert seeker not in owner_feed(listing.owner, other_listing)


def test_cannot_mark_foreign_listing_or_foreign_match(client, seeker, listing, make_user, make_listing):
    stranger = make_user()
    client.force_login(stranger)
    assert client.get(reverse("matching:found") + f"?listing={listing.pk}").status_code == 404

    match = _match_with_chat(seeker, listing)
    client.post(reverse("matching:found"), {"choice": match.pk})  # чужой мэтч
    assert not Outcome.objects.exists()


def test_listing_confirm_prompt_and_answer(client, listing):
    Listing.objects.filter(pk=listing.pk).update(updated_at=timezone.now() - timedelta(days=40))
    prompt = outcomes.pending_prompt(listing.owner)
    assert prompt.kind == "listing_confirm" and prompt.listing == listing

    client.force_login(listing.owner)
    client.post(reverse("matching:listing_confirm", args=[listing.pk]))
    assert outcomes.pending_prompt(listing.owner) is None


def test_status_page_shows_outcomes(client, django_user_model, seeker, listing):
    match = _match_with_chat(seeker, listing)
    outcomes.record_found(listing.owner, listing, match)
    admin = django_user_model.objects.create_superuser(email="adm@test.local", password="pass12345")
    client.force_login(admin)
    html = client.get(reverse("site_status")).content.decode()
    assert "Нашли соседа или комнату: 1 (через «Соседей»: 1)" in html
