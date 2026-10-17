"""Общие middleware проекта."""

from django.conf import settings


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
