"""Переменные, доступные во всех шаблонах."""

from django.conf import settings


def site_flags(request):
    """Флаги режима сайта и счётчик для значка «Мэтчи» в нижнем меню."""
    context = {
        "INVITE_ONLY": settings.INVITE_ONLY,
        "SITE_NOINDEX": settings.SITE_NOINDEX,
        "nav_badge": 0,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        # Импорт внутри функции: модели загружаются после настроек
        from django.db.models import Q

        from apps.matching.models import Match
        from apps.messaging.models import Message

        open_matches = Match.objects.filter(Q(seeker=user) | Q(listing__owner=user), is_closed=False)
        unread = Message.objects.filter(match__in=open_matches, read_at__isnull=True).exclude(sender=user).count()
        not_started = open_matches.filter(messages__isnull=True).count()
        context["nav_badge"] = unread + not_started
    return context
