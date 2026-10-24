from django.contrib import admin

from .models import Experiment


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    """A/B-тесты. Результаты — на странице «Статистика»."""

    list_display = ("name", "key", "variants", "is_active", "started_at", "ended_at")
    list_filter = ("is_active",)
    readonly_fields = ("started_at",)
