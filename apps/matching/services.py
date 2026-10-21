"""Бизнес-логика мэтчинга: запись свайпов, создание мэтчей и сборка ленты.

Логика вынесена из представлений (views) в отдельный модуль, чтобы:
- её было легко покрыть тестами без HTTP-запросов;
- позже переиспользовать в API для мобильного приложения.

Платных ограничений на количество свайпов в MVP нет: продукт полностью бесплатный.
Есть только защитный порог от ботов (SWIPE_LIMIT_PER_HOUR), который человек не заметит.
Если монетизация понадобится, проверку платного лимита нужно добавить в record_swipe().
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, QuerySet, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.listings.models import Listing
from apps.moderation.services import blocked_user_ids, is_blocked_between
from config import ratelimit

from .models import Match, Swipe


@dataclass
class SwipeResult:
    """Результат свайпа: сам свайп и мэтч, если он возник прямо сейчас."""

    swipe: Swipe
    match: Match | None = None

    @property
    def is_new_match(self) -> bool:
        return self.match is not None


# --- Свайпы и мэтчи ---------------------------------------------------------


def _validate_swipe(actor: User, listing: Listing, seeker: User, side: str) -> None:
    """Проверяет, что пользователь имеет право на этот свайп.

    - Ищущий свайпает только за себя и не может лайкнуть своё же объявление.
    - Владелец свайпает только по своим объявлениям и не может выбрать сам себя.
    """
    if side == Swipe.Side.SEEKER:
        if actor.pk != seeker.pk:
            raise PermissionDenied("Ищущий может свайпать только за себя")
        if listing.owner_id == actor.pk:
            raise ValidationError("Нельзя свайпать собственное объявление")
    elif side == Swipe.Side.OWNER:
        if listing.owner_id != actor.pk:
            raise PermissionDenied("Свайпать анкеты можно только по своему объявлению")
        if seeker.pk == actor.pk:
            raise ValidationError("Нельзя свайпать собственную анкету")
    else:
        raise ValidationError("Неизвестная сторона свайпа")

    if listing.status != Listing.Status.ACTIVE:
        raise ValidationError("Объявление сейчас неактивно")

    # Между заблокировавшими друг друга людьми никаких действий быть не может
    other = listing.owner if side == Swipe.Side.SEEKER else seeker
    if is_blocked_between(actor, other):
        raise ValidationError("Действие недоступно")


def record_swipe(actor: User, listing: Listing, seeker: User, side: str, decision: str) -> SwipeResult:
    """Записывает свайп и, если интерес взаимный, создаёт мэтч.

    Повторный свайп по той же паре обновляет решение (например, пользователь
    передумал и лайкнул ранее пропущенную карточку).

    Всё выполняется в одной транзакции, а уникальное ограничение на Match
    гарантирует, что при одновременных встречных лайках мэтч будет один.
    """
    _validate_swipe(actor, listing, seeker, side)
    if decision not in Swipe.Decision.values:
        raise ValidationError("Неизвестное решение")

    # Лайк — действие в сторону другого человека: только с подтверждённой почтой
    if decision == Swipe.Decision.LIKE and not actor.can_interact:
        raise ValidationError("Подтвердите почту, чтобы ставить лайки, — ссылка в письме, которое мы отправили.")

    # Защита от ботов, которые лайкают всех подряд
    if ratelimit.is_limited("swipe", str(actor.pk), settings.SWIPE_LIMIT_PER_HOUR, 60 * 60):
        raise ValidationError("Слишком много свайпов подряд. Сделайте паузу и возвращайтесь чуть позже.")

    with transaction.atomic():
        swipe, _ = Swipe.objects.update_or_create(
            listing=listing,
            seeker=seeker,
            side=side,
            defaults={"decision": decision},
        )

        if decision != Swipe.Decision.LIKE:
            return SwipeResult(swipe=swipe)

        # Ищем встречный лайк другой стороны по той же паре
        other_side = Swipe.Side.OWNER if side == Swipe.Side.SEEKER else Swipe.Side.SEEKER
        mutual = Swipe.objects.filter(
            listing=listing, seeker=seeker, side=other_side, decision=Swipe.Decision.LIKE
        ).exists()
        if not mutual:
            return SwipeResult(swipe=swipe)

        # Мэтч мог уже существовать (например, лайк поставлен повторно) — тогда не дублируем
        try:
            with transaction.atomic():
                match, created = Match.objects.get_or_create(listing=listing, seeker=seeker)
        except IntegrityError:
            # Встречный запрос успел создать мэтч параллельно — просто берём его
            match, created = Match.objects.get(listing=listing, seeker=seeker), False

        if match.is_closed:
            # Если стороны снова лайкнули друг друга после закрытия — открываем заново
            match.is_closed = False
            match.save(update_fields=["is_closed"])
            created = True

    if created:
        from apps.notifications.services import notify_match

        notify_match(match, actor)
    return SwipeResult(swipe=swipe, match=match if created else None)


def user_matches(user: User) -> QuerySet[Match]:
    """Все открытые мэтчи пользователя — и как ищущего, и как владельца."""
    return (
        Match.objects.filter(Q(seeker=user) | Q(listing__owner=user), is_closed=False)
        .select_related("listing", "listing__owner__profile", "seeker__profile", "listing__city")
        .order_by("-created_at")
    )


# --- Лента ------------------------------------------------------------------


def activity_bucket(user_prefix: str = "") -> tuple[Case, Coalesce]:
    """Насколько недавно человек заходил: 0 — недавно, 1 — пару недель назад, 2 — давно.

    Если человек ещё ни разу не заходил после появления учёта визитов,
    считаем от даты регистрации.
    """
    now = timezone.now()
    seen = Coalesce(F(f"{user_prefix}last_seen_at"), F(f"{user_prefix}date_joined"))
    return Case(
        When(_seen__gte=now - timedelta(days=settings.ACTIVITY_FRESH_DAYS), then=Value(0)),
        When(_seen__gte=now - timedelta(days=settings.ACTIVITY_STALE_DAYS), then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    ), seen


def _with_activity(qs: QuerySet, user_prefix: str = "") -> QuerySet:
    """Добавляет к выборке признак активности и убирает тех, кто пропал надолго."""
    bucket, seen = activity_bucket(user_prefix)
    hide_before = timezone.now() - timedelta(days=settings.ACTIVITY_HIDE_DAYS)
    return qs.annotate(_seen=seen).filter(_seen__gte=hide_before).annotate(activity=bucket)


def _resurface_cutoff():
    """Момент, раньше которого пропущенные карточки снова можно показывать."""
    return timezone.now() - timedelta(days=settings.FEED_RESURFACE_PASSED_AFTER_DAYS)


def seeker_feed(user: User, limit: int | None = None) -> list[Listing]:
    """Лента объявлений для ищущего.

    Порядок фильтрации и ранжирования (см. архитектуру):
    1. Жёсткие фильтры: город, бюджет, пол, свои объявления не показываем.
    2. Исключаем уже оценённые: лайкнутые — навсегда, пропущенные — на N дней.
    3. Сначала объявления, владельцы которых уже лайкнули этого человека.
    4. Затем совместимость по образу жизни и свежесть.
    """
    profile: Profile = user.profile
    limit = limit or settings.FEED_BATCH_SIZE
    if not profile.city_id:
        return []

    qs = Listing.objects.visible().filter(city_id=profile.city_id).exclude(owner=user)
    qs = qs.exclude(owner_id__in=blocked_user_ids(user))

    # Бюджет: допускаем превышение на 10%, люди часто готовы немного добавить
    if profile.budget_max:
        qs = qs.filter(rent__lte=int(profile.budget_max * 1.1))

    # Пол: объявление «только женщины» не показываем мужчинам и наоборот
    if profile.gender == Profile.Gender.MALE:
        qs = qs.exclude(preferred_gender=Listing.GenderPreference.FEMALE)
    elif profile.gender == Profile.Gender.FEMALE:
        qs = qs.exclude(preferred_gender=Listing.GenderPreference.MALE)

    # Несовместимые правила дома отсекаем сразу
    if profile.smoker:
        qs = qs.filter(smoking_allowed=True)
    if profile.has_pets:
        qs = qs.filter(pets_allowed=True)

    # Исключаем уже оценённые этим человеком объявления
    my_swipes = Swipe.objects.filter(listing=OuterRef("pk"), seeker=user, side=Swipe.Side.SEEKER)
    already_decided = my_swipes.filter(
        Q(decision=Swipe.Decision.LIKE) | Q(decision=Swipe.Decision.PASS, created_at__gte=_resurface_cutoff())
    )
    qs = qs.exclude(Exists(already_decided))

    # Признак «владелец уже лайкнул вас» — такие карточки поднимаем наверх
    owner_liked_me = Swipe.objects.filter(
        listing=OuterRef("pk"), seeker=user, side=Swipe.Side.OWNER, decision=Swipe.Decision.LIKE
    )
    qs = qs.annotate(liked_me=Exists(owner_liked_me))

    # Объявления владельцев, которые давно не заходили, опускаем, а пропавших больше 30 дней — скрываем
    qs = _with_activity(qs, "owner__")

    qs = qs.select_related("city", "owner__profile").prefetch_related("photos")
    qs = qs.order_by("-liked_me", "activity", "-created_at")

    # Берём с запасом и досортировываем по совместимости в Python — на MVP этого достаточно
    candidates = list(qs[: limit * 3])
    for listing in candidates:
        # Причины совместимости показываются в карточке строкой «Подходит вам: …»
        listing.fit_reasons = fit_reasons(profile, listing)
    candidates.sort(key=lambda listing: (not listing.liked_me, listing.activity, -_listing_score(listing.fit_reasons)))
    return candidates[:limit]


# Вес каждой причины совместимости при сортировке ленты
_FIT_WEIGHTS = {"район": 3, "дата заезда": 2, "бюджет": 1}


def fit_reasons(profile: Profile, listing: Listing) -> list[str]:
    """Чем объявление подходит человеку — короткие причины для карточки."""
    reasons = []
    # Цена в пределах бюджета (в ленту допускаются и чуть дороже, но «подходит» — только в бюджете)
    if profile.budget_max and listing.rent <= profile.budget_max:
        reasons.append("бюджет")
    # Совпадение по району или метро из пожеланий
    wishes = (profile.preferred_districts or "").lower()
    if wishes and (
        (listing.district and listing.district.lower() in wishes) or (listing.metro and listing.metro.lower() in wishes)
    ):
        reasons.append("район")
    # Комната свободна к желаемой дате заезда
    if profile.move_in_date and listing.available_from <= profile.move_in_date:
        reasons.append("дата заезда")
    return reasons


def _listing_score(reasons: list[str]) -> int:
    """Балл совместимости для сортировки (чем больше, тем выше в ленте)."""
    return sum(_FIT_WEIGHTS.get(reason, 0) for reason in reasons)


def owner_feed(user: User, listing: Listing, limit: int | None = None) -> list[User]:
    """Лента анкет ищущих для владельца по конкретному объявлению.

    Логика зеркальная ленте ищущего: город, бюджет, пол, правила дома,
    исключение уже оценённых, наверх — те, кто уже лайкнул это объявление.
    """
    if listing.owner_id != user.pk:
        raise PermissionDenied("Можно смотреть анкеты только для своего объявления")
    limit = limit or settings.FEED_BATCH_SIZE

    qs = User.objects.filter(
        is_active=True,
        profile__is_seeking=True,
        profile__is_hidden=False,
        profile__city_id=listing.city_id,
    ).exclude(pk=user.pk)
    qs = qs.exclude(profile__display_name="")
    qs = qs.exclude(pk__in=blocked_user_ids(user))

    # Бюджет ищущего должен покрывать хотя бы 90% цены (или не указан)
    qs = qs.filter(Q(profile__budget_max__isnull=True) | Q(profile__budget_max__gte=int(listing.rent * 0.9)))

    # Пожелания владельца по полу соседа
    if listing.preferred_gender == Listing.GenderPreference.MALE:
        qs = qs.filter(profile__gender=Profile.Gender.MALE)
    elif listing.preferred_gender == Listing.GenderPreference.FEMALE:
        qs = qs.filter(profile__gender=Profile.Gender.FEMALE)

    # Правила дома
    if not listing.smoking_allowed:
        qs = qs.filter(profile__smoker=False)
    if not listing.pets_allowed:
        qs = qs.filter(profile__has_pets=False)

    # Уже оценённые владельцем анкеты по этому объявлению
    decided = Swipe.objects.filter(listing=listing, seeker=OuterRef("pk"), side=Swipe.Side.OWNER).filter(
        Q(decision=Swipe.Decision.LIKE) | Q(decision=Swipe.Decision.PASS, created_at__gte=_resurface_cutoff())
    )
    qs = qs.exclude(Exists(decided))

    # Те, кто уже лайкнул это объявление, — в начало ленты
    seeker_liked = Swipe.objects.filter(
        listing=listing, seeker=OuterRef("pk"), side=Swipe.Side.SEEKER, decision=Swipe.Decision.LIKE
    )
    qs = qs.annotate(liked_me=Exists(seeker_liked))

    # Совместимость: заезд к дате, когда комната свободна
    qs = qs.annotate(
        date_fit=Case(
            When(profile__move_in_date__gte=listing.available_from, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    )
    # Активные — выше, пропавшие больше 30 дней — не показываются
    qs = _with_activity(qs)
    qs = qs.select_related("profile", "profile__city").order_by(
        "-liked_me", "activity", "-date_fit", "-profile__updated_at"
    )
    return list(qs[:limit])


def incoming_likes_for_listing(listing: Listing) -> QuerySet[User]:
    """Ищущие, которые лайкнули объявление, но владелец ещё не ответил.

    В MVP доступно всем бесплатно (в Tinder аналог — платная функция).
    """
    owner_decided = Swipe.objects.filter(listing=listing, seeker=OuterRef("pk"), side=Swipe.Side.OWNER)
    return (
        User.objects.filter(
            swipes_as_seeker__listing=listing,
            swipes_as_seeker__side=Swipe.Side.SEEKER,
            swipes_as_seeker__decision=Swipe.Decision.LIKE,
            is_active=True,
            profile__is_hidden=False,
        )
        .exclude(Exists(owner_decided))
        .exclude(pk__in=blocked_user_ids(listing.owner))
        .select_related("profile")
        .distinct()
    )
