"""Форма фильтров ленты комнат."""

from django import forms

from apps.geo.models import City

from .models import SearchFilters


class SearchFiltersForm(forms.ModelForm):
    room_types = forms.MultipleChoiceField(
        label="Тип жилья",
        choices=SearchFilters.RoomType.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Ничего не выбрано — показываем любой.",
    )
    max_walk_minutes = forms.TypedChoiceField(
        label="Пешком до метро",
        choices=[("", "Не важно"), *SearchFilters.WALK_CHOICES],
        coerce=int,
        empty_value=None,
        required=False,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = SearchFilters
        fields = [
            "city",
            "rent_min",
            "rent_max",
            "room_types",
            "min_room_area",
            "areas",
            "areas_only",
            "max_walk_minutes",
            "available_by",
            "furnished_only",
            "bills_included_only",
            "pets_needed",
            "smoking_needed",
        ]
        labels = {
            "pets_needed": "Только где можно с животными",
            "smoking_needed": "Только где можно курить",
        }
        widgets = {
            "rent_min": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "Например, 20000"}),
            "rent_max": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "Например, 40000"}),
            "min_room_area": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "Например, 12"}),
            "areas": forms.TextInput(attrs={"placeholder": "Например: Таганская, Курская, Сокол"}),
            "available_by": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {
            "areas": "Через запятую. Такие комнаты покажем выше в ленте.",
            "available_by": "Комнаты, свободные к этой дате, покажем выше.",
            "min_room_area": "Для квартиры целиком — площадь всей квартиры. Где площадь не указана, тоже покажем.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].queryset = City.objects.filter(is_active=True)
        self.fields["city"].empty_label = "Выберите город"
        self.fields["city"].required = True
        self.initial.setdefault("room_types", self.instance.room_type_list)

    def clean(self):
        data = super().clean()
        rent_min, rent_max = data.get("rent_min"), data.get("rent_max")
        if rent_min and rent_max and rent_min > rent_max:
            self.add_error("rent_max", "«Цена до» должна быть больше «цены от»")
        return data

    def save(self, commit=True):
        self.instance.room_types = ",".join(self.cleaned_data.get("room_types") or [])
        return super().save(commit)
