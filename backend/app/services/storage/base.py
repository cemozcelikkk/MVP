"""
Depolama adaptörleri için ortak soyut arayüz.

Amaç: `photo_service.py` gibi çağıran kodun "dosya nereye/nasıl yazılıyor"
bilgisinden tamamen habersiz olması - `LocalStorage` (geliştirme ortamı)
ile `S3Storage` (üretim, AWS S3/Cloudflare R2) birbirinin yerine
`get_storage()` factory'si üzerinden geçirilebilir.
"""
from abc import ABC, abstractmethod


class BaseStorage(ABC):
    @abstractmethod
    async def upload_file(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        """
        Dosyayı yükler ve herkese açık, doğrudan tarayıcıdan erişilebilir
        URL'sini döner.

        `filename`, depolama içindeki göreli anahtar/yoldur (ör.
        "photos/{uuid}.webp"); `delete_file`'a da aynı değer verilir.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete_file(self, filename: str) -> bool:
        """
        Dosyayı siler. Dosya zaten yoksa da (idempotent silme davranışı
        için) `True`/`False` dönebilir - her adaptör kendi semantiğini
        docstring'inde belirtir.
        """
        raise NotImplementedError
