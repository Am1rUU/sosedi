"""Объявления о комнатах и их фотографии."""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class ListingQuerySet(models.QuerySet):
    """Готовые выборки объявлений, чтобы не повторять условия по всему коду."""

    def visible(self):
        """Объявления, которые можно показывать в ленте: активные и владелец не заблокирован."""
        return self.filter(
            status=Listing.Status.ACTIVE,
            owner__is_active=True,
            owner__profile__is_hidden=False,
        )


class Listing(models.Model):
    """Объявление о свободной комнате (или квартире целиком под подселение)."""

    class Status(models.TextChoices):
        PENDING = "pending", "На модерации"
        ACTIVE = "active", "Активно"
        PAUSED = "paused", "На паузе"
        RENTED = "rented", "Сдано"
        BLOCKED = "blocked", "Заблокировано"

    class RoomType(models.TextChoices):
        ROOM = "room", "Комната в квартире"
        SHARED_ROOM = "shared", "Место в комнате"
        WHOLE = "whole", "Квартира целиком"

    class GenderPreference(models.TextChoices):
        ANY = "any", "Не важно"
        MALE = "m", "Только мужчины"
        FEMALE = "f", "Только женщины"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings", verbose_name="владелец"
    )
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    # --- Где ---
    city = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="listings", verbose_name="город")
    district = models.CharField("район", max_length=100, blank=True)
    metro = models.CharField("метро", max_length=100, blank=True)
    # Точный адрес видят только после мэтча — защита владельца от лишних визитов
    address = models.CharField("адрес (виден после мэтча)", max_length=255, blank=True)

    # --- Что ---
    title = models.CharField("заголовок", max_length=120)
    description = models.TextField("описание", max_length=5000)
    room_type = models.CharField("тип жилья", max_length=10, choices=RoomType.choices, default=RoomType.ROOM)
    rent = models.PositiveIntegerField("цена в месяц")
    deposit = models.PositiveIntegerField("залог", default=0)
    bills_included = models.BooleanField("коммуналка включена", default=False)
    furnished = models.BooleanField("с мебелью", default=True)
    available_from = models.DateField("свободно с")
    min_term_months = models.PositiveSmallIntegerField("минимальный срок, мес.", default=1)
    flatmates_count = models.PositiveSmallIntegerField("сколько человек уже живёт", default=1)

    # --- Правила и пожелания к соседу ---
    smoking_allowed = models.BooleanField("можно курить", default=False)
    pets_allowed = models.BooleanField("можно с животными", default=False)
    preferred_gender = models.CharField(
        "пол соседа", max_length=3, choices=GenderPreference.choices, default=GenderPreference.ANY
    )

    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        verbose_name = "объявление"
        verbose_name_plural = "объявления"
        ordering = ["-created_at"]
        indexes = [
            # Основной запрос ленты: активные объявления в городе по цене
            models.Index(fields=["city", "status", "rent"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} — {self.city}"

    def get_absolute_url(self) -> str:
        return reverse("listings:detail", args=[self.pk])

    @property
    def main_photo(self):
        """Первое фото объявления для карточки в ленте."""
        photos = list(self.photos.all())  # использует prefetch_related, если он был
        return photos[0] if photos else None

    @property
    def is_available_now(self) -> bool:
        """Комната уже свободна (дата заезда сегодня или в прошлом)."""
        return self.available_from <= timezone.localdate()


class ListingPhoto(models.Model):
    """Фотография объявления."""

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="photos", verbose_name="объявление")
    image = models.ImageField("фото", upload_to="listings/%Y/%m/")
    position = models.PositiveSmallIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "фото объявления"
        verbose_name_plural = "фото объявлений"
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"Фото #{self.pk} для «{self.listing.title}»"
