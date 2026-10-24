from django import template

register = template.Library()


@register.filter
def heat(value):
    """Прозрачность ячейки когортной таблицы: 0% — почти прозрачно, 100% — насыщенный зелёный."""
    if value is None:
        return 0
    return round(0.08 + 0.82 * min(float(value), 100) / 100, 2)
