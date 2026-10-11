"""Общие фикстуры для тестов: город, пользователи, объявления."""

from datetime import date, timedelta
from itertools import count

import pytest

from apps.accounts.models import User
from apps.geo.models import City
from apps.listings.models import Listing

_counter = count(1)


@pytest.fixture
def city(db):
    """Москва создаётся миграцией с начальными городами."""
    return City.objects.get(slug="moskva")


@pytest.fixture
def other_city(db):
    return City.objects.get(slug="kazan")


@pytest.fixture
def make_user(db, city):
    """Фабрика пользователей с заполненной анкетой ищущего."""

    def _make(**profile_fields):
        n = next(_counter)
        user = User.objects.create_user(email=f"user{n}@test.local", password="pass12345!")
        defaults = {
            "display_name": f"Пользователь {n}",
            "city": city,
            "is_seeking": True,
            "budget_max": 40000,
            "gender": "o",
        }
        defaults.update(profile_fields)
        for field, value in defaults.items():
            setattr(user.profile, field, value)
        user.profile.save()
        return user

    return _make


@pytest.fixture
def make_listing(db, city, make_user):
    """Фабрика активных объявлений."""

    def _make(owner=None, **fields):
        owner = owner or make_user(is_seeking=False)
        defaults = {
            "city": city,
            "title": "Комната у метро",
            "description": "Тихая светлая комната",
            "rent": 30000,
            "available_from": date.today() + timedelta(days=5),
            "status": Listing.Status.ACTIVE,
        }
        defaults.update(fields)
        return Listing.objects.create(owner=owner, **defaults)

    return _make


@pytest.fixture
def seeker(make_user):
    return make_user()


@pytest.fixture
def listing(make_listing):
    return make_listing()
