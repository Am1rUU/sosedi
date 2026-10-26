"""Страница «Состояние сайта» в админке."""

import pytest
from django.urls import reverse

from config.status import check_database, check_settings, check_storage


@pytest.mark.django_db
def test_status_page_requires_staff(client, django_user_model):
    url = reverse("site_status")
    assert client.get(url).status_code == 302  # аноним → на вход в админку
    user = django_user_model.objects.create_user(email="u@example.com", password="pass12345")
    client.force_login(user)
    assert client.get(url).status_code == 302  # обычный пользователь тоже не пускается


@pytest.mark.django_db
def test_status_page_for_admin(client, django_user_model):
    admin = django_user_model.objects.create_superuser(email="a@example.com", password="pass12345")
    client.force_login(admin)
    response = client.get(reverse("site_status"))
    assert response.status_code == 200
    assert "База данных" in response.content.decode()
    assert "Хранилище фото" in response.content.decode()


@pytest.mark.django_db
def test_database_check_reports_vendor():
    from django.db import connection

    check = check_database()
    assert check.ok == (connection.vendor != "sqlite")
    assert any("Пользователей" in line for line in check.details)


@pytest.mark.django_db
def test_storage_check_writes_and_cleans_up(settings, tmp_path):
    check = check_storage()
    assert any("записан" in line for line in check.details)
    assert not list((tmp_path).glob("status-check/*"))


def test_settings_check_hides_secret_values(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "super-secret-value")
    check = check_settings()
    text = " ".join(check.details)
    assert "DB_PASSWORD" in text
    assert "super-secret-value" not in text


@pytest.mark.django_db
def test_one_broken_check_does_not_break_page(client, django_user_model, monkeypatch):
    import config.status as status

    def boom():
        raise RuntimeError("сломалось внутри проверки")

    monkeypatch.setattr(status, "check_telegram", boom)
    admin = django_user_model.objects.create_superuser(email="a2@example.com", password="pass12345")
    client.force_login(admin)
    response = client.get(reverse("site_status"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "RuntimeError: сломалось внутри проверки" in html
    assert "База данных" in html
