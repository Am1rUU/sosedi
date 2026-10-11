"""Начальный список городов.

Запускаем с одного города (Москва активна), остальные заведены заранее,
но выключены — их включают в админке по мере запуска.
"""

from django.db import migrations

# (название, slug, страна, валюта, активен ли сразу)
CITIES = [
    ("Москва", "moskva", "RU", "RUB", True),
    ("Санкт-Петербург", "spb", "RU", "RUB", False),
    ("Казань", "kazan", "RU", "RUB", False),
    ("Екатеринбург", "ekaterinburg", "RU", "RUB", False),
    ("Новосибирск", "novosibirsk", "RU", "RUB", False),
    ("Нижний Новгород", "nizhniy-novgorod", "RU", "RUB", False),
    ("Алматы", "almaty", "KZ", "KZT", False),
    ("Астана", "astana", "KZ", "KZT", False),
    ("Минск", "minsk", "BY", "BYN", False),
    ("Ташкент", "tashkent", "UZ", "UZS", False),
    ("Ереван", "erevan", "AM", "AMD", False),
    ("Тбилиси", "tbilisi", "GE", "GEL", False),
    ("Бишкек", "bishkek", "KG", "KGS", False),
]


def create_cities(apps, schema_editor):
    """Создаёт города, если их ещё нет (повторный запуск безопасен)."""
    City = apps.get_model("geo", "City")
    for name, slug, country, currency, active in CITIES:
        City.objects.get_or_create(
            slug=slug, defaults={"name": name, "country": country, "currency": currency, "is_active": active}
        )


def remove_cities(apps, schema_editor):
    """Откат миграции: удаляет добавленные города."""
    City = apps.get_model("geo", "City")
    City.objects.filter(slug__in=[c[1] for c in CITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("geo", "0001_initial")]

    operations = [migrations.RunPython(create_cities, remove_cities)]
