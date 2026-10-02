from typing import Literal

"""
`/api/v1/spots/{spot_id}/reviews`, `/check-in`, `/photos` ve `/favorite`
endpoint'leri.

Ayrı bir dosyada tutulur ki `spots.py` (çekirdek CRUD/bbox/sync) büyümesin;
hepsi aynı `/spots` prefix'ini paylaşır.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.check_in import CheckInCreate, CheckInRead
from app.schemas.review import ReviewCreate, ReviewRead, ReviewUpdate
from app.schemas.saved_list import FavoriteToggleResponse
from app.schemas.spot_photo import SpotPhotoRead
from app.services.checkin_service import CheckInTooFarError, DuplicateCheckInError, add_check_in
from app.services.photo_service import (
    ImageTooLargeError,
    UnsupportedImageTypeError,
    save_spot_photo,
    save_spot_photos_batch,
)
from app.services.review_service import (
    DuplicateReviewError,
    ReviewNotFoundError,
    ReviewPermissionError,
    add_review,
    get_my_review,
    get_reviews_for_spot,
    update_review,
)
from app.services.saved_list_service import toggle_favorite

router = APIRouter(prefix="/spots", tags=["spot-interactions"])


@router.post("/{spot_id}/reviews", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_review(
    spot_id: uuid.UUID,
    payload: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewRead:
    """
    Kullanıcı+nokta başına YALNIZCA BİR aktif değerlendirme (ikincisi 409). 1-5 arası genel puan + opsiyonel yorum + opsiyonel çok boyutlu
    değerlendirme (güvenlik/sessizlik/yol erişimi/zemin/temizlik/manzara/
    çekim - her biri bağımsız olarak boş bırakılabilir) ekler. Spot'un
    `average_rating`/`review_count` alanları aynı transaction içinde
    otomatik güncellenir. Kullanıcının aktif araç profili varsa tür/uzunluk
    anlık görüntüsü yoruma kaydedilir (bkz. `review_service.add_review`
    docstring'i - araç profili gerekmez, gizlilik kuralları için oraya bakın).
    """
    try:
        review = await add_review(db, spot_id=spot_id, current_user=current_user, data=payload)
    except DuplicateReviewError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu nokta için zaten bir değerlendirmeniz var; yeni yazmak yerine mevcut değerlendirmenizi düzenleyin.",
        )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return review


@router.get("/{spot_id}/reviews/me", response_model=ReviewRead | None)
async def read_my_review(
    spot_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewRead | None:
    """Kullanıcının bu noktadaki aktif değerlendirmesi; yoksa `null`."""
    return await get_my_review(db, spot_id=spot_id, current_user=current_user)


@router.get("/{spot_id}/reviews", response_model=list[ReviewRead])
async def list_reviews(
    spot_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
) -> list[ReviewRead]:
    reviews = await get_reviews_for_spot(db, spot_id=spot_id, limit=limit, offset=offset)
    if reviews is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return reviews


@router.patch("/{spot_id}/reviews/{review_id}", response_model=ReviewRead)
async def update_review_endpoint(
    spot_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: ReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewRead:
    """
    Bir yorumu düzenler (kimlik doğrulama gerektirir). Sadece yorumun
    sahibi VEYA MODERATOR/ADMIN düzenleyebilir - `spot_service`deki
    sahiplik kuralıyla birebir aynı (bkz. `review_service.update_review`).
    `dimension_ratings` içindeki bir ölçütü açıkça `null` göndermek onu
    "Değerlendirmedim"e geri döndürür; hiç göndermemek dokunmaz.
    """
    del spot_id  # URL tutarlılığı için tutuluyor - review_id zaten benzersiz.
    try:
        return await update_review(db, review_id=review_id, current_user=current_user, data=payload)
    except ReviewNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Yorum bulunamadı.")
    except ReviewPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu yorumu düzenleme yetkiniz yok."
        )


@router.post(
    "/{spot_id}/check-in",
    response_model=CheckInRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_check_in(
    spot_id: uuid.UUID,
    payload: CheckInCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckInRead:
    """
    "Buradayım" onayı verir. Gövdedeki `latitude`/`longitude`, kullanıcının
    check-in anındaki gerçek GPS konumudur; sunucu bunu spot'un koordinatıyla
    PostGIS `ST_DWithin` üzerinden karşılaştırıp 500 metreden uzaksa
    reddeder (oturduğu yerden trust_score kasmayı engeller). Aynı kullanıcı
    aynı spota aynı gün içinde ikinci kez check-in yapamaz.

    Başarılıysa kullanıcının `trust_score`'unu +1 artırır (bkz.
    `checkin_service.add_check_in`).
    """
    try:
        check_in_obj = await add_check_in(db, spot_id=spot_id, user_id=current_user.id, data=payload)
    except CheckInTooFarError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Check-in yapabilmek için noktaya en fazla 500 metre mesafede olmalısınız.",
        )
    except DuplicateCheckInError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu noktaya bugün zaten check-in yaptınız.",
        )
    if check_in_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return check_in_obj


@router.post(
    "/{spot_id}/photos",
    response_model=SpotPhotoRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_spot_photo(
    spot_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="JPEG, PNG veya WebP - azami 5MB")],
    caption: Annotated[str | None, Form(max_length=300)] = None,
    photo_kind: Annotated[Literal["general", "entrance"], Form()] = "general",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpotPhotoRead:
    """
    Spot'a fotoğraf ekler (multipart/form-data). Dosya `backend/uploads/`
    altına UUID adıyla kaydedilir ve `/uploads/{dosya}` üzerinden statik
    olarak servis edilir; `storage_url` bu göreli yolu taşır.
    """
    try:
        photo = await save_spot_photo(
            db, spot_id=spot_id, uploaded_by=current_user.id, file=file, caption=caption, photo_kind=photo_kind
        )
    except UnsupportedImageTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Desteklenmeyen dosya tipi: '{exc}'. İzin verilenler: JPEG, PNG, WebP.",
        )
    except ImageTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Dosya çok büyük. Azami boyut: {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )

    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return photo


@router.post(
    "/{spot_id}/photos/batch",
    response_model=list[SpotPhotoRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_spot_photos_batch(
    spot_id: uuid.UUID,
    files: Annotated[list[UploadFile], File(description="Birden fazla JPEG, PNG veya WebP dosyası - her biri azami 5MB")],
    cover_index: Annotated[int, Form(description="Kapak fotoğrafının listedeki sırası (0-indexed)")] = 0,
    approach_indices: Annotated[list[int], Form()] = [],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SpotPhotoRead]:
    """
    Spot'a birden fazla fotoğraf ekler (multipart/form-data). İlk fotoğraf
    (veya `cover_index` ile belirtilen) kapak fotoğrafı olarak işaretlenir.
    """
    if any(index < 0 or index >= len(files) for index in approach_indices):
        raise HTTPException(422, "Giriş fotoğrafı sırası geçersiz.")
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="En az bir dosya gönderilmeli.",
        )
    try:
        photos = await save_spot_photos_batch(
            db,
            spot_id=spot_id,
            uploaded_by=current_user.id,
            files=files,
            cover_index=min(cover_index, len(files) - 1),
            approach_indices=approach_indices,
        )
    except UnsupportedImageTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Desteklenmeyen dosya tipi: '{exc}'. İzin verilenler: JPEG, PNG, WebP.",
        )
    except ImageTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Dosya çok büyük. Azami boyut: {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )
    if photos is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return photos

@router.post("/{spot_id}/favorite", response_model=FavoriteToggleResponse)
async def toggle_favorite_endpoint(
    spot_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteToggleResponse:
    """
    Hızlı favori toggle'ı: spot favorilerde yoksa ekler, varsa çıkarır.
    Favoriler, kullanıcının `is_default_favorites=True` olan tek listesidir
    (ilk çağrıda örtük olarak oluşturulur) - bkz.
    `saved_list_service.toggle_favorite`.
    """
    is_favorited = await toggle_favorite(db, user_id=current_user.id, spot_id=spot_id)
    if is_favorited is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return FavoriteToggleResponse(is_favorited=is_favorited)
