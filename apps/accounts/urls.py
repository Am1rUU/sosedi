from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    # Вход и выход — встроенные представления Django, только свой шаблон
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile_edit, name="profile_edit"),
    path("people/<int:user_id>/", views.profile_detail, name="profile_detail"),
]
