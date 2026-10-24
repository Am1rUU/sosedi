"""Страница «Статистика»: метрики считаются верно на известных данных."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Invite, User
from apps.analytics import ab, metrics
from apps.analytics.models import DailyVisit, Experiment, ExperimentAssignment
from apps.matching import outcomes
from apps.matching.models import Match, Swipe
from apps.matching.services import record_swipe
from apps.messaging.models import Message

pytestmark = pytest.mark.django_db


def _match(seeker, listing):
    record_swipe(seeker, listing, seeker, Swipe.Side.SEEKER, Swipe.Decision.LIKE)
    return record_swipe(listing.owner, listing, seeker, Swipe.Side.OWNER, Swipe.Decision.LIKE).match


@pytest.fixture
def world(make_user, make_listing):
    """3 ищущих, 2 хозяина. Мэтчи: A↔комната1 (с ответом, нашли), B↔комната1 (без ответа). C только смотрел."""
    a, b, c = make_user(display_name="A"), make_user(display_name="B"), make_user(display_name="C")
    room1, room2 = make_listing(), make_listing()
    m1 = _match(a, room1)
    _match(b, room1)
    record_swipe(c, room2, c, Swipe.Side.SEEKER, Swipe.Decision.PASS)
    Message.objects.create(match=m1, sender=a, text="Привет")
    Message.objects.create(match=m1, sender=room1.owner, text="Здравствуйте")
    outcomes.record_found(room1.owner, room1, m1)
    outcomes.record_found(a, None, m1)
    return {"a": a, "b": b, "c": c, "room1": room1, "room2": room2}


def test_kpis_and_funnels(world):
    dash = metrics.build("30")
    kpi = {m.label: m for m in dash.kpis}
    assert kpi["Нашли через «Соседей»"].value == "2"
    assert kpi["Мэтчи"].value == "2"
    assert "50%" in kpi["Мэтчи"].sub  # формат: 50%, 33,3%  # ответ только в одном из двух

    seeker = {s.label: s.count for s in dash.seeker_funnel}
    assert seeker["Зарегистрировались"] == 3  # хозяева без свайпов комнат не считаются ищущими
    assert seeker["Смотрели комнаты"] == 3
    assert seeker["Лайкнули комнату"] == 2
    assert seeker["Получили мэтч"] == 2
    assert seeker["Получили ответ"] == 1
    assert seeker["Нашли жильё"] == 1

    owner = {s.label: s.count for s in dash.owner_funnel}
    assert owner["Создали объявление"] == 2
    assert owner["Лайкнули анкету"] == 1
    assert owner["Сдали комнату"] == 1


def test_fake_and_staff_users_are_excluded(world, django_user_model):
    User.objects.filter(pk=world["b"].pk).update(email="seeker9@fake.sosedi.local")
    django_user_model.objects.create_superuser(email="adm@test.local", password="x")
    dash = metrics.build("30")
    assert {s.label: s.count for s in dash.seeker_funnel}["Зарегистрировались"] == 2
    dash = metrics.build("30", include_fake=True)
    assert {s.label: s.count for s in dash.seeker_funnel}["Зарегистрировались"] == 3


def test_retention_cohorts(make_user):
    today = timezone.localdate()
    joined = timezone.now() - timedelta(days=15)
    u1, u2 = make_user(), make_user()
    User.objects.filter(pk__in=[u1.pk, u2.pk]).update(date_joined=joined)
    start = timezone.localtime(joined).date() - timedelta(days=timezone.localtime(joined).weekday())
    DailyVisit.objects.create(user=u1, date=start + timedelta(days=8))  # вернулся на 1-й неделе
    dash = metrics.build("90")
    row = next(r for r in dash.retention if r["start"] == start)
    assert row["size"] == 2
    assert row["cells"][0] == 50.0
    assert start + timedelta(weeks=4) > today and row["cells"][3] is None


def test_visit_is_recorded_once_per_day(client, make_user):
    user = make_user()
    client.force_login(user)
    client.get(reverse("accounts:profile_edit"))
    client.get(reverse("accounts:profile_edit"))
    assert DailyVisit.objects.filter(user=user).count() == 1


def test_channels(world, make_user):
    Invite.objects.create(channel="TG Аренда", used_by=world["a"])
    Invite.objects.create(channel="TG Аренда", used_by=world["c"])
    Invite.objects.create(channel="ВК Сокол")
    dash = metrics.build("30")
    tg = next(c for c in dash.channels if c["channel"] == "TG Аренда")
    assert (tg["sent"], tg["registered"], tg["active"], tg["matched"], tg["found"]) == (2, 2, 2, 1, 1)
    vk = next(c for c in dash.channels if c["channel"] == "ВК Сокол")
    assert vk["registered"] == 0


def test_ab_assignment_is_stable_and_inactive_returns_control(make_user):
    exp = Experiment.objects.create(key="photo_first", name="Фото первым", variants="A,B")
    user = make_user()
    first = ab.variant(user, "photo_first")
    assert first in ("A", "B")
    assert all(ab.variant(user, "photo_first") == first for _ in range(3))
    assert ExperimentAssignment.objects.count() == 1
    exp.is_active = False
    exp.save()
    assert ab.variant(make_user(), "photo_first") == "A"
    assert ab.variant(user, "unknown_test") == "A"


def test_ab_results_and_significance(make_user, make_listing):
    exp = Experiment.objects.create(key="t", name="Тест", variants="A,B")
    for i in range(60):
        user = make_user()
        variant = "A" if i % 2 else "B"
        ExperimentAssignment.objects.create(experiment=exp, user=user, variant=variant)
        if variant == "B" or i % 10 == 1:  # B получают мэтч все, A — каждый пятый
            _match(user, make_listing())
    dash = metrics.build("30")
    rows = {r["variant"]: r for r in dash.experiments[0]["rows"]}
    assert rows["A"]["verdict"] == "контроль"
    assert rows["B"]["matched_pct"] == "100%"
    assert rows["B"]["verdict"].startswith("лучше контроля")
    assert metrics._two_proportion_p(5, 50, 6, 50) > 0.05


def test_liveness_and_likes_histogram(world):
    Match.objects.update(created_at=timezone.now() - timedelta(days=20))
    dash = metrics.build("30")
    live = {m.label: m for m in dash.liveness}
    assert live["Мэтчи без ответа"].value == "50%"
    hist = {b["label"]: b["count"] for b in dash.likes_histogram}
    assert hist["1–4"] == 2  # два ищущих лайкнули по одной комнате в один день


def test_page_for_staff_only(client, world, make_user, django_user_model):
    client.force_login(make_user())
    assert client.get(reverse("analytics_dashboard")).status_code == 302
    admin = django_user_model.objects.create_superuser(email="adm@test.local", password="x")
    client.force_login(admin)
    html = client.get(reverse("analytics_dashboard") + "?period=7").content.decode()
    assert "Воронка ищущих" in html and "Нашли через «Соседей»" in html


def test_bar_widths_use_dot_decimal_for_css(client, world, django_user_model):
    """В стилях дробь должна быть с точкой (width:66.7%), иначе браузер рисует полосу на всю ширину."""
    import re

    admin = django_user_model.objects.create_superuser(email="adm2@test.local", password="x")
    client.force_login(admin)
    html = client.get(reverse("analytics_dashboard")).content.decode()
    assert not re.search(r"width:\d+,\d+%", html)
    assert not re.search(r"opacity:\d+,\d+", html)
