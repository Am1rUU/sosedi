from django.apps import AppConfig


class ModerationConfig(AppConfig):
    """Модуль модерации: жалобы пользователей и автоматическое скрытие."""

    name = "apps.moderation"
    verbose_name = "Модерация"
