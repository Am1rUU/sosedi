"""Выключатели новых функций (FeatureFlag): постепенный запуск без деплоя.

features.enabled(user, "roles")   — видит ли этот человек новую функцию
features.for_everyone("roles")    — включена ли она всем (меняет поведение лент для всех)
"""

from django.core.cache import cache

CACHE_SECONDS = 30


def mode(key: str) -> str:
    cache_key = f"feature:{key}"
    try:
        value = cache.get(cache_key)
    except OSError:
        value = None
    if value is None:
        from .models import FeatureFlag

        value = FeatureFlag.objects.filter(key=key).values_list("mode", flat=True).first() or "off"
        try:
            cache.set(cache_key, value, CACHE_SECONDS)
        except OSError:
            pass
    return value


def enabled(user, key: str) -> bool:
    current = mode(key)
    if current == "all":
        return True
    if current == "staff":
        return bool(user is not None and getattr(user, "is_authenticated", False) and user.is_staff)
    return False


def for_everyone(key: str) -> bool:
    return mode(key) == "all"


def reset_cache(key: str) -> None:
    try:
        cache.delete(f"feature:{key}")
    except OSError:
        pass
