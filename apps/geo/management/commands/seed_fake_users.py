"""Фейковые пользователи для закрытого теста: 10 ищущих и 10 сдающих комнату в Москве.

Запуск:
    python manage.py seed_fake_users            # создать или обновить
    python manage.py seed_fake_users --delete   # удалить всех фейковых пользователей и их фото

На хостинге запускается автоматически при каждом старте, если задана
переменная SEED_FAKE_USERS=1 (см. docker-entrypoint.sh). Повторный запуск
безопасен: пользователи не дублируются, а время «последнего визита»
освежается, чтобы фейковые анкеты не пропадали из ленты как неактивные.

Фото: если положить картинки в папки seed/photos/people и seed/photos/rooms,
они подставятся в анкеты и объявления (по порядку имён файлов).
Если папки пустые — анкеты и объявления будут без фото.

Войти под фейковым пользователем нельзя: пароль у них не задан.
"""

import random
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.geo.models import City
from apps.listings.models import Listing, ListingPhoto
from config.images import process_photo

# По этому домену фейковых пользователей легко найти в админке и удалить
FAKE_EMAIL_DOMAIN = "fake.sosedi.local"
PHOTOS_DIR = Path(settings.BASE_DIR) / "seed" / "photos"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# (имя, год рождения, пол, занятие, бюджет, желаемые районы/метро, курит, животные, режим, о себе)
SEEKERS = [
    (
        "Алиса",
        2000,
        "f",
        "Junior-дизайнер в агентстве",
        35000,
        "Курская, Чистые пруды, Бауманская",
        False,
        False,
        "late",
        "Переехала из Казани, работаю в агентстве у Курской. Люблю готовить на всех и смотреть сериалы по вечерам. "
        "Не шумлю, гостей зову редко и заранее предупреждаю.",
    ),
    (
        "Егор",
        1997,
        "m",
        "Backend-разработчик",
        45000,
        "Электрозаводская, Семёновская",
        False,
        False,
        "flex",
        "Работаю удалённо 3 дня в неделю, так что ценю тишину днём. По выходным катаюсь на велосипеде. "
        "Посуду мою сразу, честно.",
    ),
    (
        "Вика",
        2003,
        "f",
        "Студентка ВШЭ, 3 курс",
        25000,
        "Китай-город, Покровка, Курская",
        False,
        False,
        "late",
        "Учусь на Покровке, подрабатываю в кофейне. Ищу комнату недалеко от учёбы, в идеале с соседями-студентами.",
    ),
    (
        "Артур",
        1995,
        "m",
        "Менеджер проектов",
        50000,
        "Белорусская, Маяковская, Динамо",
        False,
        True,
        "early",
        "Со мной живёт спокойный кот Бублик, он лоток знает и мебель не трогает. Встаю рано, бегаю по утрам.",
    ),
    (
        "Полина",
        1999,
        "f",
        "Врач-ординатор",
        38000,
        "Сокол, Аэропорт, Войковская",
        False,
        False,
        "early",
        "Работаю в больнице, бывают ночные смены — днём иногда сплю. Ищу спокойную квартиру без вечеринок.",
    ),
    (
        "Никита",
        2001,
        "m",
        "Аналитик в банке",
        40000,
        "Таганская, Пролетарская",
        True,
        False,
        "flex",
        "Курю только на улице или на балконе. Люблю настолки — если соседи тоже любят, будет здорово.",
    ),
    (
        "Даша",
        1998,
        "f",
        "SMM-специалист",
        33000,
        "Динамо, Савёловская, Белорусская",
        False,
        True,
        "late",
        "У меня маленькая собака (той-пудель), очень воспитанная. Работаю из дома, поэтому ищу комнату со столом.",
    ),
    (
        "Руслан",
        1993,
        "m",
        "Инженер-проектировщик",
        42000,
        "ВДНХ, Алексеевская, Рижская",
        False,
        False,
        "early",
        "Тихий, аккуратный, по вечерам читаю или в спортзале. Переезжаю из Екатеринбурга по работе.",
    ),
    (
        "Соня",
        2002,
        "f",
        "Студентка МГУ",
        24000,
        "Университет, Профсоюзная, Ленинский проспект",
        False,
        False,
        "flex",
        "Учусь на биофаке, много времени провожу в лаборатории. Ищу соседок, с которыми можно вместе готовить.",
    ),
    (
        "Марк",
        1996,
        "m",
        "Фотограф",
        36000,
        "Курская, Площадь Ильича, Римская",
        False,
        False,
        "late",
        "Снимаю свадьбы и портреты, бываю в разъездах. Дома аккуратен, коммуналку и уборку делю честно.",
    ),
]

# (имя хозяина, о себе, заголовок, район, метро, мин пешком, мин на транспорте, цена, залог, тип,
#  пол соседа, курение, животные, сколько живёт, мебель, коммуналка включена, описание)
OWNERS = [
    (
        "Ольга",
        "Живу здесь с дочкой-студенткой, работаю бухгалтером.",
        "Светлая комната 15 м² у Таганской",
        "Таганский",
        "Таганская",
        7,
        None,
        34000,
        34000,
        "room",
        "f",
        False,
        False,
        2,
        True,
        False,
        "Комната с большим окном во двор, есть шкаф, кровать и рабочий стол. Кухня 10 м², стиральная и посудомойка. "
        "Ищем спокойную девушку, можно студентку.",
    ),
    (
        "Сергей",
        "Программист, много работаю из дома, люблю порядок.",
        "Комната в сталинке на Курской",
        "Басманный",
        "Курская",
        5,
        None,
        39000,
        39000,
        "room",
        "any",
        False,
        True,
        1,
        True,
        False,
        "Потолки 3,2 м, тихий двор, рядом Садовое. Есть кот, так что подойдёт тем, кто любит животных. "
        "Интернет 500 Мбит, в комнате рабочее место.",
    ),
    (
        "Алина",
        "Учусь в магистратуре, в квартире живём втроём.",
        "Место для девушки у Университета",
        "Раменки",
        "Университет",
        12,
        4,
        23000,
        10000,
        "shared",
        "f",
        False,
        False,
        3,
        True,
        True,
        "Ищем четвёртую соседку в просторную комнату на двоих. До МГУ 15 минут пешком. Коммуналка уже в цене.",
    ),
    (
        "Артём",
        "Работаю в IT, по вечерам часто дома.",
        "Комната с балконом на Белорусской",
        "Тверской",
        "Белорусская",
        9,
        None,
        46000,
        46000,
        "room",
        "any",
        True,
        False,
        1,
        True,
        False,
        "Свежий ремонт, свой балкон — курить можно только там. В квартире живёт один сосед, то есть я.",
    ),
    (
        "Павел",
        "Инженер, спокойный, на выходных часто за городом.",
        "Уютная комната у м. Сокол",
        "Сокол",
        "Сокол",
        6,
        None,
        35000,
        35000,
        "room",
        "any",
        False,
        False,
        1,
        True,
        False,
        "Зелёный район, рядом посёлок художников и парк. Комната 13 м², тёплая, окна на тихую сторону.",
    ),
    (
        "Ирина",
        "Дизайнер, работаю в студии, дома бываю вечером.",
        "Комната в лофте у Электрозаводской",
        "Преображенское",
        "Электрозаводская",
        4,
        None,
        41000,
        41000,
        "room",
        "any",
        False,
        False,
        2,
        True,
        False,
        "Квартира в бывшем фабричном здании: кирпичные стены, большие окна. Соседи — творческие и аккуратные.",
    ),
    (
        "Кирилл",
        "Работаю в банке, люблю готовить.",
        "Комната у ВДНХ с видом на парк",
        "Останкинский",
        "ВДНХ",
        15,
        5,
        30000,
        15000,
        "room",
        "m",
        False,
        False,
        1,
        True,
        True,
        "Ищу соседа-парня. Рядом ВДНХ и Ботанический сад, удобно бегать. Коммуналка включена.",
    ),
    (
        "Наталья",
        "Пенсионерка, сдаю вторую комнату, живу тихо.",
        "Тихая комната у м. Аэропорт",
        "Аэропорт",
        "Аэропорт",
        8,
        None,
        32000,
        32000,
        "room",
        "f",
        False,
        False,
        1,
        True,
        True,
        "Ищу аккуратную девушку, можно студентку или молодого специалиста. Чистый подъезд, хорошие соседи.",
    ),
    (
        "Глеб",
        "Музыкант-преподаватель, занимаюсь в студии, не дома.",
        "Комната на Савёловской с животными",
        "Бутырский",
        "Савёловская",
        10,
        3,
        33000,
        33000,
        "room",
        "any",
        False,
        True,
        2,
        False,
        False,
        "Можно с животными — у нас живёт собака. Комната без мебели: можно обставить под себя.",
    ),
    (
        "Елена",
        "Работаю врачом, живу с мужем.",
        "Квартира целиком у Римской под подселение",
        "Лефортово",
        "Римская",
        11,
        4,
        52000,
        52000,
        "whole",
        "any",
        False,
        False,
        0,
        True,
        False,
        "Однокомнатная квартира целиком, можно вдвоём. Рядом Лефортовский парк и Яуза.",
    ),
]


def _photos(kind: str) -> list[Path]:
    folder = PHOTOS_DIR / kind
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def _prepared(path: Path):
    """Фото проходит ту же обработку, что и загруженное человеком: сжатие и удаление EXIF."""
    with path.open("rb") as raw:
        return process_photo(File(raw, name=path.name))


class Command(BaseCommand):
    help = "Создаёт 10 фейковых ищущих и 10 фейковых хозяев комнат в Москве (или удаляет их с --delete)"

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Удалить всех фейковых пользователей и их фото")

    def handle(self, *args, **options):
        if options["delete"]:
            self._delete()
        else:
            self._create()

    def _delete(self):
        users = User.objects.filter(email__endswith=f"@{FAKE_EMAIL_DOMAIN}")
        for photo in ListingPhoto.objects.filter(listing__owner__in=users):
            photo.image.delete(save=False)
        for profile in Profile.objects.filter(user__in=users).exclude(photo=""):
            profile.photo.delete(save=False)
        count = users.count()
        users.delete()
        self.stdout.write(f"Удалено фейковых пользователей: {count}")

    @transaction.atomic
    def _create(self):
        moscow = City.objects.filter(slug="moskva").first()
        if moscow is None:
            self.stderr.write("Нет города Москва (slug=moskva) — фейковые пользователи не созданы")
            return

        rng = random.Random(7)  # одинаковые данные при каждом запуске
        people = _photos("people")
        rooms = _photos("rooms")
        now = timezone.now()
        created_users = 0

        def ensure_user(email: str) -> User:
            nonlocal created_users
            user, created = User.objects.get_or_create(email=email)
            if created:
                user.set_unusable_password()  # под фейковым пользователем войти нельзя
                user.save()
                created_users += 1
            # Освежаем «последний визит», чтобы анкета не считалась заброшенной
            User.objects.filter(pk=user.pk).update(
                last_seen_at=now - timedelta(hours=rng.randint(1, 72)), email_verified_at=now
            )
            return user

        def set_avatar(profile: Profile, index: int):
            if profile.photo or not people:
                return
            path = people[index % len(people)]
            profile.photo.save(f"{path.stem}.jpg", _prepared(path), save=False)

        # --- Ищущие ---
        for i, (name, year, gender, job, budget, districts, smoker, pets, schedule, about) in enumerate(SEEKERS):
            user = ensure_user(f"seeker{i + 1}@{FAKE_EMAIL_DOMAIN}")
            profile = user.profile
            profile.display_name = name
            profile.birth_year = year
            profile.gender = gender
            profile.occupation = job
            profile.about = about
            profile.is_seeking = True
            profile.city = moscow
            profile.preferred_districts = districts
            profile.budget_max = budget
            profile.move_in_date = date.today() + timedelta(days=rng.randint(5, 40))
            profile.smoker = smoker
            profile.has_pets = pets
            profile.schedule = schedule
            set_avatar(profile, i)
            profile.save()

        # --- Хозяева и объявления ---
        room_index = 0
        for i, row in enumerate(OWNERS):
            (
                owner_name,
                owner_about,
                title,
                district,
                metro,
                walk,
                transport,
                rent,
                deposit,
                room_type,
                gender_pref,
                smoking,
                pets,
                flatmates,
                furnished,
                bills,
                description,
            ) = row
            user = ensure_user(f"owner{i + 1}@{FAKE_EMAIL_DOMAIN}")
            profile = user.profile
            profile.display_name = owner_name
            profile.about = owner_about
            profile.city = moscow
            profile.is_seeking = False
            set_avatar(profile, len(SEEKERS) + i)
            profile.save()

            listing, created = Listing.objects.get_or_create(
                owner=user,
                title=title,
                defaults={
                    "city": moscow,
                    "description": description,
                    "rent": rent,
                    "available_from": date.today() + timedelta(days=rng.randint(0, 25)),
                },
            )
            listing.district = district
            listing.metro = metro
            listing.metro_walk_minutes = walk
            listing.metro_transport_minutes = transport
            listing.description = description
            listing.rent = rent
            listing.deposit = deposit
            listing.room_type = room_type
            listing.preferred_gender = gender_pref
            listing.smoking_allowed = smoking
            listing.pets_allowed = pets
            listing.flatmates_count = flatmates
            listing.furnished = furnished
            listing.bills_included = bills
            if listing.status not in (Listing.Status.BLOCKED, Listing.Status.RENTED):
                listing.status = Listing.Status.ACTIVE
            listing.save()  # заодно освежает «обновлено» — вопрос «Комната ещё свободна?» не нужен

            # До трёх фото на объявление, если фото комнат есть и у объявления их ещё нет
            if rooms and not listing.photos.exists():
                for position in range(min(3, len(rooms))):
                    path = rooms[room_index % len(rooms)]
                    room_index += 1
                    photo = ListingPhoto(listing=listing, position=position)
                    photo.image.save(f"{path.stem}.jpg", _prepared(path), save=True)

        self.stdout.write(
            f"Фейковые пользователи готовы: {len(SEEKERS)} ищущих и {len(OWNERS)} хозяев "
            f"(новых: {created_users}; фото людей: {len(people)}, фото комнат: {len(rooms)})"
        )
