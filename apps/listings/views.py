"""Страницы объявлений: мои объявления, создание, редактирование, просмотр."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.matching.models import Match
from apps.matching.services import incoming_likes_for_listing

from .forms import ListingForm
from .models import Listing, ListingPhoto


def _save_photos(listing: Listing, photos) -> None:
    """Сохраняет загруженные фото в конец списка фото объявления."""
    start = listing.photos.count()
    for index, image in enumerate(photos):
        ListingPhoto.objects.create(listing=listing, image=image, position=start + index)


@login_required
def my_listings(request):
    """Список объявлений текущего пользователя с количеством входящих лайков."""
    listings = list(request.user.listings.select_related("city").prefetch_related("photos"))
    for listing in listings:
        # Сколько людей лайкнули объявление и ждут ответа — главный повод зайти в ленту
        listing.incoming_count = incoming_likes_for_listing(listing).count()
    return render(request, "listings/my_listings.html", {"listings": listings})


@login_required
def listing_create(request):
    """Создание объявления. При включённой премодерации оно уходит на проверку."""
    from apps.accounts import roles

    roles_on = roles.active(request.user)
    if roles_on:
        # В роли «Сдаю комнату» — одна комната на человека
        existing = roles.my_listing(request.user)
        if existing is not None:
            messages.info(request, "У вас уже есть комната — её можно изменить.")
            return redirect("listings:edit", existing.pk)
    form = ListingForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        listing = form.save(commit=False)
        listing.owner = request.user
        listing.status = Listing.Status.PENDING if settings.LISTINGS_PREMODERATION else Listing.Status.ACTIVE
        listing.save()
        _save_photos(listing, form.cleaned_data["photos"])
        if listing.status == Listing.Status.PENDING:
            messages.info(request, "Объявление отправлено на модерацию. Обычно это занимает несколько часов.")
        else:
            messages.success(request, "Объявление опубликовано. Теперь можно смотреть анкеты соседей.")
        if roles_on:
            if roles.role_of(request.user) != roles.OWNER:
                roles.switch(request.user, roles.OWNER)
            if listing.status == Listing.Status.ACTIVE:
                return redirect("matching:owner_feed", listing.pk)
            return redirect("accounts:profile_edit")
        return redirect("listings:my")
    return render(request, "listings/listing_form.html", {"form": form, "is_new": True})


@login_required
def listing_edit(request, pk: int):
    """Редактирование своего объявления."""
    listing = get_object_or_404(Listing, pk=pk, owner=request.user)
    if listing.status == Listing.Status.BLOCKED:
        messages.error(request, "Объявление заблокировано модератором и не может быть изменено.")
        return redirect("listings:my")

    form = ListingForm(request.POST or None, request.FILES or None, instance=listing)
    if request.method == "POST" and form.is_valid():
        form.save()
        _save_photos(listing, form.cleaned_data["photos"])
        messages.success(request, "Изменения сохранены")
        return redirect("listings:my")
    return render(request, "listings/listing_form.html", {"form": form, "listing": listing, "is_new": False})


@login_required
@require_POST
def listing_set_status(request, pk: int):
    """Пауза, возобновление или отметка «сдано»."""
    listing = get_object_or_404(Listing, pk=pk, owner=request.user)
    new_status = request.POST.get("status")
    allowed = {Listing.Status.ACTIVE, Listing.Status.PAUSED, Listing.Status.RENTED}
    if listing.status in {Listing.Status.BLOCKED, Listing.Status.PENDING} or new_status not in allowed:
        messages.error(request, "Этот статус сейчас нельзя установить")
        return redirect("listings:my")

    listing.status = new_status
    listing.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Статус объявления: {listing.get_status_display().lower()}")
    return redirect("listings:my")


@login_required
@require_POST
def photo_delete(request, photo_id: int):
    """Удаление фото из своего объявления."""
    photo = get_object_or_404(ListingPhoto, pk=photo_id, listing__owner=request.user)
    listing_pk = photo.listing_id
    photo.image.delete(save=False)
    photo.delete()
    return redirect("listings:edit", pk=listing_pk)


@login_required
def listing_detail(request, pk: int):
    """Карточка объявления.

    Владелец видит своё объявление всегда. Остальные — только активные.
    Точного адреса в объявлении нет: хозяин сам сообщает его в чате.
    """
    listing = get_object_or_404(Listing.objects.select_related("city", "owner__profile"), pk=pk)
    is_owner = listing.owner_id == request.user.pk
    if not is_owner and listing.status != Listing.Status.ACTIVE:
        # Участники мэтча видят объявление и после того, как оно снято
        if not Match.objects.filter(listing=listing, seeker=request.user).exists():
            raise Http404

    return render(request, "listings/listing_detail.html", {"listing": listing, "is_owner": is_owner})
