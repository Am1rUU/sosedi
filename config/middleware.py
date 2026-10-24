"""Общие middleware проекта."""

from django.conf import settings
from django.http import HttpResponse

# Адрес, по которому хостинг (Timeweb App Platform) проверяет, что приложение живо
HEALTHCHECK_PATH = "/healthz/"


class HealthCheckMiddleware:
    """Отвечает «ok» на проверку здоровья от хостинга.

    Стоит первым в списке middleware и отвечает раньше остальных. Это важно:
    хостинг стучится внутри своей сети по http и с внутренним адресом вместо
    домена. Дальше по цепочке Django ответил бы редиректом на https
    (SECURE_SSL_REDIRECT) или ошибкой 400 из-за ALLOWED_HOSTS, и хостинг
    решил бы, что приложение упало.

    База данных намеренно не проверяется: если она недоступна, перезапуск
    контейнера не поможет, а только добавит простоя.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTHCHECK_PATH:
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


class NoIndexMiddleware:
    """Просит поисковики не индексировать сайт, пока идёт закрытый тест.

    Заголовок X-Robots-Tag действует на любые ответы, включая фото и файлы,
    в отличие от robots.txt, который поисковики могут проигнорировать для
    ссылок, найденных на сторонних сайтах.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.SITE_NOINDEX:
            response["X-Robots-Tag"] = "noindex, nofollow"
        return response


class LastSeenMiddleware:
    """Запоминает, когда человек последний раз заходил на сайт.

    Чтобы не писать в базу на каждый клик, обновляем не чаще раза в 10 минут:
    время последней записи держим в сессии. Если человек не заходил так долго,
    что его анкета и объявления были скрыты из лент, — сообщаем, что они снова видны.
    """

    UPDATE_EVERY_SECONDS = 600
    SESSION_KEY = "last_seen_ts"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            self._touch(request, user)
        return self.get_response(request)

    def _touch(self, request, user):
        import time
        from datetime import timedelta

        from django.contrib import messages
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        now_ts = time.time()
        last_ts = request.session.get(self.SESSION_KEY)
        if last_ts and now_ts - last_ts < self.UPDATE_EVERY_SECONDS:
            return

        now = timezone.now()
        previous = user.last_seen_at
        get_user_model().objects.filter(pk=user.pk).update(last_seen_at=now)
        user.last_seen_at = now
        request.session[self.SESSION_KEY] = now_ts

        # Отметка «заходил в этот день» — для удержания по неделям на странице статистики
        from apps.analytics.models import DailyVisit

        DailyVisit.objects.get_or_create(user_id=user.pk, date=timezone.localdate(now))

        if previous and now - previous > timedelta(days=settings.ACTIVITY_HIDE_DAYS):
            messages.info(
                request,
                "С возвращением! Пока вас не было, мы не показывали вашу анкету и объявления в ленте. "
                "Теперь их снова видят.",
            )
