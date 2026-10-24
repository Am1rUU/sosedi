"""A/B-тесты: стабильное распределение людей по вариантам.

Использование в коде:

    from apps.analytics import ab
    if ab.variant(request.user, "feed_photo_first") == "B":
        ...  # новый вариант

Человек всегда попадает в один и тот же вариант (по хэшу id и ключа теста),
а первый показ записывается — так дашборд знает, кто участвовал и с какого момента.
Если теста нет или он выключен — возвращается контрольный (первый) вариант.
"""

import hashlib

from django.db import IntegrityError

from .models import Experiment, ExperimentAssignment


def _bucket(user_id: int, key: str, variants: list[str]) -> str:
    digest = hashlib.sha256(f"{key}:{user_id}".encode()).hexdigest()
    return variants[int(digest[:8], 16) % len(variants)]


def variant(user, key: str, default: str = "A") -> str:
    if user is None or not user.is_authenticated:
        return default
    experiment = Experiment.objects.filter(key=key).first()
    if experiment is None:
        return default
    variants = experiment.variant_list
    if not experiment.is_active:
        return variants[0]
    existing = ExperimentAssignment.objects.filter(experiment=experiment, user=user).values_list("variant", flat=True)
    for value in existing:
        return value
    chosen = _bucket(user.pk, key, variants)
    try:
        ExperimentAssignment.objects.create(experiment=experiment, user=user, variant=chosen)
    except IntegrityError:  # параллельный запрос уже записал
        pass
    return chosen
