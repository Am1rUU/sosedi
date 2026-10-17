"""Заполнение базы демо-данными для локальной разработки и показа MVP.

Запуск:  python manage.py seed_demo
Повторный запуск безопасен: существующие демо-пользователи не дублируются.
Пароль всех демо-пользователей: demo12345
"""

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Invite, Profile, User
from apps.accounts.services import create_invites, invite_url
from apps.geo.models import City
from apps.listings.models import Listing
from apps.matching.models import Swipe
from apps.matching.services import record_swipe

DEMO_PASSWORD = "demo12345"

# Ищущие: (имя, год рождения, пол, занятие, бюджет, районы, курит, животные, режим)
SEEKERS = [
    ("Анна", 1999, "f", "Дизайнер интерфейсов", 35000, "Таганская, Курская", False, False, "late"),
    ("Илья", 1996, "m", "Backend-разработчик", 40000, "Бауманская, Курская", False, True, "flex"),
    ("Мария", 2002, "f", "Студентка МГУ", 25000, "Университет, Профсоюзная", False, False, "early"),
    ("Тимур", 1994, "m", "Маркетолог", 45000, "Белорусская, Динамо", True, False, "late"),
    ("Ксения", 1998, "f", "Врач-ординатор", 38000, "Сокол, Аэропорт", False, False, "early"),
    ("Дмитрий", 2000, "m", "Аналитик данных", 30000, "Электрозаводская", False, False, "flex"),
]

# Объявления: (заголовок, район, метро, цена, тип, пол, курение, животные, описание)
LISTINGS = [
    (
        "Светлая комната у м. Таганская",
        "Таганский",
        "Таганская",
        32000,
        "room",
        "any",
        False,
        False,
        "Комната 14 м² в трёшке, живут двое: я и подруга. Тихо, чисто, рядом парк.",
    ),
    (
        "Комната в сталинке на Курской",
        "Басманный",
        "Курская",
        37000,
        "room",
        "any",
        False,
        True,
        "Высокие потолки, большая кухня. Есть кот, так что любителям животных — сюда.",
    ),
    (
        "Место для девушки у Университета",
        "Раменки",
        "Университет",
        22000,
        "room",
        "f",
        False,
        False,
        "Ищем третью соседку, студентки. До МГУ 10 минут пешком.",
    ),
    (
        "Комната с балконом на Белорусской",
        "Тверской",
        "Белорусская",
        43000,
        "room",
        "any",
        True,
        False,
        "Свежий ремонт, балкон, можно курить на балконе. Живёт один сосед-программист.",
    ),
    (
        "Уютная комната у м. Сокол",
        "Сокол",
        "Сокол",
        34000,
        "room",
        "any",
        False,
        False,
        "Зелёный район, рядом поселок художников. Сосед — спокойный инженер.",
    ),
]


class Command(BaseCommand):
    help = "Создаёт демо-пользователей, анкеты, объявления и пару мэтчей"

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)  # воспроизводимые данные
        moscow = City.objects.get(slug="moskva")

        # --- Администратор для входа в модерацию ---
        if not User.objects.filter(email="admin@sosedi.local").exists():
            User.objects.create_superuser("admin@sosedi.local", DEMO_PASSWORD)
            self.stdout.write("Создан администратор admin@sosedi.local")

        # --- Ищущие ---
        seekers = []
        for i, (name, year, gender, job, budget, districts, smoker, pets, schedule) in enumerate(SEEKERS, start=1):
            user, created = User.objects.get_or_create(email=f"seeker{i}@sosedi.local")
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            Profile.objects.filter(user=user).update(
                display_name=name,
                birth_year=year,
                gender=gender,
                occupation=job,
                about=f"Привет! Я {name}, {job.lower()}. Чистоплотный(ая), уважаю личное пространство.",
                is_seeking=True,
                city=moscow,
                preferred_districts=districts,
                budget_max=budget,
                move_in_date=date.today() + timedelta(days=random.randint(3, 30)),
                smoker=smoker,
                has_pets=pets,
                schedule=schedule,
            )
            seekers.append(user)

        # --- Владельцы и их объявления ---
        listings = []
        for i, (title, district, metro, rent, room_type, gender, smoking, pets, text) in enumerate(LISTINGS, start=1):
            owner, created = User.objects.get_or_create(email=f"owner{i}@sosedi.local")
            if created:
                owner.set_password(DEMO_PASSWORD)
                owner.save()
            Profile.objects.filter(user=owner).update(
                display_name=["Ольга", "Сергей", "Алина", "Артём", "Павел"][i - 1],
                city=moscow,
                about="Сдаю комнату в своей квартире, живу здесь сам(а).",
            )
            listing, _ = Listing.objects.get_or_create(
                owner=owner,
                title=title,
                defaults={
                    "city": moscow,
                    "district": district,
                    "metro": metro,
                    "rent": rent,
                    "deposit": rent,
                    "room_type": room_type,
                    "preferred_gender": gender,
                    "smoking_allowed": smoking,
                    "pets_allowed": pets,
                    "description": text,
                    "available_from": date.today() + timedelta(days=random.randint(0, 20)),
                    "min_term_months": random.choice([1, 3, 6]),
                    "flatmates_count": random.choice([1, 2]),
                    "bills_included": random.choice([True, False]),
                },
            )
            listings.append(listing)

        # --- Немного активности, чтобы ленты и мэтчи были не пустыми ---
        # Анна и владелец комнаты на Таганской лайкнули друг друга — мэтч
        record_swipe(seekers[0], listings[0], seekers[0], Swipe.Side.SEEKER, Swipe.Decision.LIKE)
        record_swipe(listings[0].owner, listings[0], seekers[0], Swipe.Side.OWNER, Swipe.Decision.LIKE)
        # Илья лайкнул комнату на Курской — владелец увидит его во «Кто лайкнул»
        record_swipe(seekers[1], listings[1], seekers[1], Swipe.Side.SEEKER, Swipe.Decision.LIKE)
        # Владелец комнаты у Сокола лайкнул Ксению — у неё карточка будет с пометкой
        record_swipe(listings[4].owner, listings[4], seekers[4], Swipe.Side.OWNER, Swipe.Decision.LIKE)

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: {len(seekers)} ищущих, {len(listings)} объявлений. "
                f"Пароль всех демо-аккаунтов: {DEMO_PASSWORD}"
            )
        )
        self.stdout.write(
            "Попробуйте войти как seeker1@sosedi.local (есть мэтч) или owner2@sosedi.local (есть входящий лайк)."
        )

        # Пара приглашений, чтобы проверить регистрацию в закрытом режиме
        if not Invite.objects.filter(note="демо").exists():
            create_invites(2, note="демо")
        self.stdout.write("Ссылки-приглашения для проверки регистрации:")
        for invite in Invite.objects.usable().filter(note="демо"):
            self.stdout.write(f"  {invite_url(invite)}")
