"""Команда seed_fake_users: 10 ищущих + 10 хозяев, без дублей, с фото из папки."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.geo.management.commands import seed_fake_users as cmd
from apps.listings.models import Listing, ListingPhoto
from apps.matching.services import owner_feed, seeker_feed

pytestmark = pytest.mark.django_db


@pytest.fixture
def moscow(db):
    from apps.geo.models import City

    return City.objects.get(slug="moskva")


def _fake_users():
    return User.objects.filter(email__endswith=f"@{cmd.FAKE_EMAIL_DOMAIN}")


def test_creates_20_users_and_10_listings_without_duplicates(moscow, tmp_path, monkeypatch):
    monkeypatch.setattr(cmd, "PHOTOS_DIR", tmp_path)  # пустая папка — без фото
    call_command("seed_fake_users")
    call_command("seed_fake_users")
    assert _fake_users().count() == 20
    assert Listing.objects.filter(owner__in=_fake_users(), status=Listing.Status.ACTIVE).count() == 10
    assert not any(u.has_usable_password() for u in _fake_users())


def test_fake_users_show_up_in_real_users_feeds(moscow, tmp_path, monkeypatch, make_user):
    monkeypatch.setattr(cmd, "PHOTOS_DIR", tmp_path)
    call_command("seed_fake_users")
    real_seeker = make_user(city=moscow, budget_max=60000)
    assert len(seeker_feed(real_seeker)) >= 5

    real_owner = make_user(city=moscow, is_seeking=False)
    my_listing = Listing.objects.create(
        owner=real_owner,
        city=moscow,
        title="Моя комната",
        description="-",
        rent=30000,
        available_from=timezone.localdate() + timedelta(days=3),
    )
    assert len(owner_feed(real_owner, my_listing)) >= 3


def test_uses_photos_from_folder_and_delete_cleans_up(moscow, tmp_path, monkeypatch, settings):
    for kind in ("people", "rooms"):
        (tmp_path / kind).mkdir()
        for n in range(4):
            Image.new("RGB", (900, 700), (40 * n, 120, 90)).save(tmp_path / kind / f"{n}.jpg")
    monkeypatch.setattr(cmd, "PHOTOS_DIR", tmp_path)
    call_command("seed_fake_users")

    assert all(u.profile.photo for u in _fake_users())
    assert ListingPhoto.objects.count() == 30  # по 3 на каждое из 10 объявлений
    call_command("seed_fake_users")
    assert ListingPhoto.objects.count() == 30  # повтор не дублирует фото

    from pathlib import Path

    def files_in_media():
        return [p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()]

    assert files_in_media()
    call_command("seed_fake_users", "--delete")
    assert not _fake_users().exists()
    assert ListingPhoto.objects.count() == 0
    assert files_in_media() == []  # фото удалены из хранилища
