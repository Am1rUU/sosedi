from django.urls import path

from . import views

app_name = "matching"

urlpatterns = [
    # Ищущий смотрит комнаты
    path("", views.feed, name="feed"),
    path("swipe/<int:listing_id>/", views.seeker_swipe, name="seeker_swipe"),
    # Владелец смотрит анкеты по своему объявлению
    path("listing/<int:listing_id>/", views.owner_feed, name="owner_feed"),
    path("listing/<int:listing_id>/swipe/<int:seeker_id>/", views.owner_swipe, name="owner_swipe"),
    path("listing/<int:listing_id>/likes/", views.incoming_likes, name="incoming_likes"),
    # Мэтчи обеих ролей
    path("matches/", views.matches, name="matches"),
    path("found/", views.found, name="found"),
    path("found/later/", views.found_snooze, name="found_snooze"),
    path("listing/<int:listing_id>/still-available/", views.listing_confirm, name="listing_confirm"),
    path("match/<int:match_id>/", views.match_page, name="match"),
]
