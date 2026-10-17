"""Тесты ядра продукта: свайпы, мэтчи, ленты."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.listings.models import Listing
from apps.matching.models import Match, Swipe
from apps.matching.services import (
    incoming_likes_for_listing,
    owner_feed,
    record_swipe,
    seeker_feed,
    user_matches,
)

LIKE, PASS = Swipe.Decision.LIKE, Swipe.Decision.PASS
SEEKER, OWNER = Swipe.Side.SEEKER, Swipe.Side.OWNER


# --- Мэтчи ------------------------------------------------------------------


def test_match_when_seeker_likes_first(seeker, listing):
    """Ищущий лайкнул первым, затем владелец — возникает мэтч."""
    first = record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    assert not first.is_new_match

    second = record_swipe(listing.owner, listing, seeker, OWNER, LIKE)
    assert second.is_new_match
    assert Match.objects.filter(listing=listing, seeker=seeker).count() == 1


def test_match_when_owner_likes_first(seeker, listing):
    """Порядок лайков не важен."""
    record_swipe(listing.owner, listing, seeker, OWNER, LIKE)
    result = record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    assert result.is_new_match


def test_no_match_when_one_side_passes(seeker, listing):
    record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    result = record_swipe(listing.owner, listing, seeker, OWNER, PASS)
    assert not result.is_new_match
    assert not Match.objects.exists()


def test_repeat_like_does_not_duplicate_match(seeker, listing):
    """Повторный лайк не создаёт второй мэтч и не считается новым."""
    record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    record_swipe(listing.owner, listing, seeker, OWNER, LIKE)
    again = record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    assert not again.is_new_match
    assert Match.objects.count() == 1
    assert Swipe.objects.count() == 2  # свайп обновился, а не задублировался


def test_changing_mind_from_pass_to_like_creates_match(seeker, listing):
    record_swipe(listing.owner, listing, seeker, OWNER, LIKE)
    record_swipe(seeker, listing, seeker, SEEKER, PASS)
    result = record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    assert result.is_new_match


def test_closed_match_reopens_on_mutual_like(seeker, listing):
    record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    match = record_swipe(listing.owner, listing, seeker, OWNER, LIKE).match
    match.is_closed = True
    match.save()

    result = record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    assert result.is_new_match
    match.refresh_from_db()
    assert not match.is_closed


def test_user_matches_visible_to_both_sides(seeker, listing):
    record_swipe(seeker, listing, seeker, SEEKER, LIKE)
    record_swipe(listing.owner, listing, seeker, OWNER, LIKE)
    assert user_matches(seeker).count() == 1
    assert user_matches(listing.owner).count() == 1


# --- Права на свайп ----------------------------------------------------------


def test_cannot_swipe_own_listing(listing):
    with pytest.raises(ValidationError):
        record_swipe(listing.owner, listing, listing.owner, SEEKER, LIKE)


def test_seeker_cannot_swipe_for_someone_else(seeker, make_user, listing):
    stranger = make_user()
    with pytest.raises(PermissionDenied):
        record_swipe(stranger, listing, seeker, SEEKER, LIKE)


def test_only_owner_can_swipe_people_for_listing(seeker, make_user, listing):
    stranger = make_user()
    with pytest.raises(PermissionDenied):
        record_swipe(stranger, listing, seeker, OWNER, LIKE)


def test_cannot_swipe_inactive_listing(seeker, listing):
    listing.status = Listing.Status.RENTED
    listing.save()
    with pytest.raises(ValidationError):
        record_swipe(seeker, listing, seeker, SEEKER, LIKE)


# --- Лента ищущего -----------------------------------------------------------


def test_seeker_feed_filters_city_budget_and_own(seeker, make_listing, other_city):
    good = make_listing(rent=30000)
    make_listing(rent=90000)  # дороже бюджета
    make_listing(city=other_city)  # другой город
    make_listing(owner=seeker)  # своё объявление
    make_listing(status=Listing.Status.PAUSED)  # на паузе

    assert seeker_feed(seeker) == [good]


def test_seeker_feed_allows_ten_percent_over_budget(make_user, make_listing):
    seeker = make_user(budget_max=30000)
    slightly_over = make_listing(rent=33000)
    make_listing(rent=34000)
    assert seeker_feed(seeker) == [slightly_over]


def test_seeker_feed_respects_gender_and_house_rules(make_user, make_listing):
    man_smoker = make_user(gender="m", smoker=True)
    make_listing(preferred_gender="f", smoking_allowed=True)  # только девушки
    make_listing(smoking_allowed=False)  # нельзя курить
    fits = make_listing(smoking_allowed=True)
    assert seeker_feed(man_smoker) == [fits]


def test_seeker_feed_hides_swiped_and_resurfaces_old_passes(seeker, make_listing, settings):
    liked = make_listing()
    passed = make_listing()
    record_swipe(seeker, liked, seeker, SEEKER, LIKE)
    record_swipe(seeker, passed, seeker, SEEKER, PASS)
    assert seeker_feed(seeker) == []

    # Пропуск «постарел» — карточка возвращается, лайкнутая — нет
    old = timezone.now() - timedelta(days=settings.FEED_RESURFACE_PASSED_AFTER_DAYS + 1)
    Swipe.objects.filter(listing=passed).update(created_at=old)
    assert seeker_feed(seeker) == [passed]


def test_seeker_feed_puts_listings_that_liked_me_first(seeker, make_listing):
    newer = make_listing(title="Новое")
    older_liked_me = make_listing(title="Владелец лайкнул")
    Listing.objects.filter(pk=older_liked_me.pk).update(created_at=timezone.now() - timedelta(days=10))
    record_swipe(older_liked_me.owner, older_liked_me, seeker, OWNER, LIKE)

    feed = seeker_feed(seeker)
    assert feed[0] == older_liked_me
    assert feed[0].liked_me is True
    assert feed[1] == newer


def test_seeker_feed_hides_listings_of_hidden_owner(seeker, listing):
    listing.owner.profile.is_hidden = True
    listing.owner.profile.save()
    assert seeker_feed(seeker) == []


# --- Лента владельца ---------------------------------------------------------


def test_owner_feed_filters_people(make_user, make_listing, other_city):
    listing = make_listing(rent=30000, preferred_gender="f", pets_allowed=False)
    good = make_user(gender="f", budget_max=30000)
    make_user(gender="m")  # не тот пол
    make_user(gender="f", budget_max=15000)  # бюджет мал
    make_user(gender="f", has_pets=True)  # с животными нельзя
    make_user(gender="f", city=other_city)  # другой город
    make_user(gender="f", is_seeking=False)  # не ищет
    make_user(gender="f", is_hidden=True)  # скрыт модератором

    assert owner_feed(listing.owner, listing) == [good]


def test_owner_feed_puts_people_who_liked_first(make_user, listing):
    regular = make_user()
    fan = make_user()
    record_swipe(fan, listing, fan, SEEKER, LIKE)
    feed = owner_feed(listing.owner, listing)
    assert feed[0] == fan
    assert regular in feed


def test_owner_feed_only_for_own_listing(make_user, listing):
    with pytest.raises(PermissionDenied):
        owner_feed(make_user(), listing)


def test_incoming_likes_excludes_answered(make_user, listing):
    waiting = make_user()
    answered = make_user()
    record_swipe(waiting, listing, waiting, SEEKER, LIKE)
    record_swipe(answered, listing, answered, SEEKER, LIKE)
    record_swipe(listing.owner, listing, answered, OWNER, PASS)
    assert list(incoming_likes_for_listing(listing)) == [waiting]


# --- Совместимость и экраны мэтчей ---------------------------------------------


def test_fit_reasons_shown_in_feed(make_user, make_listing):
    from datetime import date, timedelta

    seeker = make_user(
        budget_max=35000, preferred_districts="Таганская, Курская", move_in_date=date.today() + timedelta(days=30)
    )
    make_listing(rent=30000, metro="Таганская")
    listing = seeker_feed(seeker)[0]
    assert listing.fit_reasons == ["бюджет", "район", "дата заезда"]


def test_better_fit_goes_first(make_user, make_listing):
    seeker = make_user(budget_max=40000, preferred_districts="Сокол")
    plain = make_listing(title="Обычная")
    in_district = make_listing(title="У Сокола", metro="Сокол")
    Listing.objects.filter(pk=in_district.pk).update(created_at=timezone.now() - timedelta(days=3))
    assert seeker_feed(seeker)[:2] == [in_district, plain]
