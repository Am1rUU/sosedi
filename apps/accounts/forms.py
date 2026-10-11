"""Формы регистрации и редактирования анкеты."""

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm

from apps.geo.models import City

from .models import Profile, User


class SignUpForm(UserCreationForm):
    """Регистрация по email и паролю."""

    # Явное согласие на обработку персональных данных — требование 152-ФЗ
    accept_terms = forms.BooleanField(
        label="Я соглашаюсь с правилами сервиса и обработкой персональных данных",
        required=True,
    )

    class Meta:
        model = User
        fields = ("email",)

    def clean_email(self):
        """Email храним в нижнем регистре, чтобы не было дублей вида Ivan@ и ivan@."""
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже зарегистрирован")
        return email


class ProfileForm(forms.ModelForm):
    """Редактирование анкеты: о себе, что ищу, образ жизни."""

    class Meta:
        model = Profile
        fields = [
            "display_name",
            "birth_year",
            "gender",
            "occupation",
            "about",
            "photo",
            "is_seeking",
            "city",
            "preferred_districts",
            "budget_max",
            "move_in_date",
            "smoker",
            "has_pets",
            "works_from_home",
            "schedule",
        ]
        widgets = {
            "about": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Чем занимаетесь, какой вы сосед, что важно в быту"}
            ),
            "move_in_date": forms.DateInput(attrs={"type": "date"}),
            "preferred_districts": forms.TextInput(attrs={"placeholder": "Например: Таганская, Курская, ЦАО"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # В выборе только города, где сервис запущен
        self.fields["city"].queryset = City.objects.filter(is_active=True)
        self.fields["display_name"].required = True
        self.fields["city"].required = True

    def clean_photo(self):
        """Ограничиваем размер фото, чтобы не забивать хранилище."""
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > settings.MAX_PHOTO_SIZE_BYTES:
            raise forms.ValidationError("Фото слишком большое, максимум 5 МБ")
        return photo
