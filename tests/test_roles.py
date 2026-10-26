"""Роли «Ищу комнату» / «Сдаю комнату», новое меню и колокольчик."""

import pytest
from django.urls import reverse

from apps.accounts import features, roles
from apps.accounts.models import FeatureFlag, Profile
from apps.matching.models import Swipe
from apps.matching.services import record_swipe, seeker_feed
from apps.notifications.models import InAppNotification

pytestmark = pytest.mark.django_db


def _flag(mode):
    FeatureFlag.objects.update_or_create(key="roles", defaults={"mode": mode})
    features.reset_cache("roles")


@pytest.fixture
def staff(make_user):
    user = make_user(role="")
    user.is_staff = True
    user.save()
    return user


# --- Выключатель --------------------------------------------------------------


def test_flag_starts_for_staff_only(make_user, staff):
    assert features.mode("roles") == "staff"
    assert roles.active(staff)
    assert not roles.active(make_user())


def test_old_menu_for_regular_users_new_for_staff(client, make_user, staff):
    client.force_login(make_user(role=Profile.Role.SEEKER))
    html = client.get(reverse("matching:matches")).content.decode()
    assert ">Мэтчи" in html and "Уведомления" not in html

    client.force_login(staff)
    staff.profile.role = Profile.Role.SEEKER
    staff.profile.save()
    html = client.get(reverse("matching:matches")).content.decode()
    assert "Уведомления" in html and reverse("accounts:search") in html


def test_flag_off_hides_role_pages(client, staff):
    _flag("off")
    client.force_login(staff)
    assert client.get(reverse("accounts:start")).url == reverse("matching:feed")
    assert client.post(reverse("accounts:switch_role"), {"role": "owner"}).status_code == 404


# --- Первый вход и переключение ----------------------------------------------


def test_no_role_goes_to_start_screen(client, staff):
    client.force_login(staff)
    assert client.get(reverse("matching:feed")).url == reverse("accounts:start")
    assert client.get(reverse("accounts:profile_edit")).url == reverse("accounts:start")
    assert "Что вы ищете?" in client.get(reverse("accounts:start")).content.decode()


def test_choose_seeker_opens_feed(client, staff):
    client.force_login(staff)
    response = client.post(reverse("accounts:start"), {"role": "seeker"})
    assert response.url == reverse("matching:feed")
    staff.profile.refresh_from_db()
    assert staff.profile.role == "seeker" and staff.profile.is_seeking


def test_choose_owner_without_room_goes_to_create(client, staff):
    client.force_login(staff)
    response = client.post(reverse("accounts:start"), {"role": "owner"})
    assert response.url == reverse("listings:create")
    staff.profile.refresh_from_db()
    assert staff.profile.role == "owner" and not staff.profile.is_seeking


def test_owner_search_opens_room_feed(client, staff, make_listing):
    listing = make_listing(owner=staff)
    roles.switch(staff, roles.OWNER)
    client.force_login(staff)
    assert client.get(reverse("accounts:search")).url == reverse("matching:owner_feed", args=[listing.pk])
    # Ленту комнат сдающему не показываем
    assert client.get(reverse("matching:feed")).url == reverse("matching:owner_feed", args=[listing.pk])


def test_switch_role_from_profile(client, staff, make_listing):
    make_listing(owner=staff)
    roles.switch(staff, roles.SEEKER)
    client.force_login(staff)
    response = client.post(reverse("accounts:switch_role"), {"role": "owner"})
    assert response.url == reverse("accounts:profile_edit")
    staff.profile.refresh_from_db()
    assert staff.profile.role == "owner" and not staff.profile.is_seeking
    html = client.get(reverse("accounts:profile_edit")).content.decode()
    assert "Моя комната" in html and 'name="budget_max"' not in html and 'name="is_seeking"' not in html


def test_seeker_profile_has_search_fields(client, staff):
    roles.switch(staff, roles.SEEKER)
    client.force_login(staff)
    html = client.get(reverse("accounts:profile_edit")).content.decode()
    assert 'name="budget_max"' in html and "Моя комната" not in html


def test_owner_profile_saves_without_seeker_fields(client, staff, city):
    roles.switch(staff, roles.OWNER)
    staff.profile.budget_max = 55000
    staff.profile.save()
    client.force_login(staff)
    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Анна",
            "city": city.pk,
            "gender": "f",
            "schedule": "flex",
            "smoker": "False",
            "has_pets": "False",
            "works_from_home": "False",
        },
    )
    assert response.status_code == 302
    staff.profile.refresh_from_db()
    assert staff.profile.display_name == "Анна" and staff.profile.budget_max == 55000


# --- Одна комната ---------------------------------------------------------------


def test_one_room_per_owner(client, staff, make_listing):
    listing = make_listing(owner=staff)
    roles.switch(staff, roles.OWNER)
    client.force_login(staff)
    assert client.get(reverse("listings:create")).url == reverse("listings:edit", args=[listing.pk])


# --- Сообщения и колокольчик по ролям ---------------------------------------


def test_messages_show_only_active_role(client, staff, make_listing, seeker):
    my_room = make_listing(owner=staff, title="Моя комната у парка")
    other_room = make_listing(title="Чужая комната")
    # Как хозяин: кто-то лайкнул мою комнату
    record_swipe(seeker, my_room, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    # Как ищущий: хозяин чужой комнаты лайкнул меня
    record_swipe(other_room.owner, other_room, staff, Swipe.Side.OWNER, Swipe.Decision.LIKE)

    client.force_login(staff)
    roles.switch(staff, roles.SEEKER)
    html = client.get(reverse("matching:matches")).content.decode()
    assert "Чужая комната" in html and "ждёт ответа" not in html

    roles.switch(staff, roles.OWNER)
    html = client.get(reverse("matching:matches")).content.decode()
    assert "Чужая комната" not in html and "1 человек ждёт ответа" in html


def test_bell_shows_active_role_and_marks_read(client, staff, make_listing, seeker):
    my_room = make_listing(owner=staff)
    record_swipe(seeker, my_room, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    note = InAppNotification.objects.get(user=staff)
    assert note.role == "owner"

    client.force_login(staff)
    roles.switch(staff, roles.SEEKER)
    assert "лайкнул вашу комнату" not in client.get(reverse("notifications:inbox")).content.decode()

    roles.switch(staff, roles.OWNER)
    html = client.get(reverse("matching:matches")).content.decode()
    assert 'href="/notifications/"' in html
    html = client.get(reverse("notifications:inbox")).content.decode()
    assert "лайкнул вашу комнату" in html
    note.refresh_from_db()
    assert note.read_at is not None


def test_match_notifies_both_sides(seeker, listing):
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE)
    assert InAppNotification.objects.filter(kind="match", user=seeker, role="seeker").exists()
    assert InAppNotification.objects.filter(kind="match", user=listing.owner, role="owner").exists()


# --- Видимость (когда роли включены всем) ------------------------------------


def test_room_hidden_when_owner_in_seeker_role(seeker, make_user, make_listing):
    owner = make_user(is_seeking=False)
    listing = make_listing(owner=owner)
    roles.switch(owner, roles.SEEKER)

    _flag("staff")
    assert listing in seeker_feed(seeker)  # пока роли только у сотрудников — ленты не меняются

    _flag("all")
    assert listing not in seeker_feed(seeker)
    roles.switch(owner, roles.OWNER)
    assert listing in seeker_feed(seeker)
