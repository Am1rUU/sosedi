"""Сообщения внутри мэтча.

Чат привязан к мэтчу, поэтому написать человеку без взаимного лайка нельзя —
это главная защита от спама. Контакты пользователи обменивают сами, когда готовы.
"""

from django.conf import settings
from django.db import models


class Message(models.Model):
    """Одно сообщение в чате мэтча."""

    match = models.ForeignKey("matching.Match", on_delete=models.CASCADE, related_name="messages", verbose_name="мэтч")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages", verbose_name="отправитель"
    )
    text = models.TextField("текст", max_length=2000)
    created_at = models.DateTimeField("отправлено", auto_now_add=True, db_index=True)
    read_at = models.DateTimeField("прочитано", null=True, blank=True)

    class Meta:
        verbose_name = "сообщение"
        verbose_name_plural = "сообщения"
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.sender}: {self.text[:40]}"
