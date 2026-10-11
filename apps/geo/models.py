"""Справочник городов.

На MVP достаточно города и текстовых полей «район» и «метро» в объявлении.
Когда понадобится поиск по карте и радиусу, сюда добавятся районы, станции
метро и координаты (PostgreSQL + PostGIS).
"""

from django.db import models


class City(models.Model):
    """Город, в котором работает сервис."""

    class Country(models.TextChoices):
        # Страны запуска: сначала Россия, затем СНГ
        RUSSIA = "RU", "Россия"
        KAZAKHSTAN = "KZ", "Казахстан"
        BELARUS = "BY", "Беларусь"
        UZBEKISTAN = "UZ", "Узбекистан"
        ARMENIA = "AM", "Армения"
        GEORGIA = "GE", "Грузия"
        KYRGYZSTAN = "KG", "Кыргызстан"

    name = models.CharField("название", max_length=100)
    slug = models.SlugField("код для адреса", max_length=100, unique=True)
    country = models.CharField("страна", max_length=2, choices=Country.choices, default=Country.RUSSIA)
    # Валюта нужна, чтобы корректно показывать цены в разных странах
    currency = models.CharField("валюта", max_length=3, default="RUB")
    # Неактивные города скрыты из выбора — так можно запускать города по одному
    is_active = models.BooleanField("доступен", default=True)

    class Meta:
        verbose_name = "город"
        verbose_name_plural = "города"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
