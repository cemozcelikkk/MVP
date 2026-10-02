"""
AWS S3 veya Cloudflare R2 (S3 uyumlu API) için async depolama adaptörü.

`aioboto3` kullanır; her çağrıda kısa ömürlü bir client açılıp kapatılır
(bağlantı havuzlama aioboto3/aiohttp tarafında zaten yönetiliyor - uzun
ömürlü bir client'ı elle saklamak yerine bu, basitlik/doğruluk için tercih
edildi).
"""
import aioboto3
from botocore.config import Config as BotoConfig

from app.core.config import settings
from app.services.storage.base import BaseStorage


class S3Storage(BaseStorage):
    def __init__(self) -> None:
        if not settings.S3_BUCKET_NAME:
            raise RuntimeError(
                "STORAGE_BACKEND='s3' seçildiyse S3_BUCKET_NAME .env'de zorunludur."
            )

        self._bucket = settings.S3_BUCKET_NAME
        self._session = aioboto3.Session()

        boto_config = None
        if settings.S3_ENDPOINT_URL:
            # Cloudflare R2 gibi AWS-dışı S3-uyumlu uç noktalar genelde
            # "path-style" adresleme gerektirir; "virtual-hosted style"
            # (bucket.endpoint/...) çoğunlukla sadece gerçek AWS S3'te
            # sorunsuz çözümlenir.
            boto_config = BotoConfig(s3={"addressing_style": "path"})

        self._client_kwargs = {
            "endpoint_url": settings.S3_ENDPOINT_URL,
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "region_name": settings.S3_REGION_NAME,
            "config": boto_config,
        }

    def _public_url(self, filename: str) -> str:
        if settings.S3_PUBLIC_CUSTOM_DOMAIN:
            return f"https://{settings.S3_PUBLIC_CUSTOM_DOMAIN.rstrip('/')}/{filename}"
        if settings.S3_ENDPOINT_URL:
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self._bucket}/{filename}"
        return f"https://{self._bucket}.s3.{settings.S3_REGION_NAME}.amazonaws.com/{filename}"

    async def upload_file(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=filename,
                Body=file_bytes,
                ContentType=content_type,
            )
        return self._public_url(filename)

    async def delete_file(self, filename: str) -> bool:
        # S3 API semantiği: DeleteObject, anahtar mevcut olmasa bile
        # başarıyla (204) döner; bu yüzden burada her zaman True dönüyoruz.
        async with self._session.client("s3", **self._client_kwargs) as s3:
            await s3.delete_object(Bucket=self._bucket, Key=filename)
        return True
