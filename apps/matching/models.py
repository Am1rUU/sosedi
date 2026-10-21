"""Свайпы и мэтчи.

Как устроен мэтч:
- ищущий свайпает объявление (сторона SEEKER);
- владелец свайпает анкету ищущего в контексте своего объявления (сторона OWNER);
- если обе стороны поставили лайк для одной пары «объявление + ищущий», создаётся мэтч,
  и между ними открывается чат. Порядок лайков не важен.

Любой свайп однозначно описывается тройкой (объявление, ищущий, сторона),
поэтому ограничение уникальности простое и работает одинаково в SQLite и PostgreSQL.
"""

from django.conf import settings
from django.db import models


class Swipe(models.Model):
    """Решение одной стороны по паре «объявление + ищущий»: лайк или пропуск."""

    class Side(models.TextChoices):
        SEEKER = "seeker", "Ищущий оценил объявление"
        OWNER = "owner", "Владелец оценил ищущего"

    class Decision(models.TextChoices):
        LIKE = "like", "Лайк"
        PASS = "pass", "Пропуск"

    listing = models.ForeignKey(
        "listings.Listing", on_delete=models.CASCADE, related_name="swipes", verbose_name="объявление"
    )
    seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="swipes_as_seeker", verbose_name="ищущий"
    )
    side = models.CharField("кто свайпнул", max_length=6, choices=Side.choices)
    decision = models.CharField("решение", max_length=4, choices=Decision.choices)
    # created_at обновляется при повторном решении — нужен для «воскрешения» пропущенных карточек
    created_at = models.DateTimeField("когда", auto_now=True)

    class Meta:
        verbose_name = "свайп"
        verbose_name_plural = "свайпы"
        constraints = [
            models.UniqueConstraint(fields=["listing", "seeker", "side"], name="unique_swipe_per_side"),
        ]
        indexes = [
            models.Index(fields=["seeker", "side"]),
            models.Index(fields=["listing", "side", "decision"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_side_display()}: {self.get_decision_display()} ({self.listing_id}/{self.seeker_id})"


class Outcome(models.Model):
    """Итог поиска: человек нашёл комнату или сдал её.

    Главная метрика MVP — сколько пар реально договорились через сервис.
    Если договорились через «Соседей», заполнен match; если в другом месте — нет.
    """

    class Role(models.TextChoices):
        SEEKER = "seeker", "Нашёл комнату"
        OWNER = "owner", "Сдал комнату"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="outcomes", verbose_name="пользователь"
    )
    role = models.CharField("что произошло", max_length=6, choices=Role.choices)
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outcomes",
        verbose_name="объявление",
    )
    match = models.ForeignKey(
        "Match", on_delete=models.SET_NULL, null=True, blank=True, related_name="outcomes", verbose_name="с кем (мэтч)"
    )
    created_at = models.DateTimeField("когда", auto_now_add=True)

    class Meta:
        verbose_name = "итог поиска"
        verbose_name_plural = "итоги поиска"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        where = "через «Соседей»" if self.match_id else "в другом месте"
        return f"{self.user}: {self.get_role_display().lower()} {where}"

    @property
    def via_service(self) -> bool:
        return self.match_id is not None


class Match(models.Model):
    """Взаимный интерес: ищущий и владелец лайкнули друг друга по конкретному объявлению."""

    listing = models.ForeignKey(
        "listings.Listing", on_delete=models.CASCADE, related_name="matches", verbose_name="объявление"
    )
    seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_seeker", verbose_name="ищущий"
    )
    created_at = models.DateTimeField("когда", auto_now_add=True)
    # Любая сторона может закрыть мэтч (передумали, комната сдана и т.д.)
    is_closed = models.BooleanField("закрыт", default=False)

    class Meta:
        verbose_name = "мэтч"
        verbose_name_plural = "мэтчи"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["listing", "seeker"], name="unique_match"),
        ]

    def __str__(self) -> str:
        return f"Мэтч: {self.seeker} ↔ {self.listing}"

    @property
    def owner(self):
        """Владелец объявления — вторая сторона мэтча."""
        return self.listing.owner

    def participants(self) -> set[int]:
        """ID обоих участников — для проверки доступа к чату."""
        return {self.seeker_id, self.listing.owner_id}

    def other_side(self, user):
        """Собеседник для указанного пользователя."""
        return self.listing.owner if user.pk == self.seeker_id else self.seeker


class SearchFilters(models.Model):
    """Фильтры ленты комнат — что показывать человеку.

    Независимы от анкеты (анкета — то, что о человеке видят хозяева).
    При первом обращении заполняются из анкеты, дальше живут сами по себе.
    """

    class RoomType(models.TextChoices):
        ROOM = "room", "Комната"
        SHARED = "shared", "Место в комнате"
        WHOLE = "whole", "Квартира целиком"

    WALK_CHOICES = [(5, "до 5 минут"), (10, "до 10 минут"), (15, "до 15 минут"), (20, "до 20 минут")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="search_filters", verbose_name="пользователь"
    )
    city = models.ForeignKey(
        "geo.City", on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="город"
    )
    rent_min = models.PositiveIntegerField("цена от", null=True, blank=True)
    rent_max = models.PositiveIntegerField("цена до", null=True, blank=True)
    room_types = models.CharField("тип жилья", max_length=40, blank=True, help_text="Через запятую; пусто — любой")
    areas = models.CharField("станции метро или районы", max_length=255, blank=True)
    areas_only = models.BooleanField("показывать только эти станции и районы", default=False)
    max_walk_minutes = models.PositiveSmallIntegerField("пешком до метро", null=True, blank=True, choices=WALK_CHOICES)
    available_by = models.DateField("заезд не позже", null=True, blank=True)
    furnished_only = models.BooleanField("только с мебелью", default=False)
    bills_included_only = models.BooleanField("только с коммуналкой в цене", default=False)
    pets_needed = models.BooleanField("можно с животными", default=False)
    smoking_needed = models.BooleanField("можно курить", default=False)
    updated_at = models.DateTimeField("обновлены", auto_now=True)

    class Meta:
        verbose_name = "фильтры поиска"
        verbose_name_plural = "фильтры поиска"

    def __str__(self) -> str:
        return f"Фильтры: {self.user}"

    @property
    def room_type_list(self) -> list[str]:
        return [t for t in self.room_types.split(",") if t]

    @property
    def area_list(self) -> list[str]:
        return [a.strip() for a in self.areas.replace(";", ",").split(",") if a.strip()]
