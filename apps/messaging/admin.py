from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Сообщения доступны модератору только для разбора жалоб.

    Важно: доступ к переписке должен быть описан в политике конфиденциальности.
    """

    list_display = ("sender", "match", "short_text", "created_at")
    search_fields = ("text", "sender__email")
    raw_id_fields = ("match", "sender")

    @admin.display(description="текст")
    def short_text(self, obj):
        return obj.text[:80]
