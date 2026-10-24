from django.contrib import admin
from django.utils import timezone

from apps.listings.models import Listing

from .models import Block, Report


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    """Кто кого заблокировал. Здесь же можно снять блокировку по просьбе пользователя."""

    list_display = ("blocker", "blocked", "created_at")
    search_fields = ("blocker__email", "blocked__email")
    raw_id_fields = ("blocker", "blocked")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Очередь жалоб. По умолчанию модератор фильтрует по статусу «Новая»."""

    list_display = ("reason", "reported_user", "listing", "reporter", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("reported_user__email", "reporter__email", "comment")
    raw_id_fields = ("reporter", "reported_user", "listing")
    actions = ["ban_user", "reject"]

    def save_model(self, request, obj, form, change):
        # Статус сменили вручную в карточке жалобы — запоминаем время решения
        if obj.status != Report.Status.OPEN and obj.resolved_at is None:
            obj.resolved_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="Принять меры: заблокировать пользователя и его объявления")
    def ban_user(self, request, queryset):
        """Блокирует нарушителей: деактивирует аккаунт, скрывает анкету и объявления."""
        users = {report.reported_user for report in queryset}
        for user in users:
            user.is_active = False
            user.save(update_fields=["is_active"])
            user.profile.is_hidden = True
            user.profile.save(update_fields=["is_hidden"])
            user.listings.update(status=Listing.Status.BLOCKED)
        queryset.update(status=Report.Status.RESOLVED, resolved_at=timezone.now())
        self.message_user(request, f"Заблокировано пользователей: {len(users)}")

    @admin.action(description="Отклонить жалобы")
    def reject(self, request, queryset):
        updated = queryset.update(status=Report.Status.REJECTED, resolved_at=timezone.now())
        self.message_user(request, f"Отклонено жалоб: {updated}")
