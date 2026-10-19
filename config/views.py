"""Общие страницы проекта."""

import logging

from django.shortcuts import render

logger = logging.getLogger(__name__)


def csrf_failure(request, reason=""):
    """Понятная страница, если форма не прошла защиту от подделки запросов (CSRF).

    Чаще всего это значит, что форма «устарела»: страница была открыта давно,
    или в соседней вкладке человек вошёл или вышел из аккаунта. Достаточно
    открыть форму заново. Техническая причина пишется в лог для разбора.
    """
    logger.warning(
        "Форма отклонена защитой CSRF: %s (путь %s, origin %s, https=%s)",
        reason,
        request.path,
        request.META.get("HTTP_ORIGIN", "-"),
        request.is_secure(),
    )
    return render(request, "csrf_failure.html", {"retry_url": request.path}, status=403)
