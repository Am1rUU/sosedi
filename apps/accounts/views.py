"""Страницы регистрации, входа и анкеты."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ProfileForm, SignUpForm
from .models import User


def signup(request):
    """Регистрация: после неё сразу входим и отправляем заполнять анкету."""
    if request.user.is_authenticated:
        return redirect("matching:feed")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Добро пожаловать! Заполните анкету, чтобы начать.")
        return redirect("accounts:profile_edit")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def profile_edit(request):
    """Редактирование своей анкеты."""
    profile = request.user.profile
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Анкета сохранена")
        return redirect("matching:feed")
    return render(request, "accounts/profile_edit.html", {"form": form})


@login_required
def profile_detail(request, user_id: int):
    """Публичная анкета человека (скрытые и заблокированные не показываем)."""
    person = get_object_or_404(
        User.objects.select_related("profile", "profile__city"),
        pk=user_id,
        is_active=True,
        profile__is_hidden=False,
    )
    return render(request, "accounts/profile_detail.html", {"person": person})
