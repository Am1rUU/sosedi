from django.contrib import admin

from .models import Match, Outcome, SearchFilters, Swipe


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


@admin.register(Outcome)
class OutcomeAdmin(admin.ModelAdmin):
    """Итоги поиска — главная метрика: сколько людей нашли соседа или комнату через сервис."""

    list_display = ("user", "role", "listing", "via_service_display", "created_at")
    list_filter = ("role", ("match", admin.EmptyFieldListFilter))
    raw_id_fields = ("user", "listing", "match")

    @admin.display(boolean=True, description="через «Соседей»")
    def via_service_display(self, obj):
        return obj.via_service


@admin.register(SearchFilters)
class SearchFiltersAdmin(admin.ModelAdmin):
    """Фильтры поиска — для разбора вопросов «почему мне не показывается…»."""

    list_display = ("user", "city", "rent_min", "rent_max", "room_types", "max_walk_minutes", "updated_at")
    raw_id_fields = ("user",)
