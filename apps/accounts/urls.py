from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    # Вход — с защитой от подбора пароля; выход — встроенное представление Django
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("start/", views.start, name="start"),
    path("role/", views.switch_role, name="switch_role"),
    path("search/", views.search, name="search"),
    path("profile/", views.profile_edit, name="profile_edit"),
    path("delete/", views.account_delete, name="delete"),
    path("people/<int:user_id>/", views.profile_detail, name="profile_detail"),
    path("verify/resend/", views.resend_verification, name="resend_verification"),
    path("verify-profile/", views.verify_profile, name="verify_profile"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
]
