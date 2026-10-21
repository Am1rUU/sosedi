"""Переменные, доступные во всех шаблонах."""

from django.conf import settings


def site_flags(request):
    """Флаги режима сайта и счётчик для значка «Мэтчи» в нижнем меню."""
    context = {
        "INVITE_ONLY": settings.INVITE_ONLY,
        "SITE_NOINDEX": settings.SITE_NOINDEX,
        "nav_badge": 0,
        "email_unverified": False,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        # Импорт внутри функции: модели загружаются после настроек
        from django.db.models import Q

        from apps.matching.models import Match
        from apps.messaging.models import Message

        open_matches = Match.objects.filter(Q(seeker=user) | Q(listing__owner=user), is_closed=False)
        unread = (
            Message.objects.filter(match__in=open_matches, read_at__isnull=True, deleted_at__isnull=True)
            .exclude(sender=user)
            .count()
        )
        not_started = open_matches.filter(messages__isnull=True).count()
        from apps.matching.services import incoming_likes_for_seeker

        context["nav_badge"] = unread + not_started + incoming_likes_for_seeker(user).count()
        context["email_unverified"] = not user.can_interact

        # Вопрос «Нашли соседа/комнату?» — только на страницах сайта, не в админке
        on_answer_page = getattr(request.resolver_match, "url_name", "") == "found"
        if not request.path.startswith("/admin/") and request.method == "GET" and not on_answer_page:
            from apps.matching.outcomes import pending_prompt

            context["found_prompt"] = pending_prompt(user)
    return context
