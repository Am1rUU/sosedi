"""Подтверждение почты и уведомления о мэтче и сообщениях (почта и Telegram)."""

import json
import re

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts import verification
from apps.accounts.models import User
from apps.matching.models import Swipe
from apps.matching.services import record_swipe
from apps.messaging.models import Message
from apps.notifications import telegram
from apps.notifications.models import NotificationSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def verified(make_user):
    """Фабрика пользователей с подтверждённой почтой."""

    def _make(**fields):
        user = make_user(**fields)
        User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())
        user.refresh_from_db()
        return user

    return _make


@pytest.fixture
def tg_calls(settings, monkeypatch):
    """Подменяем Telegram API: запоминаем вызовы вместо настоящих запросов."""
    settings.TELEGRAM_BOT_TOKEN = "123:test"
    calls = []

    def fake_call(method, payload=None, timeout=10):
        calls.append((method, payload or {}))
        if method == "getMe":
            return {"username": "sosedi_test_bot"}
        if method == "getWebhookInfo":
            return {"url": telegram.webhook_url()}
        return {}

    monkeypatch.setattr(telegram, "call", fake_call)
    return calls


def _like_both(seeker, listing):
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    return record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE).match


# --- Подтверждение почты ----------------------------------------------------


def test_signup_sends_verification_link_that_confirms_email(client, settings):
    settings.EMAIL_VERIFICATION_REQUIRED = True
    client.post(
        reverse("accounts:signup"),
        {
            "email": "new@test.local",
            "password1": "Strong-pass-123",
            "password2": "Strong-pass-123",
            "accept_terms": "on",
        },
    )
    user = User.objects.get(email="new@test.local")
    assert user.email_verified_at is None
    assert len(mail.outbox) == 1
    link = re.search(r"https?://\S+/accounts/verify/\S+/", mail.outbox[0].body).group(0)

    path = "/" + link.split("/", 3)[3]  # из полной ссылки берём путь
    client.get(path)
    user.refresh_from_db()
    assert user.email_verified_at is not None


def test_bad_or_foreign_token_does_not_verify(client, make_user):
    user = make_user()
    client.get(reverse("accounts:verify_email", args=["garbage-token"]))
    token = verification.make_token(user)
    user.email = "changed@test.local"
    user.save()
    client.get(reverse("accounts:verify_email", args=[token]))  # почта сменилась — старая ссылка не работает
    user.refresh_from_db()
    assert user.email_verified_at is None


def test_unverified_user_cannot_like_or_write_but_can_pass(client, settings, make_user, verified, make_listing):
    settings.EMAIL_VERIFICATION_REQUIRED = True
    seeker = make_user()
    listing = make_listing(owner=verified(is_seeking=False))
    with pytest.raises(ValidationError):
        record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.PASS)  # пропуск — можно

    settings.EMAIL_VERIFICATION_REQUIRED = False
    match = _like_both(seeker, listing)
    settings.EMAIL_VERIFICATION_REQUIRED = True
    client.force_login(seeker)
    client.post(reverse("messaging:send", args=[match.pk]), {"text": "Привет"})
    assert not Message.objects.exists()

    html = client.get(reverse("accounts:profile_edit")).content.decode()
    assert "Подтвердите почту" in html


def test_resend_is_rate_limited(client, settings, make_user):
    settings.EMAIL_VERIFICATION_REQUIRED = True
    user = make_user()
    client.force_login(user)
    for _ in range(5):
        client.post(reverse("accounts:resend_verification"))
    assert len(mail.outbox) == 3


# --- Уведомления на почту ---------------------------------------------------


def test_match_notifies_only_the_other_side(verified, make_listing):
    seeker = verified()
    listing = make_listing(owner=verified(is_seeking=False))
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    assert mail.outbox == []
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)  # второй лайк — владелец
    assert [m.to for m in mail.outbox] == [[seeker.email]]
    assert "мэтч" in mail.outbox[0].subject.lower()
    assert "/chat/" in mail.outbox[0].body


def test_message_notifications_are_throttled_per_chat(client, verified, make_listing):
    seeker = verified()
    listing = make_listing(owner=verified(is_seeking=False))
    match = _like_both(seeker, listing)
    mail.outbox.clear()

    client.force_login(seeker)
    for text in ("Привет!", "Когда можно посмотреть?", "Я свободна вечером"):
        client.post(reverse("messaging:send", args=[match.pk]), {"text": text})
    assert Message.objects.count() == 3
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [listing.owner.email]
    assert "Привет!" in mail.outbox[0].body


def test_email_notifications_can_be_turned_off(client, verified, make_listing):
    seeker = verified()
    listing = make_listing(owner=verified(is_seeking=False))
    client.force_login(seeker)
    client.post(reverse("notifications:preferences"), {})  # обе галочки сняты
    assert NotificationSettings.objects.get(user=seeker).email_enabled is False
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)  # мэтч — уведомление владельцу
    assert [m.to for m in mail.outbox] == [[listing.owner.email]]


def test_unverified_email_gets_no_notifications(make_user, verified, make_listing):
    seeker = make_user()  # почта не подтверждена (подтверждение в тестах не обязательно)
    listing = make_listing(owner=verified(is_seeking=False))
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)
    assert mail.outbox == []


# --- Telegram ---------------------------------------------------------------


def _webhook(client, settings, text, chat_id=555, secret=None):
    return client.post(
        reverse("telegram_webhook"),
        data=json.dumps({"message": {"text": text, "chat": {"id": chat_id, "type": "private", "username": "alice"}}}),
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret if secret is not None else settings.TELEGRAM_WEBHOOK_SECRET,
    )


def test_telegram_link_flow_and_notifications(client, settings, tg_calls, verified, make_listing):
    seeker = verified()
    client.force_login(seeker)
    response = client.post(reverse("notifications:telegram_connect"))
    assert response.url.startswith("https://t.me/sosedi_test_bot?start=")
    code = response.url.split("start=")[1]

    assert _webhook(client, settings, f"/start {code}", secret="wrong").status_code == 403
    _webhook(client, settings, f"/start {code}")
    prefs = NotificationSettings.objects.get(user=seeker)
    assert prefs.telegram_chat_id == 555 and prefs.telegram_username == "alice"

    tg_calls.clear()
    listing = make_listing(owner=verified(is_seeking=False))
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)
    sent = [p for m, p in tg_calls if m == "sendMessage"]
    assert len(sent) == 1 and sent[0]["chat_id"] == 555
    assert "Взаимный интерес" in sent[0]["text"]

    _webhook(client, settings, "/stop")
    assert NotificationSettings.objects.get(user=seeker).telegram_chat_id is None


def test_telegram_old_code_is_rejected(client, settings, tg_calls, verified):
    user = verified()
    prefs = NotificationSettings.objects.create(
        user=user, telegram_link_code="oldcode", telegram_link_created_at=timezone.now() - timezone.timedelta(hours=2)
    )
    _webhook(client, settings, "/start oldcode")
    prefs.refresh_from_db()
    assert prefs.telegram_chat_id is None


def test_status_page_has_email_and_telegram_blocks(client, django_user_model, tg_calls):
    admin = django_user_model.objects.create_superuser(email="adm@test.local", password="pass12345")
    client.force_login(admin)
    html = client.get(reverse("site_status")).content.decode()
    assert "Почта" in html and "@sosedi_test_bot" in html


@pytest.mark.django_db(transaction=True)
def test_background_sending_after_commit(settings, verified, make_listing):
    """Боевой режим: письмо уходит в фоновом потоке после сохранения мэтча."""
    import time

    settings.NOTIFICATIONS_ASYNC = True
    seeker = verified()
    listing = make_listing(owner=verified(is_seeking=False))
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)
    for _ in range(50):
        if mail.outbox:
            break
        time.sleep(0.05)
    assert [m.to for m in mail.outbox] == [[seeker.email]]
