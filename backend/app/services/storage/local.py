"""Geliştirme ortamı için yerel disk depolama adaptörü."""
import asyncio
from pathlib import Path

from app.core.config import settings
from app.services.storage.base import BaseStorage


class LocalStorage(BaseStorage):
    """
    Dosyaları `settings.UPLOAD_DIR` altına yazar; `app.main`'de bu dizin
    `/uploads` adıyla `StaticFiles` olarak mount edilir, dönen URL de bu
    prefix'i kullanır.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or settings.UPLOAD_DIR

    async def upload_file(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        destination = self._base_dir / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Disk I/O senkron bir çağrı; event loop'u bloklamamak için thread'e devrediyoruz.
        await asyncio.to_thread(destination.write_bytes, file_bytes)
        return f"/uploads/{filename}"

    async def delete_file(self, filename: str) -> bool:
        destination = self._base_dir / filename
        if not destination.exists():
            return False
        await asyncio.to_thread(destination.unlink)
        return True
