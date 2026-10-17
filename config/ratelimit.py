"""Простое ограничение частоты действий через кэш Django.

Используется для защиты от подбора пароля и от ботов, которые лайкают
или пишут всем подряд. Это не платный лимит: пороги заданы так, чтобы
живой человек их не замечал.

Счётчик «фиксированного окна»: первое действие открывает окно на window секунд,
внутри окна считаем действия, по истечении окна счёт начинается заново.
"""

from django.core.cache import cache


def _key(scope: str, ident: str) -> str:
    return f"rl:{scope}:{ident}"


def hit(scope: str, ident: str, window: int) -> int:
    """Учитывает одно действие и возвращает, сколько их было в текущем окне."""
    key = _key(scope, ident)
    # add() срабатывает, только если ключа ещё нет — так открывается новое окно
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # Окно истекло между add() и incr() — начинаем заново
        cache.set(key, 1, timeout=window)
        return 1


def count(scope: str, ident: str) -> int:
    """Сколько действий уже было в текущем окне (без учёта нового)."""
    return cache.get(_key(scope, ident), 0)


def reset(scope: str, ident: str) -> None:
    """Сбрасывает счётчик (например, после успешного входа)."""
    cache.delete(_key(scope, ident))


def is_limited(scope: str, ident: str, limit: int, window: int) -> bool:
    """Учитывает действие и сообщает, превышен ли лимит."""
    return hit(scope, ident, window) > limit
