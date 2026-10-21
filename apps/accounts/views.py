"""Страницы регистрации, входа, анкеты и удаления аккаунта."""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.moderation.services import is_blocked_between
from config import ratelimit

from . import verification
from .forms import DeleteAccountForm, LoginForm, ProfileForm, SignUpForm
from .models import Invite, User

logger = logging.getLogger(__name__)


def _client_ip(request) -> str:
    """IP посетителя. За прокси хостинга настоящий адрес лежит в X-Forwarded-For."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def signup(request):
    """Регистрация: после неё сразу входим и отправляем заполнять анкету.

    В закрытом тесте нужен код приглашения. Ссылка вида ?invite=КОД
    подставляет код в форму автоматически.
    """
    if request.user.is_authenticated:
        return redirect("matching:feed")

    # Код берём из ссылки (?invite=КОД) или из формы, если человек ввёл его сам
    code = (request.POST.get("invite_code") or request.GET.get("invite") or "").strip().upper()
    form = SignUpForm(request.POST or None, initial={"invite_code": code})

    # Статус приглашения для подсказки над формой:
    # «ok» — по ссылке пришёл рабочий код, поле с кодом не показываем;
    # «bad» — код устарел или уже использован, сразу говорим об этом;
    # None — кода нет, человек вводит его сам.
    invite_status = None
    if settings.INVITE_ONLY and code:
        invite_status = "ok" if Invite.objects.usable().filter(code=code).exists() else "bad"

    def render_form():
        return render(request, "accounts/signup.html", {"form": form, "invite_status": invite_status, "code": code})

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if settings.INVITE_ONLY:
                # Блокируем строку приглашения, чтобы по одному коду не зарегистрировались двое одновременно
                invite = Invite.objects.select_for_update().filter(pk=form.invite.pk, used_by__isnull=True).first()
                if invite is None:
                    form.add_error("invite_code", "Приглашение уже использовано")
                    invite_status = "bad"
                    return render_form()
            user = form.save()
            if settings.INVITE_ONLY:
                invite.used_by = user
                invite.used_at = timezone.now()
                invite.save(update_fields=["used_by", "used_at"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        if settings.EMAIL_VERIFICATION_REQUIRED:
            verification.send_in_background(user)
            messages.success(
                request,
                f"Добро пожаловать! Мы отправили письмо на {user.email} — подтвердите почту, "
                "чтобы ставить лайки и писать. А пока расскажите о себе.",
            )
        else:
            messages.success(request, "Добро пожаловать! Расскажите о себе — это займёт пару минут.")
        return redirect("accounts:profile_edit")
    return render_form()


class RateLimitedLoginView(LoginView):
    """Вход с защитой от подбора пароля.

    После LOGIN_MAX_FAILURES неудачных попыток вход блокируется на
    LOGIN_LOCKOUT_SECONDS — и для этого email, и для этого IP-адреса
    (иначе можно было бы перебирать пароли к разным аккаунтам).
    """

    template_name = "accounts/login.html"
    form_class = LoginForm

    def _idents(self):
        email = (self.request.POST.get("username") or "").strip().lower()
        return [("login-ip", _client_ip(self.request)), ("login-email", email)]

    def _is_locked(self) -> bool:
        return any(ratelimit.count(scope, ident) >= settings.LOGIN_MAX_FAILURES for scope, ident in self._idents())

    def post(self, request, *args, **kwargs):
        if self._is_locked():
            form = self.get_form()
            form.errors.clear()
            form.add_error(None, "Слишком много неудачных попыток входа. Попробуйте через 15 минут.")
            logger.warning("Вход заблокирован после неудачных попыток: ip=%s", _client_ip(request))
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        for scope, ident in self._idents():
            ratelimit.hit(scope, ident, settings.LOGIN_LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        for scope, ident in self._idents():
            ratelimit.reset(scope, ident)
        return super().form_valid(form)


@login_required
def profile_edit(request):
    """Редактирование своей анкеты."""
    profile = request.user.profile
    old_photo_name = profile.photo.name if profile.photo else ""
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Старое фото удаляем из хранилища, если его заменили или убрали
        if old_photo_name and old_photo_name != (profile.photo.name if profile.photo else ""):
            profile.photo.storage.delete(old_photo_name)
        messages.success(request, "Анкета сохранена")
        return redirect("matching:feed")
    from apps.notifications import telegram
    from apps.notifications.services import email_configured, settings_for

    context = {
        "form": form,
        "notif": settings_for(request.user),
        "email_notifications_available": email_configured(),
        "telegram_available": telegram.is_configured(),
    }
    return render(request, "accounts/profile_edit.html", context)


@login_required
def profile_detail(request, user_id: int):
    """Публичная анкета человека (скрытые, удалённые и заблокированные не показываем)."""
    person = get_object_or_404(
        User.objects.select_related("profile", "profile__city"),
        pk=user_id,
        is_active=True,
        profile__is_hidden=False,
    )
    if person.pk != request.user.pk and is_blocked_between(request.user, person):
        raise Http404
    return render(request, "accounts/profile_detail.html", {"person": person})


@login_required
def account_delete(request):
    """Удаление аккаунта и всех данных пользователя (право по 152-ФЗ).

    Удаляются анкета, объявления, фото, свайпы, мэтчи и переписки.
    Файлы фото стираются из хранилища до удаления записей.
    """
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        # Сначала собираем файлы, потом удаляем записи, потом файлы
        files = []
        if user.profile.photo:
            files.append((user.profile.photo.storage, user.profile.photo.name))
        for listing in user.listings.prefetch_related("photos"):
            for photo in listing.photos.all():
                files.append((photo.image.storage, photo.image.name))

        logout(request)
        user.delete()
        for storage, name in files:
            storage.delete(name)

        messages.info(request, "Аккаунт и все ваши данные удалены. Спасибо, что были с нами.")
        return redirect("home")
    return render(request, "accounts/account_delete.html", {"form": form})


def verify_email(request, token: str):
    """Переход по ссылке из письма."""
    user = verification.confirm(token)
    if user is None:
        messages.error(request, "Ссылка устарела или неверна. Войдите и отправьте письмо ещё раз.")
        return redirect("accounts:login" if not request.user.is_authenticated else "matching:feed")
    messages.success(request, "Почта подтверждена! Теперь можно ставить лайки и писать сообщения.")
    return redirect("matching:feed" if request.user.is_authenticated else "accounts:login")


@login_required
@require_POST
def resend_verification(request):
    """Кнопка «Отправить письмо ещё раз» (не чаще 3 раз в час)."""
    user = request.user
    if user.email_verified_at:
        messages.info(request, "Почта уже подтверждена")
    elif ratelimit.is_limited("verify_resend", str(user.pk), 3, 60 * 60):
        messages.error(request, "Письмо уже отправлено несколько раз. Проверьте папку «Спам» или попробуйте через час.")
    else:
        verification.send_in_background(user)
        messages.success(request, f"Письмо отправлено на {user.email}. Проверьте и папку «Спам».")
    return redirect(request.POST.get("next") or "matching:feed")
