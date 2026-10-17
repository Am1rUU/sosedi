"""Обработка загружаемых фото.

Зачем:
1. Приватность. Фото с телефона содержат скрытые метаданные (EXIF), в том числе
   GPS-координаты места съёмки. По фото комнаты можно было бы вычислить адрес,
   который мы специально скрываем до мэтча. Поэтому метаданные полностью удаляются.
2. Размер. Фото уменьшается до MAX_PHOTO_SIDE_PX по длинной стороне и сжимается —
   лента грузится быстрее, хранилище не забивается.
3. Безопасность. Файл заново кодируется из пикселей, поэтому вместо «картинки»
   нельзя подсунуть что-то другое.
"""

import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

# Защита от «бомб» — картинок огромного разрешения, которые съедают память
Image.MAX_IMAGE_PIXELS = 50_000_000


def process_photo(uploaded_file) -> ContentFile:
    """Возвращает очищенную и сжатую JPEG-копию загруженного фото.

    Поворот фото учитывается до удаления EXIF (иначе снимки с телефона
    оказались бы повёрнуты боком).
    """
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                # Прозрачность (PNG) заливаем белым, чтобы JPEG не стал чёрным
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            elif img.mode == "L":
                img = img.convert("RGB")

            side = settings.MAX_PHOTO_SIDE_PX
            img.thumbnail((side, side), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            # Сохраняем без exif/icc и прочих метаданных
            img.save(output, format="JPEG", quality=85, optimize=True, progressive=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValidationError("Не удалось прочитать фото. Загрузите снимок в формате JPG или PNG.") from error

    # Случайное имя: исходное имя файла может содержать личные данные
    return ContentFile(output.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
