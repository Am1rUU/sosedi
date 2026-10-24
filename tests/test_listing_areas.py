"""Площадь комнаты и квартиры в объявлении."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _post(client, city, **fields):
    data = {
        "title": "Комната",
        "city": city.pk,
        "room_type": "room",
        "rent": 30000,
        "deposit": 0,
        "available_from": "2026-11-01",
        "min_term_months": 1,
        "flatmates_count": 1,
        "preferred_gender": "any",
        "description": "Светлая комната",
        **fields,
    }
    return client.post(reverse("listings:create"), data)


def test_areas_saved_and_shown(client, make_user, city, seeker):
    owner = make_user(is_seeking=False)
    client.force_login(owner)
    _post(client, city, room_area=14, flat_area=65)
    listing = owner.listings.get()
    assert (listing.room_area, listing.flat_area) == (14, 65)

    client.force_login(seeker)
    html = client.get(reverse("listings:detail", args=[listing.pk])).content.decode()
    assert "Комната 14 м²" in html and "Квартира 65 м²" in html


def test_room_cannot_be_bigger_than_flat(client, make_user, city):
    client.force_login(make_user(is_seeking=False))
    response = _post(client, city, room_area=80, flat_area=40)
    assert response.status_code == 200
    assert "room_area" in response.context["form"].errors


def test_whole_flat_has_no_room_area(client, make_user, city):
    owner = make_user(is_seeking=False)
    client.force_login(owner)
    _post(client, city, room_type="whole", room_area=20, flat_area=40)
    listing = owner.listings.get()
    assert listing.room_area is None and listing.flat_area == 40


def test_areas_are_optional(client, make_user, city):
    owner = make_user(is_seeking=False)
    client.force_login(owner)
    _post(client, city)
    assert owner.listings.get().room_area is None


def test_kitchen_area_saved_shown_and_validated(client, make_user, city, seeker):
    owner = make_user(is_seeking=False)
    client.force_login(owner)
    response = _post(client, city, flat_area=40, kitchen_area=45)
    assert "kitchen_area" in response.context["form"].errors
    _post(client, city, room_area=14, flat_area=60, kitchen_area=9)
    listing = owner.listings.get()
    assert listing.kitchen_area == 9
    client.force_login(seeker)
    html = client.get(reverse("listings:detail", args=[listing.pk])).content.decode()
    assert "Кухня 9 м²" in html


def test_room_area_filter(client, make_user, city, make_listing):
    from apps.matching.services import seeker_feed

    make_listing(title="маленькая", room_area=9)
    make_listing(title="большая", room_area=18)
    make_listing(title="без площади")
    make_listing(title="квартира большая", room_type="whole", flat_area=40)
    make_listing(title="квартира маленькая", room_type="whole", flat_area=10)
    seeker = make_user(budget_max=None)
    client.force_login(seeker)
    client.post(reverse("matching:filters"), {"city": city.pk, "min_room_area": 15})
    seeker = type(seeker).objects.get(pk=seeker.pk)
    titles = sorted(listing.title for listing in seeker_feed(seeker))
    assert titles == ["без площади", "большая", "квартира большая"]
