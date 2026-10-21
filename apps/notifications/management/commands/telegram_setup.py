"""Подключение Telegram-бота: сообщаем Telegram адрес сайта для входящих сообщений.

Запускается автоматически при старте, если задан TELEGRAM_BOT_TOKEN (см. docker-entrypoint.sh).
"""

from django.core.management.base import BaseCommand

from apps.notifications import telegram


class Command(BaseCommand):
    help = "Настраивает webhook Telegram-бота на адрес сайта (SITE_URL)"

    def handle(self, *args, **options):
        if not telegram.is_configured():
            self.stdout.write("TELEGRAM_BOT_TOKEN не задан — Telegram-уведомления выключены")
            return
        try:
            telegram.set_webhook()
            name = telegram.bot_username()
        except telegram.TelegramError as exc:
            self.stderr.write(f"Не удалось подключить Telegram-бота: {exc}")
            return
        self.stdout.write(f"Telegram-бот @{name} подключён: {telegram.webhook_url()}")
