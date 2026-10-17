"""Форма жалобы."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.listings.models import Listing

from .models import Report
from .services import block_user, file_report


class ReportForm(forms.Form):
    """Причина жалобы и необязательный комментарий."""

    reason = forms.ChoiceField(label="Причина", choices=Report.Reason.choices, widget=forms.RadioSelect)
    comment = forms.CharField(
        label="Подробности",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Что произошло? Это поможет модератору."}),
    )
    also_block = forms.BooleanField(label="Заодно заблокировать этого пользователя", required=False, initial=True)


@login_required
@require_POST
def block(request, user_id: int):
    """Заблокировать пользователя: он пропадёт из лент и чатов, общие мэтчи закроются."""
    blocked = get_object_or_404(User, pk=user_id)
    if blocked.pk == request.user.pk:
        messages.error(request, "Нельзя заблокировать себя.")
        return redirect("matching:matches")
    block_user(request.user, blocked)
    messages.info(request, "Пользователь заблокирован. Вы больше не увидите друг друга.")
    return redirect("matching:matches")


@login_required
def report_user(request, user_id: int):
    """Пожаловаться на пользователя (и, опционально, на его объявление)."""
    reported = get_object_or_404(User, pk=user_id)
    if reported.pk == request.user.pk:
        messages.error(request, "Нельзя пожаловаться на себя.")
        return redirect("matching:feed")

    listing = None
    listing_id = request.GET.get("listing") or request.POST.get("listing")
    if listing_id and str(listing_id).isdigit():
        listing = Listing.objects.filter(pk=int(listing_id), owner=reported).first()

    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        file_report(
            reporter=request.user,
            reported_user=reported,
            reason=form.cleaned_data["reason"],
            comment=form.cleaned_data["comment"],
            listing=listing,
        )
        if form.cleaned_data["also_block"]:
            block_user(request.user, reported)
            messages.success(request, "Спасибо! Жалоба отправлена модераторам, пользователь заблокирован.")
        else:
            messages.success(request, "Спасибо! Жалоба отправлена модераторам.")
        return redirect("matching:feed")

    return render(request, "moderation/report.html", {"form": form, "reported": reported, "listing": listing})
