"""Корневая маршрутизация: подключает адреса каждого модуля."""

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.views.static import serve

# Заголовки админки — это рабочее место модераторов
admin.site.site_header = "Соседи — модерация"
admin.site.site_title = "Соседи"
admin.site.index_title = "Управление сервисом"


def robots_txt(request):
    """robots.txt: на время закрытого теста запрещаем поисковикам весь сайт."""
    if settings.SITE_NOINDEX:
        body = "User-agent: *\nDisallow: /\n"
    else:
        body = "User-agent: *\nDisallow: /admin/\nDisallow: /accounts/\nDisallow: /chat/\n"
    return HttpResponse(body, content_type="text/plain")


urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("listings/", include("apps.listings.urls")),
    path("feed/", include("apps.matching.urls")),
    path("chat/", include("apps.messaging.urls")),
    path("report/", include("apps.moderation.urls")),
    path("robots.txt", robots_txt, name="robots"),
    # Проверка живости для балансировщика и мониторинга
    path("healthz/", TemplateView.as_view(template_name="healthz.txt", content_type="text/plain"), name="healthz"),
]

# Загруженные фото раздаёт сам Django, пока не подключено отдельное хранилище (S3).
# Для закрытого теста этого достаточно; при росте нагрузки фото переедут в S3.
if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
