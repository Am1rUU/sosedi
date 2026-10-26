"""Оповещения об ошибках сайта сотрудникам в Telegram."""

import logging

import pytest
from django.test import RequestFactory

from apps.notifications import telegram
from apps.notifications.alerts import TelegramAlertHandler
from apps.notifications.models import NotificationSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def sent(settings, monkeypatch):
    settings.TELEGRAM_BOT_TOKEN = "1:x"
    messages = []
    monkeypatch.setattr(telegram, "send_message", lambda chat_id, text, *a, **k: messages.append((chat_id, text)))
    return messages


def _error_record(path="/feed/"):
    try:
        raise ValueError("что-то сломалось")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "django.request", logging.ERROR, __file__, 1, "Internal Server Error: %s", (path,), sys.exc_info()
        )
    record.request = RequestFactory().get(path)
    return record


def test_error_goes_to_staff_with_telegram_once_per_10_minutes(sent, make_user, django_user_model):
    admin = django_user_model.objects.create_superuser(email="adm@test.local", password="x")
    NotificationSettings.objects.create(user=admin, telegram_chat_id=111)
    regular = make_user()
    NotificationSettings.objects.create(user=regular, telegram_chat_id=222)

    handler = TelegramAlertHandler()
    handler.emit(_error_record())
    handler.emit(_error_record())  # та же ошибка — не дублируем

    assert [chat for chat, _ in sent] == [111]
    assert "GET /feed/" in sent[0][1] and "ValueError: что-то сломалось" in sent[0][1]


def test_no_token_no_alerts(settings, sent, django_user_model):
    settings.TELEGRAM_BOT_TOKEN = ""
    admin = django_user_model.objects.create_superuser(email="adm@test.local", password="x")
    NotificationSettings.objects.create(user=admin, telegram_chat_id=111)
    TelegramAlertHandler().emit(_error_record())
    assert sent == []
