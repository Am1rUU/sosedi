from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Profile, User


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

    list_display = ("__str__", "user", "city", "is_seeking", "is_hidden", "updated_at")
    list_filter = ("is_seeking", "is_hidden", "city", "gender")
    list_editable = ("is_hidden",)
    search_fields = ("display_name", "user__email", "about")
    raw_id_fields = ("user",)
