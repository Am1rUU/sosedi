"""Расчёт метрик для страницы «Статистика».

Всё считается запросами к основным таблицам (свайпы, мэтчи, сообщения, жалобы)
плюс визиты по дням и A/B-участники. Фейковые пользователи и сотрудники
(админы, модераторы) по умолчанию исключены — они искажают воронку.

Структура повторяет «План развития»: главная метрика, воронки ищущих и хозяев,
«живость» площадки, удержание по недельным когортам, безопасность, готовность
к монетизации, каналы привлечения, A/B-тесты.
"""

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db.models import Count, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.accounts.models import Invite, Profile, User, VerificationRequest
from apps.listings.models import Listing
from apps.matching.models import Match, Outcome, Swipe
from apps.messaging.models import Message
from apps.moderation.models import Block, Report

from .models import DailyVisit, Experiment, ExperimentAssignment

FAKE_EMAIL_SUFFIX = "@fake.sosedi.local"
PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}


@dataclass
class Step:
    label: str
    count: int
    hint: str = ""
    pct_of_first: float = 0.0
    pct_of_prev: float | None = None


@dataclass
class Metric:
    label: str
    value: str
    hint: str = ""
    sub: str = ""


@dataclass
class Dashboard:
    period_label: str
    since: datetime | None
    kpis: list[Metric] = field(default_factory=list)
    seeker_funnel: list[Step] = field(default_factory=list)
    owner_funnel: list[Step] = field(default_factory=list)
    liveness: list[Metric] = field(default_factory=list)
    retention: list[dict] = field(default_factory=list)
    safety: list[Metric] = field(default_factory=list)
    likes_histogram: list[dict] = field(default_factory=list)
    likes_cap_share: str = "—"
    channels: list[dict] = field(default_factory=list)
    experiments: list[dict] = field(default_factory=list)


# --- Вспомогательное ----------------------------------------------------------


def real_users(include_fake: bool = False):
    qs = User.objects.filter(is_staff=False)
    if not include_fake:
        qs = qs.exclude(email__endswith=FAKE_EMAIL_SUFFIX)
    return qs


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _ru(number: float, digits: int = 1) -> str:
    """Число по-русски: 14,2 (а не 14.2), без лишнего «,0»."""
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _fmt_pct(part: int, whole: int) -> str:
    return f"{_ru(_pct(part, whole))}%" if whole else "—"


def _median(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes = seconds / 60
    if minutes < 60:
        return f"{max(1, round(minutes))} мин"
    hours = minutes / 60
    if hours < 48:
        return f"{_ru(hours)} ч"
    return f"{_ru(hours / 24)} дн"


def _funnel(steps: list[Step]) -> list[Step]:
    first = steps[0].count if steps else 0
    prev = None
    for step in steps:
        step.pct_of_first = _pct(step.count, first)
        step.pct_of_prev = _pct(step.count, prev) if prev is not None else None
        prev = step.count
    return steps


def _since_q(field_name: str, since):
    return Q(**{f"{field_name}__gte": since}) if since else Q()


def _replied_match_ids(match_ids) -> set[int]:
    """Мэтчи, где написали обе стороны (был ответ)."""
    senders = defaultdict(set)
    for match_id, sender_id in Message.objects.filter(match_id__in=match_ids).values_list("match_id", "sender_id"):
        senders[match_id].add(sender_id)
    return {mid for mid, s in senders.items() if len(s) >= 2}


# --- Сборка дашборда ----------------------------------------------------------


def build(period: str = "30", include_fake: bool = False) -> Dashboard:
    days = PERIODS.get(period, 30)
    now = timezone.now()
    since = now - timedelta(days=days) if days else None
    label = f"за {days} дн." if days else "за всё время"
    users = real_users(include_fake)
    user_ids = set(users.values_list("pk", flat=True))

    dash = Dashboard(period_label=label, since=since)
    _kpis(dash, users, user_ids, since, now)
    _seeker_funnel(dash, users, since)
    _owner_funnel(dash, user_ids, since)
    _liveness(dash, user_ids, since, now)
    _retention(dash, users, now)
    _safety(dash, user_ids, since)
    _likes_per_day(dash, user_ids, since)
    _channels(dash, user_ids, since)
    _experiments(dash, user_ids)
    return dash


def _kpis(dash, users, user_ids, since, now):
    matches = Match.objects.filter(_since_q("created_at", since), seeker_id__in=user_ids)
    match_ids = list(matches.values_list("pk", flat=True))
    replied = _replied_match_ids(match_ids)
    outcomes = Outcome.objects.filter(_since_q("created_at", since), user_id__in=user_ids)
    via = outcomes.filter(match__isnull=False)
    today = timezone.localdate(now)
    wau = DailyVisit.objects.filter(user_id__in=user_ids, date__gt=today - timedelta(days=7)).values("user").distinct()
    dau = DailyVisit.objects.filter(user_id__in=user_ids, date=today).count()

    dash.kpis = [
        Metric(
            "Нашли через «Соседей»",
            str(via.count()),
            "Главная метрика: люди ответили «Нашли», выбрав мэтч. Каждая сделка отмечается обеими сторонами "
            "по отдельности, поэтому одна пара может дать 2.",
            f"всего отметили «нашли»: {outcomes.count()}",
        ),
        Metric(
            "Мэтчи",
            str(len(match_ids)),
            "Взаимные лайки за период",
            f"с ответом: {_fmt_pct(len(replied), len(match_ids))}",
        ),
        Metric("Регистрации", str(users.filter(_since_q("date_joined", since)).count()), "Новые аккаунты за период"),
        Metric(
            "Активные за 7 дней",
            str(wau.count()),
            "Уникальные люди, заходившие за последние 7 дней (не зависит от выбранного периода)",
            f"сегодня: {dau}",
        ),
    ]


def _seeker_funnel(dash, users, since):
    cohort = users.filter(_since_q("date_joined", since))
    # Ищущие — все, кроме тех, кто только сдаёт (создал объявление и ни разу не свайпал комнаты)
    owners_only = cohort.filter(listings__isnull=False).exclude(swipes_as_seeker__side=Swipe.Side.SEEKER)
    cohort = cohort.exclude(pk__in=owners_only.values("pk"))
    ids = set(cohort.values_list("pk", flat=True))

    complete = Profile.objects.filter(user_id__in=ids).exclude(display_name="").exclude(city=None).count()
    seeker_swipes = Swipe.objects.filter(seeker_id__in=ids, side=Swipe.Side.SEEKER)
    swiped = seeker_swipes.values("seeker").distinct().count()
    liked = seeker_swipes.filter(decision=Swipe.Decision.LIKE).values("seeker").distinct().count()
    matches = Match.objects.filter(seeker_id__in=ids)
    matched = matches.values("seeker").distinct().count()
    with_msgs = matches.filter(messages__isnull=False).distinct()
    chatted = with_msgs.values("seeker").distinct().count()
    replied_ids = _replied_match_ids(with_msgs.values_list("pk", flat=True))
    replied = Match.objects.filter(pk__in=replied_ids).values("seeker").distinct().count()
    found = Outcome.objects.filter(user_id__in=ids, role=Outcome.Role.SEEKER).values("user").distinct().count()

    dash.seeker_funnel = _funnel(
        [
            Step("Зарегистрировались", len(ids), "Новые аккаунты за период, кроме тех, кто только сдаёт"),
            Step("Заполнили анкету", complete, "Есть имя и город"),
            Step("Смотрели комнаты", swiped, "Хотя бы один свайп в ленте"),
            Step("Лайкнули комнату", liked),
            Step("Получили мэтч", matched),
            Step("Начали переписку", chatted, "В мэтче есть хотя бы одно сообщение"),
            Step("Получили ответ", replied, "В переписке писали обе стороны"),
            Step("Нашли жильё", found, "Ответили «Нашли» (через «Соседей» или в другом месте)"),
        ]
    )


def _owner_funnel(dash, user_ids, since):
    listings = Listing.objects.filter(_since_q("created_at", since), owner_id__in=user_ids)
    owner_ids = set(listings.values_list("owner_id", flat=True))
    listing_ids = list(listings.values_list("pk", flat=True))
    owner_swipes = Swipe.objects.filter(listing_id__in=listing_ids, side=Swipe.Side.OWNER)
    swiped = owner_swipes.values("listing__owner").distinct().count()
    liked = owner_swipes.filter(decision=Swipe.Decision.LIKE).values("listing__owner").distinct().count()
    matches = Match.objects.filter(listing_id__in=listing_ids)
    matched = matches.values("listing__owner").distinct().count()
    with_msgs = matches.filter(messages__isnull=False).distinct()
    chatted = with_msgs.values("listing__owner").distinct().count()
    replied_ids = _replied_match_ids(with_msgs.values_list("pk", flat=True))
    replied = Match.objects.filter(pk__in=replied_ids).values("listing__owner").distinct().count()
    rented = (
        Outcome.objects.filter(listing_id__in=listing_ids, role=Outcome.Role.OWNER).values("user").distinct().count()
    )

    dash.owner_funnel = _funnel(
        [
            Step("Создали объявление", len(owner_ids), "Хозяева, создавшие объявление за период"),
            Step("Смотрели анкеты", swiped, "Хотя бы один свайп в ленте анкет"),
            Step("Лайкнули анкету", liked),
            Step("Получили мэтч", matched),
            Step("Начали переписку", chatted),
            Step("Получили ответ", replied),
            Step("Сдали комнату", rented, "Отметили «Сдано» в вопросе «Нашли соседа?»"),
        ]
    )


def _liveness(dash, user_ids, since, now):
    week_ago = now - timedelta(days=7)
    # 1. Доля комнат, получивших мэтч в первые 7 дней (только комнаты старше 7 дней)
    old_enough = Listing.objects.filter(_since_q("created_at", since), owner_id__in=user_ids, created_at__lte=week_ago)
    first_match = dict(
        Match.objects.filter(listing__in=old_enough)
        .values("listing")
        .annotate(first=Min("created_at"))
        .values_list("listing", "first")
    )
    created = dict(old_enough.values_list("pk", "created_at"))
    matched_7d = sum(1 for pk, first in first_match.items() if first - created[pk] <= timedelta(days=7))

    # 2. Медианное время до первого мэтча у комнаты
    all_listings = dict(
        Listing.objects.filter(_since_q("created_at", since), owner_id__in=user_ids).values_list("pk", "created_at")
    )
    firsts = dict(
        Match.objects.filter(listing_id__in=all_listings)
        .values("listing")
        .annotate(first=Min("created_at"))
        .values_list("listing", "first")
    )
    to_first_match = [(firsts[pk] - all_listings[pk]).total_seconds() for pk in firsts]

    # 3. Сколько лайков от хозяев получает анкета ищущего за первую неделю
    new_seekers = dict(
        User.objects.filter(pk__in=user_ids, date_joined__lte=week_ago)
        .filter(_since_q("date_joined", since))
        .filter(profile__is_seeking=True)
        .values_list("pk", "date_joined")
    )
    likes_first_week = Counter()
    for seeker_id, liked_at in Swipe.objects.filter(
        seeker_id__in=new_seekers, side=Swipe.Side.OWNER, decision=Swipe.Decision.LIKE
    ).values_list("seeker_id", "created_at"):
        if liked_at - new_seekers[seeker_id] <= timedelta(days=7):
            likes_first_week[seeker_id] += 1
    likes_median = _median([likes_first_week.get(pk, 0) for pk in new_seekers])

    # 4. Время от первого лайка пары до мэтча (как быстро отвечают взаимностью)
    matches = list(
        Match.objects.filter(_since_q("created_at", since), seeker_id__in=user_ids).values_list(
            "pk", "listing_id", "seeker_id", "created_at"
        )
    )
    first_like = {
        (listing_id, seeker_id): t
        for listing_id, seeker_id, t in Swipe.objects.filter(
            listing_id__in={m[1] for m in matches}, decision=Swipe.Decision.LIKE
        )
        .values("listing_id", "seeker_id")
        .annotate(t=Min("created_at"))
        .values_list("listing_id", "seeker_id", "t")
    }
    like_to_match = [
        (created_at - first_like[(lid, sid)]).total_seconds()
        for _, lid, sid, created_at in matches
        if (lid, sid) in first_like
    ]

    # 5. Время первого ответа в чате и «умершие» мэтчи
    match_ids = [m[0] for m in matches]
    by_match = defaultdict(list)
    for mid, sender, t in (
        Message.objects.filter(match_id__in=match_ids)
        .order_by("created_at")
        .values_list("match_id", "sender_id", "created_at")
    ):
        by_match[mid].append((sender, t))
    reply_times = []
    for msgs in by_match.values():
        first_sender, first_t = msgs[0]
        reply = next((t for s, t in msgs if s != first_sender), None)
        if reply:
            reply_times.append((reply - first_t).total_seconds())
    old_matches = [m for m in matches if m[3] <= now - timedelta(days=14)]
    replied = _replied_match_ids([m[0] for m in old_matches])
    dead = len(old_matches) - len(replied)

    dash.liveness = [
        Metric(
            "Комнаты с мэтчем за 7 дней",
            _fmt_pct(matched_7d, len(created)),
            "Из комнат, опубликованных за период и старше недели. Ориентир теста — больше половины.",
            f"{matched_7d} из {len(created)}",
        ),
        Metric("До первого мэтча у комнаты", _fmt_duration(_median(to_first_match)), "Медиана, от публикации"),
        Metric(
            "Лайков на анкету за 1-ю неделю",
            "—" if likes_median is None else _ru(likes_median),
            "Медиана лайков от хозяев новым ищущим за первые 7 дней",
        ),
        Metric("От лайка до мэтча", _fmt_duration(_median(like_to_match)), "Медиана: как быстро отвечают взаимностью"),
        Metric("Первый ответ в чате", _fmt_duration(_median(reply_times)), "Медиана от первого сообщения до ответа"),
        Metric(
            "Мэтчи без ответа",
            _fmt_pct(dead, len(old_matches)),
            "Мэтчи старше 14 дней, где не писали обе стороны. Чем меньше, тем лучше.",
            f"{dead} из {len(old_matches)}",
        ),
    ]


def _retention(dash, users, now):
    """Недельные когорты по дате регистрации: доля, вернувшихся на 1–4-й неделе."""
    today = timezone.localdate(now)
    this_monday = today - timedelta(days=today.weekday())
    rows = []
    for weeks_back in range(7, -1, -1):
        start = this_monday - timedelta(weeks=weeks_back)
        end = start + timedelta(days=7)
        cohort = list(
            users.filter(date_joined__date__gte=start, date_joined__date__lt=end).values_list("pk", flat=True)
        )
        if not cohort:
            continue
        visits = defaultdict(set)
        for user_id, day in DailyVisit.objects.filter(user_id__in=cohort, date__gte=start).values_list(
            "user_id", "date"
        ):
            visits[(day - start).days // 7].add(user_id)
        cells = []
        for week in range(1, 5):
            if start + timedelta(weeks=week) > today:
                cells.append(None)  # неделя ещё не наступила
            else:
                cells.append(_pct(len(visits[week]), len(cohort)))
        rows.append({"start": start, "size": len(cohort), "cells": cells})
    dash.retention = rows


def _safety(dash, user_ids, since):
    active_listings = Listing.objects.filter(owner_id__in=user_ids).exclude(status=Listing.Status.BLOCKED).count()
    reports = Report.objects.filter(_since_q("created_at", since))
    reaction = [
        (resolved - created).total_seconds()
        for created, resolved in reports.filter(resolved_at__isnull=False).values_list("created_at", "resolved_at")
    ]
    verifications = VerificationRequest.objects.filter(_since_q("created_at", since))
    review = [
        (r - c).total_seconds()
        for c, r in verifications.filter(reviewed_at__isnull=False).values_list("created_at", "reviewed_at")
    ]
    reviewed = verifications.exclude(status=VerificationRequest.Status.PENDING)
    approved = reviewed.filter(status=VerificationRequest.Status.APPROVED).count()
    verified_users = Profile.objects.filter(user_id__in=user_ids, verified_at__isnull=False).count()

    dash.safety = [
        Metric(
            "Жалобы на 100 объявлений",
            _ru(100 * reports.count() / active_listings) if active_listings else "—",
            "Жалобы за период на 100 неудалённых объявлений",
            f"жалоб: {reports.count()}, ждут решения: {reports.filter(status=Report.Status.OPEN).count()}",
        ),
        Metric("Реакция модерации", _fmt_duration(_median(reaction)), "Медиана от жалобы до решения"),
        Metric(
            "Блокировки в чате",
            str(Block.objects.filter(_since_q("created_at", since)).count()),
            "Люди заблокировали собеседника",
        ),
        Metric(
            "Скрыто после жалоб",
            str(Profile.objects.filter(user_id__in=user_ids, is_hidden=True).count()),
            "Анкеты, скрытые автоматически или модератором",
        ),
        Metric(
            "Подтвердили профиль",
            _fmt_pct(verified_users, len(user_ids)),
            "Доля пользователей с отметкой ✓",
            f"заявок одобрено: {_fmt_pct(approved, reviewed.count())}, проверка за {_fmt_duration(_median(review))}",
        ),
    ]


def _likes_per_day(dash, user_ids, since):
    """Сколько лайков в день ставят ищущие — сигнал для лимита (решение MVP: ~20 в день)."""
    per_day = (
        Swipe.objects.filter(
            _since_q("created_at", since), seeker_id__in=user_ids, side=Swipe.Side.SEEKER, decision=Swipe.Decision.LIKE
        )
        .annotate(day=TruncDate("created_at"))
        .values("seeker", "day")
        .annotate(n=Count("pk"))
        .values_list("n", flat=True)
    )
    buckets = [("1–4", 1, 4), ("5–9", 5, 9), ("10–19", 10, 19), ("20+", 20, 10**9)]
    counts = Counter()
    for n in per_day:
        for name, lo, hi in buckets:
            if lo <= n <= hi:
                counts[name] += 1
    total = sum(counts.values())
    top = max(counts.values(), default=0)
    dash.likes_histogram = [
        {"label": name, "count": counts[name], "pct": _pct(counts[name], total), "bar": _pct(counts[name], top)}
        for name, _, _ in buckets
    ]
    dash.likes_cap_share = _fmt_pct(counts["20+"], total)


def _channels(dash, user_ids, since):
    invites = Invite.objects.filter(_since_q("created_at", since))
    rows = defaultdict(lambda: {"sent": 0, "registered": set()})
    for channel, used_by in invites.values_list("channel", "used_by"):
        row = rows[channel or "Без канала"]
        row["sent"] += 1
        if used_by and used_by in user_ids:
            row["registered"].add(used_by)
    result = []
    for channel, row in rows.items():
        reg = row["registered"]
        active = _active_ids(reg)
        matched = _matched_times(reg).keys()
        found = Outcome.objects.filter(user_id__in=reg).values("user").distinct().count()
        result.append(
            {
                "channel": channel,
                "sent": row["sent"],
                "registered": len(reg),
                "active": len(active),
                "matched": len(matched),
                "found": found,
                "active_rate": _fmt_pct(len(active), len(reg)),
                "match_rate": _fmt_pct(len(matched), len(reg)),
            }
        )
    dash.channels = sorted(result, key=lambda r: (-r["registered"], r["channel"]))


def _active_ids(ids) -> set[int]:
    """Кто хоть раз свайпал — как ищущий или как хозяин."""
    as_seeker = Swipe.objects.filter(seeker_id__in=ids, side=Swipe.Side.SEEKER).values_list("seeker_id", flat=True)
    as_owner = Swipe.objects.filter(listing__owner_id__in=ids, side=Swipe.Side.OWNER).values_list(
        "listing__owner_id", flat=True
    )
    return set(as_seeker) | set(as_owner)


def _first_times(*querysets) -> dict:
    """Самое раннее время события для каждого человека по нескольким источникам."""
    first = {}
    for qs in querysets:
        for uid, t in qs:
            if uid not in first or t < first[uid]:
                first[uid] = t
    return first


def _matched_times(ids) -> dict:
    """Первый мэтч каждого человека — как ищущего или как хозяина."""
    return _first_times(
        Match.objects.filter(seeker_id__in=ids)
        .values("seeker_id")
        .annotate(t=Min("created_at"))
        .values_list("seeker_id", "t"),
        Match.objects.filter(listing__owner_id__in=ids)
        .values("listing__owner_id")
        .annotate(t=Min("created_at"))
        .values_list("listing__owner_id", "t"),
    )


def _two_proportion_p(x1: int, n1: int, x2: int, n2: int) -> float | None:
    """p-значение двустороннего z-теста для разницы двух долей."""
    if min(n1, n2) == 0:
        return None
    p = (x1 + x2) / (n1 + n2)
    if p in (0, 1):
        return None
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (x1 / n1 - x2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def _experiments(dash, user_ids):
    """Для каждого теста: участники по вариантам и доли «лайкнул», «мэтч», «нашёл» после попадания в тест."""
    result = []
    for exp in Experiment.objects.all()[:10]:
        assignments = list(
            ExperimentAssignment.objects.filter(experiment=exp, user_id__in=user_ids).values_list(
                "variant", "user_id", "assigned_at"
            )
        )
        groups = defaultdict(list)
        for variant, user_id, at in assignments:
            groups[variant].append((user_id, at))
        rows = []
        for variant in exp.variant_list + sorted(set(groups) - set(exp.variant_list)):
            members = groups.get(variant, [])
            since_of = dict(members)
            ids = list(since_of)

            def after_assignment(first_times: dict, since_of=since_of) -> int:
                """Сколько участников сделали это уже после попадания в тест."""
                return sum(1 for uid, t in first_times.items() if uid in since_of and t >= since_of[uid])

            liked = after_assignment(
                _first_times(
                    Swipe.objects.filter(seeker_id__in=ids, side=Swipe.Side.SEEKER, decision=Swipe.Decision.LIKE)
                    .values("seeker_id")
                    .annotate(t=Min("created_at"))
                    .values_list("seeker_id", "t")
                )
            )
            matched = after_assignment(_matched_times(ids))
            found = after_assignment(
                _first_times(
                    Outcome.objects.filter(user_id__in=ids)
                    .values("user_id")
                    .annotate(t=Min("created_at"))
                    .values_list("user_id", "t")
                )
            )
            rows.append({"variant": variant, "n": len(ids), "liked": liked, "matched": matched, "found": found})
        control = rows[0] if rows else None
        for row in rows:
            row["liked_pct"] = _fmt_pct(row["liked"], row["n"])
            row["matched_pct"] = _fmt_pct(row["matched"], row["n"])
            row["found_pct"] = _fmt_pct(row["found"], row["n"])
            if row is control:
                row["verdict"] = "контроль"
                continue
            p = _two_proportion_p(row["matched"], row["n"], control["matched"], control["n"])
            if p is None:
                row["verdict"] = "мало данных"
            elif p < 0.05:
                better = row["matched"] / row["n"] > control["matched"] / control["n"]
                row["verdict"] = f"{'лучше' if better else 'хуже'} контроля (p = {_ru(p, 3)})"
            else:
                row["verdict"] = f"разница не доказана (p = {_ru(p, 2)})"
        result.append({"experiment": exp, "rows": rows})
    dash.experiments = result
