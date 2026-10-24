"""Пользователь и его анкета.

Один и тот же пользователь может быть и ищущим (у него активная анкета),
и владельцем (у него есть объявления о комнатах). Ролей как отдельной сущности
нет: роль определяется тем, что человек делает в сервисе.
"""

import secrets
from datetime import date

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models

# Минимальный возраст пользователя сервиса
MIN_AGE = 18


def validate_birth_year(value: int) -> None:
    """Проверяет год рождения: пользователю должно быть не меньше 18 лет.

    Вынесено в функцию, а не MaxValueValidator(date.today()...), чтобы граница
    пересчитывалась каждый год и не «замораживалась» в миграции.
    """
    current_year = date.today().year
    if value < 1930 or value > current_year - MIN_AGE:
        raise ValidationError(f"Сервис доступен с {MIN_AGE} лет. Проверьте год рождения.")


class UserManager(BaseUserManager):
    """Менеджер пользователей, где идентификатором служит email."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email обязателен")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Пользователь сервиса. Входит по email.

    Позже сюда добавится вход по телефону (SMS-код) и через VK ID / Яндекс ID.
    """

    username = None  # логин не используем
    email = models.EmailField("email", unique=True)
    # Когда человек последний раз заходил на сайт (обновляется не чаще раза в 10 минут).
    # По нему лента поднимает активных и прячет тех, кто пропал надолго.
    last_seen_at = models.DateTimeField("последний визит", null=True, blank=True, db_index=True)
    # Когда человек подтвердил почту по ссылке из письма
    email_verified_at = models.DateTimeField("почта подтверждена", null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    def __str__(self) -> str:
        return self.email

    @property
    def can_interact(self) -> bool:
        """Можно ли ставить лайки и писать сообщения: почта подтверждена или подтверждение не требуется."""
        from django.conf import settings

        return bool(self.email_verified_at) or self.is_staff or not settings.EMAIL_VERIFICATION_REQUIRED


class Profile(models.Model):
    """Анкета человека: кто он, какое жильё ищет и как живёт.

    Анкету видят владельцы комнат в своей ленте, если включено «Ищу жильё».
    """

    class Gender(models.TextChoices):
        MALE = "m", "Мужской"
        FEMALE = "f", "Женский"
        OTHER = "o", "Не указывать"

    class Schedule(models.TextChoices):
        EARLY = "early", "Жаворонок"
        LATE = "late", "Сова"
        FLEXIBLE = "flex", "По-разному"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="пользователь")

    # --- Основное ---
    display_name = models.CharField("имя", max_length=60, blank=True)
    birth_year = models.PositiveSmallIntegerField(
        "год рождения",
        null=True,
        blank=True,
        validators=[validate_birth_year],
    )
    gender = models.CharField("пол", max_length=1, choices=Gender.choices, default=Gender.OTHER)
    about = models.TextField("о себе", max_length=2000, blank=True)
    occupation = models.CharField("чем занимаюсь", max_length=120, blank=True)
    photo = models.ImageField("фото", upload_to="profiles/%Y/%m/", blank=True)

    # --- Что ищу ---
    is_seeking = models.BooleanField(
        "ищу жильё",
        default=False,
        help_text="Если включено, анкету видят владельцы комнат в вашем городе.",
    )
    city = models.ForeignKey(
        "geo.City", on_delete=models.PROTECT, null=True, blank=True, related_name="profiles", verbose_name="город"
    )
    preferred_districts = models.CharField("желаемые районы или метро", max_length=255, blank=True)
    budget_max = models.PositiveIntegerField("бюджет до (в месяц)", null=True, blank=True)
    move_in_date = models.DateField("готов заехать с", null=True, blank=True)

    # --- Образ жизни (используется для совместимости в ленте) ---
    smoker = models.BooleanField("курю", default=False)
    has_pets = models.BooleanField("есть животные", default=False)
    works_from_home = models.BooleanField("работаю из дома", default=False)
    schedule = models.CharField("режим дня", max_length=5, choices=Schedule.choices, default=Schedule.FLEXIBLE)

    # --- Модерация ---
    # Скрытая анкета не показывается в лентах (например, после жалоб)
    is_hidden = models.BooleanField("скрыта модератором", default=False)

    # --- Вопрос «Нашли?» ---
    # До этого момента не спрашиваем «Нашли соседа/комнату?» (человек ответил «Пока нет»)
    found_prompt_snoozed_until = models.DateTimeField("не спрашивать «Нашли?» до", null=True, blank=True)
    # «Посмотреть ещё раз»: комнаты, пропущенные до этого момента, снова показываются в ленте
    feed_reset_at = models.DateTimeField("лента сброшена", null=True, blank=True)

    # --- Верификация ---
    # Модератор сравнил фото анкеты с живым селфи. При смене фото анкеты отметка снимается.
    verified_at = models.DateTimeField("профиль подтверждён", null=True, blank=True)

    created_at = models.DateTimeField("создана", auto_now_add=True)
    updated_at = models.DateTimeField("обновлена", auto_now=True)

    class Meta:
        verbose_name = "анкета"
        verbose_name_plural = "анкеты"

    def __str__(self) -> str:
        return self.display_name or self.user.email

    @property
    def age(self) -> int | None:
        """Примерный возраст по году рождения (точную дату не храним — меньше персданных)."""
        if not self.birth_year:
            return None
        return date.today().year - self.birth_year

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_complete(self) -> bool:
        """Достаточно ли заполнена анкета, чтобы участвовать в ленте."""
        return bool(self.display_name and self.city_id)


def generate_invite_code() -> str:
    """Короткий код приглашения без похожих символов (0/O, 1/I/L), чтобы его было легко продиктовать."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


class InviteQuerySet(models.QuerySet):
    def usable(self):
        """Приглашения, по которым ещё можно зарегистрироваться."""
        return self.filter(is_active=True, used_by__isnull=True)


class Invite(models.Model):
    """Одноразовое приглашение для регистрации в режиме закрытого теста.

    Создаётся в админке (или командой create_invites). Владелец сервиса
    отправляет человеку ссылку вида /accounts/signup/?invite=КОД.
    """

    code = models.CharField("код", max_length=16, unique=True, default=generate_invite_code)
    note = models.CharField("для кого", max_length=120, blank=True, help_text="Например: «Маша, коллега»")
    # Откуда пришёл человек — для статистики «какой канал приводит активных пользователей»
    channel = models.CharField(
        "канал",
        max_length=60,
        blank=True,
        db_index=True,
        help_text="Где раздали приглашение: «TG Аренда Москва», «ВК Сокол», «знакомые». "
        "Один канал всегда пишите одинаково.",
    )
    is_active = models.BooleanField("действует", default=True, help_text="Снимите галочку, чтобы отозвать приглашение")
    created_at = models.DateTimeField("создано", auto_now_add=True)
    used_by = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invite",
        verbose_name="кто зарегистрировался",
    )
    used_at = models.DateTimeField("использовано", null=True, blank=True)

    objects = InviteQuerySet.as_manager()

    class Meta:
        verbose_name = "приглашение"
        verbose_name_plural = "приглашения"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code}{' — ' + self.note if self.note else ''}"

    @property
    def is_usable(self) -> bool:
        return self.is_active and self.used_by_id is None


# Жесты для живого селфи: модератор проверяет, что человек на фото показывает именно этот жест.
# Так нельзя отправить чужое или заранее снятое фото.
VERIFICATION_GESTURES = {
    "two_fingers": "Покажите два пальца (знак «V») рядом с лицом",
    "palm_cheek": "Приложите ладонь к щеке",
    "thumb_up": "Покажите большой палец вверх",
    "touch_ear": "Дотроньтесь пальцем до уха",
    "three_fingers": "Покажите три пальца",
    "chin_hand": "Подоприте подбородок кулаком",
}


class VerificationRequest(models.Model):
    """Заявка на подтверждение профиля: живое селфи с жестом, которое модератор сравнивает с фото анкеты.

    Селфи нужно только для проверки: после решения модератора файл удаляется.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Ждёт проверки"
        APPROVED = "approved", "Подтверждено"
        REJECTED = "rejected", "Отклонено"

    class RejectReason(models.TextChoices):
        NOT_SAME_PERSON = "not_same", "На селфи другой человек, не как в анкете"
        WRONG_GESTURE = "gesture", "Жест не совпадает с заданием"
        BAD_PHOTO = "bad_photo", "Лицо плохо видно — переснимите при хорошем свете"
        NO_PROFILE_PHOTO = "no_photo", "В анкете нет фото, где видно лицо"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="verification_requests", verbose_name="пользователь"
    )
    gesture = models.CharField("жест", max_length=20, choices=list(VERIFICATION_GESTURES.items()))
    selfie = models.ImageField("селфи", upload_to="verification/%Y/%m/", blank=True)
    # Какое фото анкеты было на момент заявки — если его сменят, сравнивать не с чем
    profile_photo_name = models.CharField("фото анкеты на момент заявки", max_length=255, blank=True)
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reject_reason = models.CharField("причина отказа", max_length=12, choices=RejectReason.choices, blank=True)
    created_at = models.DateTimeField("подана", auto_now_add=True)
    reviewed_at = models.DateTimeField("проверена", null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="модератор"
    )

    class Meta:
        verbose_name = "заявка на верификацию"
        verbose_name_plural = "заявки на верификацию"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_status_display().lower()}"

    @property
    def gesture_text(self) -> str:
        return VERIFICATION_GESTURES.get(self.gesture, self.gesture)
