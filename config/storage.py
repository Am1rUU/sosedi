"""Настройки хранения загруженных фото в S3-совместимом хранилище (Timeweb Cloud S3).

Зачем: на App Platform файлы на диске контейнера стираются при каждом обновлении сайта.
В S3 фото хранятся отдельно от приложения и не пропадают.

Бакет приватный: прямые ссылки на фото не открываются. Сайт выдаёт временные
подписанные ссылки (живут несколько часов) — фото людей и комнат не утекут
по прямому адресу, даже если кто-то перешлёт ссылку на картинку.
"""

from botocore.config import Config

# Адрес и регион хранилища Timeweb Cloud (см. документацию Timeweb, раздел S3)
TIMEWEB_S3_ENDPOINT = "https://s3.twcstorage.ru"
TIMEWEB_S3_REGION = "ru-1"

# Сколько живёт подписанная ссылка на фото (в секундах)
SIGNED_URL_LIFETIME = 6 * 60 * 60


def s3_storage(
    bucket: str,
    access_key: str,
    secret_key: str,
    endpoint_url: str | None = TIMEWEB_S3_ENDPOINT,
    region: str = TIMEWEB_S3_REGION,
    addressing_style: str = "path",
) -> dict:
    """Описание хранилища для настройки STORAGES["default"]."""
    client_config = Config(
        signature_version="s3v4",
        s3={"addressing_style": addressing_style},
        # Новые версии boto3 по умолчанию добавляют контрольные суммы, которые
        # не все S3-совместимые хранилища понимают. Включаем их только когда обязательно.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": bucket,
            "access_key": access_key,
            "secret_key": secret_key,
            "endpoint_url": endpoint_url,
            "region_name": region,
            "client_config": client_config,
            "location": "media",  # все фото — в папке media/ внутри бакета
            "default_acl": None,  # права берутся из настроек бакета (приватный)
            "querystring_auth": True,  # подписанные временные ссылки
            "querystring_expire": SIGNED_URL_LIFETIME,
            "file_overwrite": False,  # одинаковые имена не затирают друг друга
        },
    }
