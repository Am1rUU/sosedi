"""Данные для статистики, которых нет в основных таблицах.

- DailyVisit — человек заходил в этот день (для удержания по неделям и DAU/WAU).
- Experiment / ExperimentAssignment — A/B-тесты: кто в какой вариант попал и когда.

Тексты переписок и действия внутри страниц здесь не храним — только факты.
"""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class DailyVisit(models.Model):
    """Человек заходил на сайт в этот день (одна строка на человека в день)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_visits")
    date = models.DateField("день", db_index=True)

    class Meta:
        verbose_name = "визит"
        verbose_name_plural = "визиты по дням"
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="unique_daily_visit")]

    def __str__(self) -> str:
        return f"{self.user_id} — {self.date}"


class Experiment(models.Model):
    """A/B-тест. В коде вариант берётся так: ab.variant(user, "ключ") → "A" или "B"."""

    key = models.CharField(
        "ключ в коде",
        max_length=40,
        unique=True,
        validators=[RegexValidator(r"^[a-z0-9_]+$", "Только латинские буквы, цифры и _")],
        help_text="Например: feed_photo_first. По нему код узнаёт, какой вариант показать.",
    )
    name = models.CharField("название", max_length=120)
    hypothesis = models.TextField(
        "гипотеза",
        blank=True,
        help_text="Например: «Если показывать сначала фото, ищущие будут чаще лайкать → больше мэтчей»",
    )
    variants = models.CharField(
        "варианты",
        max_length=60,
        default="A,B",
        help_text="Через запятую. Первый — контрольный (как сейчас).",
    )
    is_active = models.BooleanField(
        "идёт", default=True, help_text="Выключенный тест всем показывает контрольный вариант"
    )
    started_at = models.DateTimeField("начат", auto_now_add=True)
    ended_at = models.DateTimeField("завершён", null=True, blank=True)

    class Meta:
        verbose_name = "A/B-тест"
        verbose_name_plural = "A/B-тесты"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"

    @property
    def variant_list(self) -> list[str]:
        return [v.strip() for v in self.variants.split(",") if v.strip()] or ["A"]


class ExperimentAssignment(models.Model):
    """Человек попал в вариант теста (записывается при первом показе)."""

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="experiment_assignments")
    variant = models.CharField("вариант", max_length=20)
    assigned_at = models.DateTimeField("показан впервые", auto_now_add=True)

    class Meta:
        verbose_name = "участник теста"
        verbose_name_plural = "участники тестов"
        constraints = [models.UniqueConstraint(fields=["experiment", "user"], name="unique_assignment")]

    def __str__(self) -> str:
        return f"{self.experiment.key}: {self.user_id} → {self.variant}"
