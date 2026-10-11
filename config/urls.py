"""Корневая маршрутизация: подключает адреса каждого модуля."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

# Заголовки админки — это рабочее место модераторов
admin.site.site_header = "Соседи — модерация"
admin.site.site_title = "Соседи"
admin.site.index_title = "Управление сервисом"

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("listings/", include("apps.listings.urls")),
    path("feed/", include("apps.matching.urls")),
    path("chat/", include("apps.messaging.urls")),
    path("report/", include("apps.moderation.urls")),
    # Проверка живости для балансировщика и мониторинга
    path("healthz/", TemplateView.as_view(template_name="healthz.txt", content_type="text/plain"), name="healthz"),
]

# Локально раздаём загруженные фото самим Django (в проде этим занимается хранилище)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
