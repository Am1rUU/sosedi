from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("user/<int:user_id>/", views.report_user, name="report_user"),
    path("block/<int:user_id>/", views.block, name="block"),
]
