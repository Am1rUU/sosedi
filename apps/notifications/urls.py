from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("preferences/", views.update_preferences, name="preferences"),
    path("telegram/connect/", views.telegram_connect, name="telegram_connect"),
    path("telegram/disconnect/", views.telegram_disconnect, name="telegram_disconnect"),
]
