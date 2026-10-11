"""Жалобы пользователей.

Жалоба всегда направлена на пользователя и при необходимости уточняет объявление.
Модератор разбирает очередь в админке. После N открытых жалоб от разных людей
анкета скрывается автоматически до проверки (см. AUTO_HIDE_AFTER_REPORTS).
"""

from django.conf import settings
from django.db import models


class Report(models.Model):
    """Жалоба на пользователя или его объявление."""

    class Reason(models.TextChoices):
        SCAM = "scam", "Мошенничество, просит предоплату"
        AGENT = "agent", "Агент или риелтор под видом собственника"
        FAKE = "fake", "Фейковые фото или данные"
        RUDE = "rude", "Оскорбления или угрозы"
        SPAM = "spam", "Спам или реклама"
        DISCRIMINATION = "discrimination", "Дискриминация"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        OPEN = "open", "Новая"
        RESOLVED = "resolved", "Приняты меры"
        REJECTED = "rejected", "Отклонена"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_sent", verbose_name="кто пожаловался"
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_received",
        verbose_name="на кого",
    )
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="объявление",
    )
    reason = models.CharField("причина", max_length=20, choices=Reason.choices)
    comment = models.TextField("комментарий", max_length=2000, blank=True)
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    moderator_note = models.TextField("заметка модератора", blank=True)
    created_at = models.DateTimeField("создана", auto_now_add=True)

    class Meta:
        verbose_name = "жалоба"
        verbose_name_plural = "жалобы"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_reason_display()} — на {self.reported_user}"
