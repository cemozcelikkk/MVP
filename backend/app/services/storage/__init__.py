"""
Depolama adaptör katmanı.

`get_storage()`, `settings.STORAGE_BACKEND` değerine göre `LocalStorage`
(geliştirme) veya `S3Storage` (AWS S3/Cloudflare R2) döner. Çağıran kod
(`photo_service.py`) hangi adaptörün aktif olduğunu bilmek zorunda
değildir - sadece `BaseStorage` arayüzüne (`upload_file`/`delete_file`)
yazar.
"""
from functools import lru_cache

from app.core.config import settings
from app.services.storage.base import BaseStorage
from app.services.storage.local import LocalStorage
from app.services.storage.s3 import S3Storage

__all__ = ["BaseStorage", "LocalStorage", "S3Storage", "get_storage"]


@lru_cache
def get_storage() -> BaseStorage:
    """Aktif depolama adaptörünü döner (process başına tek instance)."""
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage()
    return LocalStorage()
