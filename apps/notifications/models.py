"""Настройки уведомлений пользователя и привязка Telegram."""

from django.conf import settings
from django.db import models


class NotificationSettings(models.Model):
    """Куда человеку присылать уведомления о мэтчах и новых сообщениях."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_settings",
        verbose_name="пользователь",
    )
    email_enabled = models.BooleanField("уведомления на почту", default=True)
    telegram_enabled = models.BooleanField("уведомления в Telegram", default=True)

    # Привязка Telegram: человек открывает бота по ссылке с одноразовым кодом,
    # бот получает код и запоминает чат, куда слать уведомления.
    telegram_chat_id = models.BigIntegerField("чат Telegram", null=True, blank=True, unique=True)
    telegram_username = models.CharField("имя в Telegram", max_length=64, blank=True)
    telegram_link_code = models.CharField("код привязки", max_length=32, blank=True, db_index=True)
    telegram_link_created_at = models.DateTimeField("код выдан", null=True, blank=True)

    class Meta:
        verbose_name = "настройки уведомлений"
        verbose_name_plural = "настройки уведомлений"

    def __str__(self) -> str:
        return f"Уведомления: {self.user}"

    @property
    def telegram_connected(self) -> bool:
        return self.telegram_chat_id is not None
