from django import template

from apps.accounts.profile_verification import pending_count

register = template.Library()


@register.simple_tag
def pending_verifications() -> int:
    """Сколько заявок на верификацию ждут модератора (для баннера на главной админки)."""
    return pending_count()
