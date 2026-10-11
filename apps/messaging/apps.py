from django.apps import AppConfig


class MessagingConfig(AppConfig):
    """Модуль сообщений: чат открывается только после мэтча."""

    name = "apps.messaging"
    verbose_name = "Сообщения"
