"""Страница «Статистика» в админке."""

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from . import metrics


@staff_member_required
def dashboard(request):
    period = request.GET.get("period", "30")
    if period not in metrics.PERIODS:
        period = "30"
    include_fake = request.GET.get("fake") == "1"
    context = {
        **admin.site.each_context(request),
        "title": "Статистика",
        "dash": metrics.build(period, include_fake),
        "period": period,
        "periods": [("7", "7 дней"), ("30", "30 дней"), ("90", "90 дней"), ("all", "Всё время")],
        "include_fake": include_fake,
    }
    return render(request, "admin/analytics.html", context)
