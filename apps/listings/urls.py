from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    path("", views.my_listings, name="my"),
    path("new/", views.listing_create, name="create"),
    path("<int:pk>/", views.listing_detail, name="detail"),
    path("<int:pk>/edit/", views.listing_edit, name="edit"),
    path("<int:pk>/status/", views.listing_set_status, name="set_status"),
    path("photos/<int:photo_id>/delete/", views.photo_delete, name="photo_delete"),
]
