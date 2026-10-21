"""Удаление своих сообщений в чате."""

import pytest
from django.urls import reverse

from apps.matching.models import Swipe
from apps.matching.services import record_swipe
from apps.messaging.models import Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def chat(seeker, listing):
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    match = record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE).match
    message = Message.objects.create(match=match, sender=seeker, text="Мой номер 8-900-000-00-00")
    return match, message


def test_sender_deletes_message_for_both(client, chat, seeker, listing):
    match, message = chat
    client.force_login(seeker)
    response = client.post(reverse("messaging:delete", args=[match.pk, message.pk]), HTTP_HX_REQUEST="true")
    assert "Сообщение удалено" in response.content.decode()
    message.refresh_from_db()
    assert message.is_deleted
    assert message.text  # текст хранится только для разбора жалоб

    client.force_login(listing.owner)
    html = client.get(reverse("messaging:chat", args=[match.pk])).content.decode()
    assert "8-900" not in html and "Сообщение удалено" in html
    html = client.get(reverse("matching:matches") + "?role=owner").content.decode()
    assert "8-900" not in html


def test_cannot_delete_someone_elses_message(client, chat, listing, make_user):
    match, message = chat
    client.force_login(listing.owner)  # собеседник
    assert client.post(reverse("messaging:delete", args=[match.pk, message.pk])).status_code == 404
    client.force_login(make_user())  # посторонний
    assert client.post(reverse("messaging:delete", args=[match.pk, message.pk])).status_code == 404
    message.refresh_from_db()
    assert not message.is_deleted


def test_deleted_unread_message_does_not_count_as_new(client, chat, seeker, listing):
    match, message = chat
    client.force_login(seeker)
    client.post(reverse("messaging:delete", args=[match.pk, message.pk]))
    client.force_login(listing.owner)
    html = client.get(reverse("listings:my")).content.decode()
    assert 'aria-label="новых' not in html
