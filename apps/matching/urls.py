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
]
