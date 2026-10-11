from django.contrib import admin

from .models import Match, Swipe


@admin.register(Swipe)
class SwipeAdmin(admin.ModelAdmin):
    """Просмотр свайпов — пригодится для разбора жалоб и аналитики."""

    list_display = ("listing", "seeker", "side", "decision", "created_at")
    list_filter = ("side", "decision")
    raw_id_fields = ("listing", "seeker")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    """Список мэтчей."""

    list_display = ("listing", "seeker", "created_at", "is_closed")
    list_filter = ("is_closed",)
    raw_id_fields = ("listing", "seeker")
