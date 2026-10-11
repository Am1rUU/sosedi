"""Пользователь и его анкета.

Один и тот же пользователь может быть и ищущим (у него активная анкета),
и владельцем (у него есть объявления о комнатах). Ролей как отдельной сущности
нет: роль определяется тем, что человек делает в сервисе.
"""

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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    def __str__(self) -> str:
        return self.email


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
    def is_complete(self) -> bool:
        """Достаточно ли заполнена анкета, чтобы участвовать в ленте."""
        return bool(self.display_name and self.city_id)
