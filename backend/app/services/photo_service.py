"""
Spot fotoğrafı yükleme/işleme iş mantığı.

Akış: ham baytları boyut sınırına dikkat ederek (streaming) belleğe oku ->
Pillow ile EXIF oryantasyonunu düzelt -> hem "ana" (max 1920x1080, WebP
q=82) hem "thumbnail" (300x300 kare, WebP q=75) versiyonlarını üret ->
her ikisini de aktif depolama adaptörüne (`services/storage`) yükle ->
`spot_photos` satırını iki URL ile birlikte kaydet.

Dosya hiçbir zaman diske/depolamaya YARIM yazılmaz: Pillow işlemesi tümüyle
bellekte biter, depolamaya sadece geçerli/tam üretilmiş baytlar gönderilir
(önceki sürümdeki "yarım yazılmış dosyayı silme" ihtiyacı bu tasarımda
zaten ortadan kalkıyor).
"""
import asyncio
import uuid
from io import BytesIO

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.spot import Spot
from app.models.spot_photo import SpotPhoto
from app.schemas.spot_photo import SpotPhotoRead
from app.services.storage import get_storage

# Sadece burada listelenen Content-Type'lar kabul edilir; nihai doğrulama
# yine de Pillow'un dosyayı gerçekten açabilmesidir (bkz. aşağı).
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})

_CHUNK_SIZE = 1024 * 1024  # 1MB

_MAIN_MAX_SIZE = (1920, 1080)
_MAIN_QUALITY = 82
_THUMB_SIZE = (300, 300)
_THUMB_QUALITY = 75


class UnsupportedImageTypeError(Exception):
    """İzin verilmeyen bir Content-Type ya da Pillow'un açamadığı bozuk/sahte bir dosya."""


class ImageTooLargeError(Exception):
    """Dosya, MAX_UPLOAD_SIZE_MB sınırını aştığında fırlatılır."""


async def _read_within_limit(file: UploadFile, max_bytes: int) -> bytes:
    """
    `Content-Length` header'ına güvenmeden, dosyayı parça parça okuyup
    sınırı aşarsa erken durur. Böylece biri header'ı küçük gösterip aslında
    çok büyük bir dosya göndererek belleği/diski doldurmaya çalışamaz.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError(total)
        chunks.append(chunk)
    return b"".join(chunks)


def _normalize_mode(img: Image.Image) -> Image.Image:
    """WebP kaydı için güvenli bir moda çevirir (palette/gri tonlama vb. dahil)."""
    if img.mode in ("P", "LA"):
        return img.convert("RGBA")
    if img.mode not in ("RGB", "RGBA"):
        return img.convert("RGB")
    return img


def _process_image(raw_bytes: bytes) -> tuple[bytes, bytes]:
    """
    CPU-bound senkron işlem; çağıran taraf bunu `asyncio.to_thread` ile
    event loop'u bloklamadan çalıştırır.

    Returns:
        (ana_gorsel_webp_bytes, thumbnail_webp_bytes)
    """
    with Image.open(BytesIO(raw_bytes)) as img:
        # Telefonla çekilen fotoğraflarda EXIF'teki dönüş bilgisini
        # (Orientation tag) piksellere gerçekten uygular; aksi halde
        # yatay çekilmiş bir foto dikey/yan görünebilir.
        img = ImageOps.exif_transpose(img)
        img = _normalize_mode(img)

        # --- Ana görsel: en-boy oranını koruyarak max 1920x1080 ---
        main_img = img.copy()
        main_img.thumbnail(_MAIN_MAX_SIZE, Image.Resampling.LANCZOS)
        main_buffer = BytesIO()
        main_img.save(main_buffer, format="WEBP", quality=_MAIN_QUALITY)

        # --- Thumbnail: 300x300 kare, ortadan crop edilerek (cover) ---
        thumb_img = ImageOps.fit(img, _THUMB_SIZE, Image.Resampling.LANCZOS)
        thumb_buffer = BytesIO()
        thumb_img.save(thumb_buffer, format="WEBP", quality=_THUMB_QUALITY)

    return main_buffer.getvalue(), thumb_buffer.getvalue()


async def save_spot_photo(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    file: UploadFile,
    caption: str | None = None,
    photo_kind: str = "general",
) -> SpotPhotoRead | None:
    """
    Spot bulunamazsa (veya soft-delete edilmişse) `None` döner -> endpoint
    404 çevirir. Desteklenmeyen tip/boyut/bozuk dosya durumunda ilgili
    exception fırlar.
    """
    spot_exists = await db.scalar(
        select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None))
    )
    if spot_exists is None:
        return None

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedImageTypeError(content_type)

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        raw_bytes = await _read_within_limit(file, max_bytes)
    finally:
        await file.close()

    try:
        # Pillow'un dosyayı fiilen açabilmesi, Content-Type header'ından
        # daha güvenilir bir doğrulamadır (biri .jpg uzantılı sahte bir
        # dosya + yanlış Content-Type gönderse bile burada yakalanır).
        main_bytes, thumb_bytes = await asyncio.to_thread(_process_image, raw_bytes)
    except UnidentifiedImageError as exc:
        raise UnsupportedImageTypeError(content_type) from exc

    photo_id = uuid.uuid4()
    main_key = f"photos/{photo_id}.webp"
    thumb_key = f"photos/{photo_id}_thumb.webp"

    storage = get_storage()
    main_url = await storage.upload_file(main_bytes, main_key, "image/webp")
    thumb_url = await storage.upload_file(thumb_bytes, thumb_key, "image/webp")

    photo = SpotPhoto(
        spot_id=spot_id,
        uploaded_by=uploaded_by,
        storage_url=main_url,
        thumbnail_url=thumb_url,
        caption=caption,
        photo_kind=photo_kind,
        is_cover=False,
    )
    db.add(photo)
    # flush + yanıtı kur + commit sırası: create_spot'taki atomiklik deseniyle
    # aynı - yanıt kurulumu patlarsa DB kaydı hiç commit edilmez. (Depolamaya
    # zaten yüklenmiş dosyalar bu durumda öksüz kalabilir; ters yönde -yani
    # DB kaydı olup dosyanın depoda olmaması- çok daha kötü bir tutarsızlık
    # olurdu ve bu sırayla imkansızdır.)
    await db.flush()
    await db.refresh(photo, attribute_names=["created_at"])
    photo_read = SpotPhotoRead.model_validate(photo)

    await db.commit()
    return photo_read


async def save_spot_photos_batch(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    files: list[UploadFile],
    cover_index: int = 0,
    approach_indices: list[int] | None = None,
) -> list[SpotPhotoRead] | None:
    """
    Birden fazla fotoğrafı tek transaction içinde kaydeder.
    `cover_index` kapak fotoğrafının listedeki sırasını belirler.
    Spot bulunamazsa `None` döner.
    """
    spot_exists = await db.scalar(
        select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None))
    )
    if spot_exists is None:
        return None

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    results: list[SpotPhotoRead] = []

    for idx, file in enumerate(files):
        content_type = (file.content_type or "").lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedImageTypeError(content_type)

        try:
            raw_bytes = await _read_within_limit(file, max_bytes)
        finally:
            await file.close()

        try:
            main_bytes, thumb_bytes = await asyncio.to_thread(_process_image, raw_bytes)
        except UnidentifiedImageError as exc:
            raise UnsupportedImageTypeError(content_type) from exc

        photo_id = uuid.uuid4()
        main_key = f"photos/{photo_id}.webp"
        thumb_key = f"photos/{photo_id}_thumb.webp"

        storage = get_storage()
        main_url = await storage.upload_file(main_bytes, main_key, "image/webp")
        thumb_url = await storage.upload_file(thumb_bytes, thumb_key, "image/webp")

        photo = SpotPhoto(
            spot_id=spot_id,
            uploaded_by=uploaded_by,
            storage_url=main_url,
            thumbnail_url=thumb_url,
            is_cover=(idx == cover_index),
            photo_kind="entrance" if idx in (approach_indices or []) else "general",
        )
        db.add(photo)
        await db.flush()
        await db.refresh(photo, attribute_names=["created_at"])
        results.append(SpotPhotoRead.model_validate(photo))

    await db.commit()
    return results
