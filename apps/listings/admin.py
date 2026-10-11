from django.contrib import admin

from .models import Listing, ListingPhoto


class ListingPhotoInline(admin.TabularInline):
    """Фото объявления прямо в карточке — модератор видит всё сразу."""

    model = ListingPhoto
    extra = 0


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    """Модерация объявлений: очередь «На модерации», массовое одобрение и блокировка."""

    list_display = ("title", "city", "rent", "owner", "status", "created_at")
    list_filter = ("status", "city", "room_type")
    search_fields = ("title", "description", "owner__email", "district", "metro")
    raw_id_fields = ("owner",)
    inlines = [ListingPhotoInline]
    actions = ["approve", "block"]

    @admin.action(description="Одобрить выбранные объявления")
    def approve(self, request, queryset):
        updated = queryset.update(status=Listing.Status.ACTIVE)
        self.message_user(request, f"Одобрено объявлений: {updated}")

    @admin.action(description="Заблокировать выбранные объявления")
    def block(self, request, queryset):
        updated = queryset.update(status=Listing.Status.BLOCKED)
        self.message_user(request, f"Заблокировано объявлений: {updated}")
