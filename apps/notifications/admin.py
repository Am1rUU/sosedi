from django.contrib import admin

from .models import NotificationSettings


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "email_enabled", "telegram_enabled", "telegram_connected_display")
    list_filter = ("email_enabled", "telegram_enabled")
    search_fields = ("user__email", "telegram_username")
    raw_id_fields = ("user",)
    readonly_fields = ("telegram_chat_id", "telegram_username", "telegram_link_code", "telegram_link_created_at")

    @admin.display(boolean=True, description="Telegram подключён")
    def telegram_connected_display(self, obj):
        return obj.telegram_connected
