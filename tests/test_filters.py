"""Фильтры поиска — отдельно от анкеты и независимо от неё."""

import pytest
from django.urls import reverse

from apps.matching.models import SearchFilters
from apps.matching.services import filters_for, owner_feed, seeker_feed

pytestmark = pytest.mark.django_db


def _save_filters(client, city, **fields):
    data = {"city": city.pk, **fields}
    return client.post(reverse("matching:filters"), data)


def test_filters_start_from_profile_then_live_independently(client, make_user, city, listing):
    seeker = make_user(budget_max=35000, preferred_districts="Таганская")
    filters = filters_for(seeker)
    assert filters.rent_max == 35000 and filters.areas == "Таганская"

    client.force_login(seeker)
    _save_filters(client, city, rent_max=50000)
    seeker.profile.refresh_from_db()
    assert seeker.profile.budget_max == 35000  # анкета не изменилась
    assert SearchFilters.objects.get(user=seeker).rent_max == 50000

    # И наоборот: правка анкеты не трогает фильтры
    client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Аня",
            "gender": "f",
            "city": city.pk,
            "budget_max": 20000,
            "smoker": "False",
            "has_pets": "False",
            "works_from_home": "False",
            "schedule": "flex",
        },
    )
    seeker.profile.refresh_from_db()
    assert seeker.profile.budget_max == 20000
    assert SearchFilters.objects.get(user=seeker).rent_max == 50000


def test_owner_sees_anketa_not_filters(make_user, listing):
    """Хозяин видит ищущего по анкете: фильтры ищущего на ленту хозяина не влияют."""
    seeker = make_user(budget_max=40000)
    filters = filters_for(seeker)
    filters.rent_max = 5000  # ищет только очень дешёвое
    filters.save()
    assert seeker in owner_feed(listing.owner, listing)


@pytest.mark.parametrize(
    "fields, visible",
    [
        ({"rent_min": 31000}, ["дорогая"]),
        ({"rent_max": 25000}, []),
        ({"room_types": ["whole"]}, ["дорогая"]),
        ({"max_walk_minutes": 10}, ["дешёвая"]),
        ({"furnished_only": "on"}, ["дешёвая"]),
        ({"pets_needed": "on"}, ["дорогая"]),
        ({"areas": "Курская", "areas_only": "on"}, ["дорогая"]),
    ],
)
def test_each_filter_works(client, make_user, city, make_listing, fields, visible):
    make_listing(title="дешёвая", rent=30000, metro="Таганская", metro_walk_minutes=5, furnished=True)
    make_listing(
        title="дорогая",
        rent=40000,
        metro="Курская",
        metro_walk_minutes=20,
        furnished=False,
        room_type="whole",
        pets_allowed=True,
    )
    seeker = make_user(budget_max=None)
    client.force_login(seeker)
    response = _save_filters(client, city, **fields)
    assert response.status_code == 302
    seeker = type(seeker).objects.get(pk=seeker.pk)
    assert sorted(listing.title for listing in seeker_feed(seeker)) == sorted(visible)


def test_price_range_is_validated(client, make_user, city):
    client.force_login(make_user())
    response = _save_filters(client, city, rent_min=50000, rent_max=20000)
    assert response.status_code == 200
    assert "rent_max" in response.context["form"].errors


def test_reset_restores_values_from_profile(client, make_user, city):
    seeker = make_user(budget_max=33000)
    client.force_login(seeker)
    _save_filters(client, city, rent_max=90000)
    client.post(reverse("matching:filters"), {"reset": "1"})
    seeker = type(seeker).objects.get(pk=seeker.pk)
    assert filters_for(seeker).rent_max == 33000


def test_feed_filter_button_opens_filters_page(client, make_user):
    client.force_login(make_user())
    html = client.get(reverse("matching:feed")).content.decode()
    assert reverse("matching:filters") in html
    assert client.get(reverse("matching:filters")).status_code == 200
