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
