from django.contrib import admin

from .models import City


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    """Управление списком городов: включение и выключение запуска."""

    list_display = ("name", "country", "currency", "is_active")
    list_filter = ("country", "is_active")
    list_editable = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
