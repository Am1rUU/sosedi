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
