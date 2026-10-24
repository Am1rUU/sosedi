from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import Invite, Profile, User, VerificationRequest
from .services import invite_url


class ProfileInline(admin.StackedInline):
    """Анкета прямо на странице пользователя — модератору не надо прыгать между разделами."""

    model = Profile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Админка пользователей с входом по email вместо логина."""

    ordering = ("-date_joined",)
    list_display = ("email", "first_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    inlines = [ProfileInline]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Личные данные", {"fields": ("first_name", "last_name")}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Список анкет для модерации: быстро найти и скрыть подозрительные."""

    list_display = ("__str__", "user", "city", "is_seeking", "is_hidden", "verified_at", "updated_at")
    list_filter = ("is_seeking", "is_hidden", ("verified_at", admin.EmptyFieldListFilter), "city", "gender")
    list_editable = ("is_hidden",)
    search_fields = ("display_name", "user__email", "about")
    raw_id_fields = ("user",)


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    """Приглашения для закрытого теста.

    Как пригласить человека: «Добавить приглашение» → впишите, для кого →
    сохраните → скопируйте ссылку из колонки «Ссылка» и отправьте её.
    """

    list_display = ("code", "note", "channel", "link", "status", "used_by", "created_at")
    list_filter = ("is_active", "channel")
    search_fields = ("code", "note", "channel", "used_by__email")
    readonly_fields = ("code", "link", "used_by", "used_at", "created_at")
    fields = ("note", "channel", "is_active", "code", "link", "used_by", "used_at", "created_at")
    actions = ["revoke"]

    @admin.display(description="Ссылка для приглашения")
    def link(self, obj):
        if not obj.pk:
            return "Появится после сохранения"
        url = invite_url(obj)
        return format_html('<input type="text" value="{}" readonly style="width: 28em" onclick="this.select()">', url)

    @admin.display(description="Статус")
    def status(self, obj):
        if obj.used_by_id:
            return "Использовано"
        return "Ждёт" if obj.is_active else "Отозвано"

    @admin.action(description="Отозвать выбранные приглашения")
    def revoke(self, request, queryset):
        updated = queryset.filter(used_by__isnull=True).update(is_active=False)
        self.message_user(request, f"Отозвано приглашений: {updated}")


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    """История заявок на верификацию. Проверять — на экране «Верификация профилей»."""

    list_display = ("user", "status", "reject_reason", "created_at", "reviewed_at", "reviewed_by")
    list_filter = ("status", "reject_reason")
    search_fields = ("user__email", "user__profile__display_name")
    readonly_fields = (
        "user",
        "gesture",
        "selfie",
        "profile_photo_name",
        "status",
        "reject_reason",
        "created_at",
        "reviewed_at",
        "reviewed_by",
    )

    def has_add_permission(self, request):
        return False
