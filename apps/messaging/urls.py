from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("<int:match_id>/", views.chat, name="chat"),
    path("<int:match_id>/messages/", views.chat_messages, name="messages"),
    path("<int:match_id>/send/", views.send_message, name="send"),
    path("<int:match_id>/messages/<int:message_id>/delete/", views.delete_message, name="delete"),
    path("<int:match_id>/close/", views.close_match, name="close"),
]
