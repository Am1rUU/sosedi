"""Экран модератора: очередь заявок на верификацию профиля."""

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render

from . import profile_verification
from .models import VerificationRequest


@staff_member_required
def verification_queue(request):
    """Самая старая ожидающая заявка: фото анкеты и селфи рядом, кнопки «Подтвердить» / «Отклонить»."""
    if request.method == "POST":
        request_obj = get_object_or_404(
            VerificationRequest, pk=request.POST.get("request_id"), status=VerificationRequest.Status.PENDING
        )
        try:
            if request.POST.get("action") == "approve":
                profile_verification.approve(request_obj, request.user)
                messages.success(request, f"Профиль {request_obj.user} подтверждён")
            else:
                profile_verification.reject(request_obj, request.user, request.POST.get("reason", ""))
                messages.info(request, f"Заявка {request_obj.user} отклонена")
        except profile_verification.VerificationError as exc:
            messages.error(request, str(exc))
        return redirect("verification_queue")

    pending = VerificationRequest.objects.filter(status=VerificationRequest.Status.PENDING).select_related(
        "user__profile"
    )
    current = pending.first()
    context = {
        **admin.site.each_context(request),
        "title": "Верификация профилей",
        "current": current,
        "remaining": pending.count(),
        "photo_changed": bool(current)
        and (current.user.profile.photo.name if current.user.profile.photo else "") != current.profile_photo_name,
        "reasons": VerificationRequest.RejectReason.choices,
    }
    return render(request, "admin/verification_queue.html", context)
