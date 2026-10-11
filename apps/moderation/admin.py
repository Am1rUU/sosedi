from django.contrib import admin

from apps.listings.models import Listing

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Очередь жалоб. По умолчанию модератор фильтрует по статусу «Новая»."""

    list_display = ("reason", "reported_user", "listing", "reporter", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("reported_user__email", "reporter__email", "comment")
    raw_id_fields = ("reporter", "reported_user", "listing")
    actions = ["ban_user", "reject"]

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
        queryset.update(status=Report.Status.RESOLVED)
        self.message_user(request, f"Заблокировано пользователей: {len(users)}")

    @admin.action(description="Отклонить жалобы")
    def reject(self, request, queryset):
        updated = queryset.update(status=Report.Status.REJECTED)
        self.message_user(request, f"Отклонено жалоб: {updated}")
