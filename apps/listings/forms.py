"""Форма объявления с загрузкой нескольких фото."""

from django import forms
from django.conf import settings

from apps.geo.models import City
from config.images import process_photo

from .models import Listing

# Сколько фото можно прикрепить к объявлению
MAX_PHOTOS = 10


class MultipleFileInput(forms.ClearableFileInput):
    """Поле выбора файлов, разрешающее выбрать несколько фото сразу."""

    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Поле формы, которое принимает и проверяет список изображений."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/*"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data if item]
        return [single_clean(data, initial)] if data else []


class ListingForm(forms.ModelForm):
    """Создание и редактирование объявления."""

    photos = MultipleImageField(label="Фото (до 10 штук)", required=False)

    class Meta:
        model = Listing
        fields = [
            "title",
            "city",
            "district",
            "metro",
            "metro_walk_minutes",
            "metro_transport_minutes",
            "room_type",
            "room_area",
            "flat_area",
            "kitchen_area",
            "rent",
            "deposit",
            "bills_included",
            "furnished",
            "available_from",
            "min_term_months",
            "flatmates_count",
            "smoking_allowed",
            "pets_allowed",
            "preferred_gender",
            "description",
        ]
        widgets = {
            "available_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(
                attrs={"rows": 6, "placeholder": "Опишите комнату, квартиру, соседей и правила дома"}
            ),
            "room_area": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "14"}),
            "flat_area": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "65"}),
            "kitchen_area": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "9"}),
            "metro_walk_minutes": forms.NumberInput(attrs={"placeholder": "Например, 7", "min": 1, "max": 120}),
            "metro_transport_minutes": forms.NumberInput(attrs={"placeholder": "Например, 10", "min": 1, "max": 120}),
            "title": forms.TextInput(attrs={"placeholder": "Например: Светлая комната у м. Таганская"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].queryset = City.objects.filter(is_active=True)
        # В форме площади стоят в одну строку под общим заголовком «Площадь, м²»
        self.fields["room_area"].label = "Комната"
        self.fields["flat_area"].label = "Квартира"
        self.fields["kitchen_area"].label = "Кухня"

    def clean(self):
        data = super().clean()
        room_area, flat_area, kitchen_area = data.get("room_area"), data.get("flat_area"), data.get("kitchen_area")
        if kitchen_area and flat_area and kitchen_area >= flat_area:
            self.add_error("kitchen_area", "Кухня не может быть больше всей квартиры")
        # Квартира целиком — отдельная площадь комнаты не нужна
        if data.get("room_type") == Listing.RoomType.WHOLE:
            data["room_area"] = None
        elif room_area and flat_area and room_area > flat_area:
            self.add_error("room_area", "Комната не может быть больше всей квартиры")
        return data

    def clean_photos(self):
        """Проверяем количество и размер фото, затем сжимаем и стираем метаданные.

        Удаление EXIF здесь особенно важно: в фото комнаты могут быть
        GPS-координаты, а точный адрес мы не показываем вовсе.
        """
        photos = self.cleaned_data.get("photos") or []
        existing = self.instance.photos.count() if self.instance.pk else 0
        if existing + len(photos) > MAX_PHOTOS:
            raise forms.ValidationError(f"Максимум {MAX_PHOTOS} фото в объявлении")
        for photo in photos:
            if photo.size > settings.MAX_PHOTO_SIZE_BYTES:
                raise forms.ValidationError(f"Фото «{photo.name}» больше 10 МБ")
        return [process_photo(photo) for photo in photos]
