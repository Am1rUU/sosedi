"""Формы регистрации, анкеты и удаления аккаунта."""

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.files.uploadedfile import UploadedFile

from apps.geo.models import City
from config.images import process_photo

from .models import Invite, Profile, User


def _bool_choice(label: str, label_false: str, label_true: str) -> forms.TypedChoiceField:
    """Да/нет в виде двух кнопок-«таблеток» вместо галочки (как в макете)."""
    return forms.TypedChoiceField(
        label=label,
        choices=[("False", label_false), ("True", label_true)],
        coerce=lambda value: value == "True",
        widget=forms.RadioSelect(attrs={"class": "chip-input"}),
    )


class SignUpForm(UserCreationForm):
    """Регистрация по email и паролю. В закрытом тесте — только с кодом приглашения."""

    invite_code = forms.CharField(
        label="Код приглашения",
        max_length=16,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )
    # Явное согласие на обработку персональных данных — требование 152-ФЗ
    accept_terms = forms.BooleanField(
        label="Я соглашаюсь с правилами сервиса и обработкой персональных данных",
        required=True,
    )

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.invite = None
        if settings.INVITE_ONLY:
            self.fields["invite_code"].required = True
        else:
            del self.fields["invite_code"]

    def clean_email(self):
        """Email храним в нижнем регистре, чтобы не было дублей вида Ivan@ и ivan@."""
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже зарегистрирован")
        return email

    def clean_invite_code(self):
        """Код должен существовать, быть активным и ещё не использованным."""
        code = (self.cleaned_data.get("invite_code") or "").strip().upper()
        invite = Invite.objects.usable().filter(code=code).first()
        if not invite:
            raise forms.ValidationError("Приглашение не найдено или уже использовано")
        self.invite = invite
        return code


class LoginForm(AuthenticationForm):
    """Вход по email. Подписи переведены под наш интерфейс."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update({"autocomplete": "email", "inputmode": "email"})


class ProfileForm(forms.ModelForm):
    """Редактирование анкеты: о себе, что ищу, образ жизни."""

    smoker = _bool_choice("Курение", "Не курю", "Курю")
    has_pets = _bool_choice("Животные", "Нет животных", "Есть питомец")
    works_from_home = _bool_choice("Работа", "Работаю вне дома", "Работаю из дома")

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
            "move_in_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "preferred_districts": forms.TextInput(attrs={"placeholder": "Например: Таганская, Курская, ЦАО"}),
            "gender": forms.RadioSelect(attrs={"class": "chip-input"}),
            "schedule": forms.RadioSelect(attrs={"class": "chip-input"}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "budget_max": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "40000"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # В выборе только города, где сервис запущен
        self.fields["city"].queryset = City.objects.filter(is_active=True)
        self.fields["city"].empty_label = "Выберите город"
        self.fields["display_name"].required = True
        self.fields["city"].required = True
        self.fields["schedule"].choices = Profile.Schedule.choices

    def clean_photo(self):
        """Новое фото уменьшаем, сжимаем и очищаем от метаданных (в том числе GPS)."""
        photo = self.cleaned_data.get("photo")
        if isinstance(photo, UploadedFile):
            if photo.size > settings.MAX_PHOTO_SIZE_BYTES:
                raise forms.ValidationError("Фото слишком большое, максимум 10 МБ")
            return process_photo(photo)
        return photo


class DeleteAccountForm(forms.Form):
    """Подтверждение удаления аккаунта паролем — защита от случайного нажатия."""

    password = forms.CharField(
        label="Ваш пароль", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Неверный пароль")
        return password
