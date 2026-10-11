from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Модуль пользователей: регистрация, вход, анкета человека."""

    name = "apps.accounts"
    verbose_name = "Пользователи"

    def ready(self):
        # Подключаем сигналы (автосоздание анкеты при регистрации)
        from . import signals  # noqa: F401
