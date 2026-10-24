"""Создание приглашений из командной строки.

Пример:  python manage.py create_invites 5 --note "друзья из чата аренды" --channel "TG Аренда Москва"
Выводит готовые ссылки, которые можно сразу разослать.
"""

from django.core.management.base import BaseCommand

from apps.accounts.services import create_invites, invite_url


class Command(BaseCommand):
    help = "Создаёт N приглашений и печатает ссылки на регистрацию"

    def add_arguments(self, parser):
        parser.add_argument("count", type=int, nargs="?", default=1, help="Сколько приглашений создать")
        parser.add_argument("--note", default="", help="Для кого приглашения (видно в админке)")
        parser.add_argument("--channel", default="", help="Канал, где раздаёте приглашения (для статистики)")

    def handle(self, *args, count, note, channel, **options):
        for invite in create_invites(count, note=note, channel=channel):
            self.stdout.write(invite_url(invite))
