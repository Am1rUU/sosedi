"""Фото в S3: загрузка, подписанные ссылки, удаление вместе с аккаунтом.

Настоящее хранилище не нужно: moto подменяет S3 у себя в памяти.
"""

import io
from datetime import date

import boto3
import pytest
from django.urls import reverse
from moto import mock_aws
from PIL import Image

from config.storage import s3_storage

pytestmark = pytest.mark.django_db

BUCKET = "sosedi-test"


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (90, 150, 120)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def s3(settings):
    """Поддельный S3 и хранилище фото, настроенное так же, как в проде (кроме адреса)."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        settings.STORAGES = {
            **settings.STORAGES,
            "default": s3_storage(BUCKET, "test", "test", endpoint_url=None, region="us-east-1"),
        }
        yield client


def _keys(client) -> list[str]:
    return [obj["Key"] for obj in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


def test_listing_photo_goes_to_bucket_with_signed_url(client, s3, make_user, city):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.listings.models import Listing

    owner = make_user()
    client.force_login(owner)
    client.post(
        reverse("listings:create"),
        {
            "title": "С фото в S3",
            "city": city.pk,
            "room_type": "room",
            "rent": 30000,
            "deposit": 0,
            "available_from": date.today().isoformat(),
            "min_term_months": 1,
            "flatmates_count": 1,
            "preferred_gender": "any",
            "description": "Текст",
            "photos": [SimpleUploadedFile("room.jpg", _jpeg(), content_type="image/jpeg")],
        },
    )
    photo = Listing.objects.get(title="С фото в S3").photos.get()

    keys = _keys(s3)
    assert len(keys) == 1 and keys[0].startswith("media/listings/")
    # Ссылка временная и подписанная — без подписи приватный бакет фото не отдаст
    assert "X-Amz-Signature=" in photo.image.url
    assert "X-Amz-Expires=21600" in photo.image.url
    # Страница объявления показывает фото по подписанной ссылке
    page = client.get(photo.listing.get_absolute_url()).content.decode()
    assert "X-Amz-Signature=" in page


def test_profile_photo_replacement_and_account_deletion_clean_bucket(client, s3, seeker, city):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(seeker)
    form = {
        "display_name": "Аня",
        "gender": "f",
        "city": city.pk,
        "schedule": "flex",
        "smoker": "False",
        "has_pets": "False",
        "works_from_home": "False",
    }
    client.post(reverse("accounts:profile_edit"), {**form, "photo": SimpleUploadedFile("a.jpg", _jpeg())})
    first = _keys(s3)
    assert len(first) == 1

    # Новое фото заменяет старое — старое удаляется из бакета
    client.post(reverse("accounts:profile_edit"), {**form, "photo": SimpleUploadedFile("b.jpg", _jpeg())})
    second = _keys(s3)
    assert len(second) == 1 and second != first

    # Удаление аккаунта стирает фото из бакета
    client.post(reverse("accounts:delete"), {"password": "pass12345!"})
    assert _keys(s3) == []


def test_s3_enabled_by_env(monkeypatch):
    """S3 включается переменной S3_BUCKET, и тогда приложение само не раздаёт фото."""
    import importlib

    import config.settings as project_settings

    monkeypatch.setenv("S3_BUCKET", "sosedi-photos")
    monkeypatch.setenv("S3_ACCESS_KEY", "key")
    monkeypatch.setenv("S3_SECRET_KEY", "secret")
    try:
        reloaded = importlib.reload(project_settings)
        options = reloaded.STORAGES["default"]["OPTIONS"]
        assert reloaded.STORAGES["default"]["BACKEND"] == "storages.backends.s3.S3Storage"
        assert options["bucket_name"] == "sosedi-photos"
        assert options["endpoint_url"] == "https://s3.twcstorage.ru"
        assert options["region_name"] == "ru-1"
        assert reloaded.SERVE_MEDIA is False
    finally:
        monkeypatch.delenv("S3_BUCKET")
        importlib.reload(project_settings)


def test_status_check_writes_to_bucket_and_cleans_up(s3):
    from config.status import check_storage

    check = check_storage()
    assert check.ok, check.details
    assert "S3 работает" in check.summary
    assert _keys(s3) == []  # тестовый файл удалён


def test_status_check_reports_s3_error(settings):
    with mock_aws():  # бакета нет — запись должна провалиться и показать ошибку
        settings.STORAGES = {
            **settings.STORAGES,
            "default": s3_storage("no-such-bucket", "test", "test", endpoint_url=None, region="us-east-1"),
        }
        from config.status import check_storage

        check = check_storage()
        assert not check.ok
        assert any("Ошибка" in line for line in check.details)


def test_status_check_lists_visible_buckets_on_wrong_name(settings):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="3b24945b-real-name")
        settings.STORAGES = {
            **settings.STORAGES,
            "default": s3_storage("display-name", "test", "test", endpoint_url=None, region="us-east-1"),
        }
        from config.status import check_storage

        check = check_storage()
        assert not check.ok
        assert any("3b24945b-real-name" in line for line in check.details)
