"""
Review CRUD, spot'un denormalize edilmiş ortalama puan/adet alanlarının
otomatik güncellenmesi, ve çok boyutlu saha değerlendirmesi.

## Araç anlık görüntüsü

`add_review`, yorumu yazan kullanıcının O ANKİ aktif araç profilini
(`vehicle_profile_service.get_active_vehicle_profile`) okuyup sadece
`vehicle_type`/`length_m`'ini review satırına KOPYALAR - bir FK/profil
referansı SAKLANMAZ (bkz. `app.models.review` docstring'i). Kullanıcının
aktif aracı yoksa (veya hiç profili yoksa) snapshot alanları NULL kalır,
yorum yine de oluşturulur - araç bilgisi vermek asla ZORUNLU değildir.

## Check-in doğrulama rozeti

"Yerinde doğrulandı" DİNAMİK hesaplanır (review satırına yazılmaz): bir
review listesi çekilirken, o spot için check-in yapmış kullanıcı id'lerinin
kümesi TEK bir ek sorguyla çekilip (N+1 değil) her review'ın yazarıyla
kesiştirilir.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check_in import CheckIn
from app.models.enums import UserRole
from app.models.review import DIMENSION_KEYS, Review
from app.models.spot import Spot
from app.models.user import User
from app.schemas.review import (
    DimensionRatings,
    DimensionRatingStat,
    ReviewCreate,
    ReviewRead,
    ReviewUpdate,
    ReviewVehicleSnapshot,
    SpotDimensionRatings,
)
from app.services.vehicle_profile_service import get_active_vehicle_profile

_PRIVILEGED_ROLES = (UserRole.MODERATOR, UserRole.ADMIN)


class ReviewNotFoundError(Exception):
    """Yorum yok."""


class ReviewPermissionError(Exception):
    """Giriş yapan kullanıcı ne yorumun sahibi ne de MODERATOR/ADMIN."""


class DuplicateReviewError(Exception):
    """Kullanıcının bu noktada zaten AKTİF bir değerlendirmesi var - yenisini değil mevcut olanı düzenlemeli."""


async def _refresh_spot_rating_summary(db: AsyncSession, spot_id: uuid.UUID) -> None:
    """`spots.average_rating`/`review_count`'u YALNIZCA aktif (superseded olmayan) yorumlardan yeniden hesaplar."""
    avg_rating, count = (
        await db.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.spot_id == spot_id, Review.is_active.is_(True)
            )
        )
    ).one()
    await db.execute(
        sa_update(Spot)
        .where(Spot.id == spot_id)
        .values(
            average_rating=round(float(avg_rating), 2) if avg_rating is not None else None,
            review_count=count,
            # Delta sync bu değişikliği "spot değişti" olarak yakalasın.
            updated_at=func.now(),
        )
    )


def _dimension_ratings_from_review(review: Review) -> DimensionRatings:
    return DimensionRatings(**{key: getattr(review, f"{key}_rating") for key in DIMENSION_KEYS})


def _apply_dimension_ratings_create(review: Review, ratings: DimensionRatings | None) -> None:
    if ratings is None:
        return
    for key in DIMENSION_KEYS:
        setattr(review, f"{key}_rating", getattr(ratings, key))


def _apply_dimension_ratings_update(review: Review, ratings: DimensionRatings | None) -> None:
    """
    `ReviewUpdate.dimension_ratings` için PATCH semantiği: sadece istek
    gövdesinde GERÇEKTEN yer alan alt-alanlar uygulanır (`exclude_unset`) -
    `null` gönderilen bir alt-alan o ölçütü "Değerlendirmedim"e ÇEKER,
    hiç bahsedilmeyen alt-alanlar dokunulmadan kalır. Bkz. `ReviewUpdate` docstring'i.
    """
    if ratings is None:
        return
    for key, value in ratings.model_dump(exclude_unset=True).items():
        setattr(review, f"{key}_rating", value)


def _review_to_read(review: Review, *, is_verified_checkin: bool) -> ReviewRead:
    vehicle_snapshot = (
        ReviewVehicleSnapshot(
            vehicle_type=review.vehicle_type_snapshot, length_m=float(review.vehicle_length_m_snapshot)
        )
        if review.vehicle_type_snapshot is not None and review.vehicle_length_m_snapshot is not None
        else None
    )
    return ReviewRead(
        id=review.id,
        spot_id=review.spot_id,
        user_id=review.user_id,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at,
        dimension_ratings=_dimension_ratings_from_review(review),
        vehicle_snapshot=vehicle_snapshot,
        is_verified_checkin=is_verified_checkin,
    )


async def _check_in_user_ids_for_spot(db: AsyncSession, *, spot_id: uuid.UUID) -> set[uuid.UUID]:
    """Bu spot'ta EN AZ bir check-in yapmış kullanıcı id'lerinin kümesi - tek sorgu."""
    rows = await db.execute(select(CheckIn.user_id.distinct()).where(CheckIn.spot_id == spot_id))
    return set(rows.scalars().all())


def _check_owner_or_privileged(*, owner_id: uuid.UUID, current_user: User, review_id: uuid.UUID) -> None:
    """`update_review` için yetki kontrolü - `spot_service._check_owner_or_privileged` ile aynı kural."""
    is_owner = owner_id == current_user.id
    is_privileged = current_user.role in _PRIVILEGED_ROLES
    if not (is_owner or is_privileged):
        raise ReviewPermissionError(review_id)


async def add_review(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    current_user: User,
    data: ReviewCreate,
) -> ReviewRead | None:
    """Spot bulunamazsa (veya soft-delete edilmişse) `None` döner -> endpoint 404 çevirir."""
    spot_exists = await db.scalar(
        select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None))
    )
    if spot_exists is None:
        return None

    # Kullanıcı+nokta başına tek aktif değerlendirme: ön kontrol (kullanıcıya net hata) +
    # aşağıdaki flush'ta `uq_reviews_one_active_per_user_spot` (eşzamanlı isteklerde DB son söz).
    already = await db.scalar(
        select(Review.id).where(
            Review.spot_id == spot_id, Review.user_id == current_user.id, Review.is_active.is_(True)
        )
    )
    if already is not None:
        raise DuplicateReviewError(spot_id)

    # Aktif araç profili varsa SADECE tür/uzunluğunun bir anlık görüntüsünü al
    # (bkz. modül docstring'i) - kullanıcının aracı yoksa sessizce None kalır,
    # yorum yapmak için araç profili ASLA zorunlu değildir.
    active_vehicle = await get_active_vehicle_profile(db, user_id=current_user.id)

    review = Review(
        spot_id=spot_id,
        user_id=current_user.id,
        rating=data.rating,
        comment=data.comment,
        vehicle_type_snapshot=active_vehicle.vehicle_type if active_vehicle else None,
        vehicle_length_m_snapshot=active_vehicle.length_m if active_vehicle else None,
    )
    _apply_dimension_ratings_create(review, data.dimension_ratings)
    db.add(review)
    # commit değil flush: id/created_at DB'den alınabilsin, ama transaction
    # açık kalsın - aşağıdaki ReviewRead/aggregate adımlarından biri
    # patlarsa hiçbir şey kalıcı olmaz (bkz. create_spot'taki aynı desen).
    try:
        await db.flush()
    except IntegrityError:
        # Yarışan eşzamanlı istek aynı anda aktif yorum oluşturdu (kısmi unique index).
        await db.rollback()
        raise DuplicateReviewError(spot_id) from None
    await db.refresh(review, attribute_names=["created_at"])

    await _refresh_spot_rating_summary(db, spot_id)

    # Yeni review'un yazarı henüz check-in yapmış olamaz (aynı transaction
    # içinde ikisi birden gelmez) ama tutarlılık için gerçek durumu sorgula.
    checked_in_users = await _check_in_user_ids_for_spot(db, spot_id=spot_id)
    review_read = _review_to_read(review, is_verified_checkin=current_user.id in checked_in_users)

    await db.commit()
    return review_read


async def update_review(
    db: AsyncSession, *, review_id: uuid.UUID, current_user: User, data: ReviewUpdate
) -> ReviewRead:
    """
    Raises:
        ReviewNotFoundError: yorum yok.
        ReviewPermissionError: kullanıcı ne yorumun sahibi ne de MODERATOR/ADMIN.
    """
    review = await db.get(Review, review_id)
    # Superseded (geçmiş) yorumlar düzenlenemez - kullanıcının aktif yorumu vardır.
    if review is None or not review.is_active:
        raise ReviewNotFoundError(review_id)

    _check_owner_or_privileged(owner_id=review.user_id, current_user=current_user, review_id=review_id)

    if data.rating is not None:
        review.rating = data.rating
    if data.comment is not None:
        review.comment = data.comment
    _apply_dimension_ratings_update(review, data.dimension_ratings)

    await db.flush()
    await db.refresh(review, attribute_names=["updated_at"])

    # Genel puan değişmiş olabilir - spot'un denormalize ortalamasını tazele.
    await _refresh_spot_rating_summary(db, review.spot_id)

    checked_in_users = await _check_in_user_ids_for_spot(db, spot_id=review.spot_id)
    review_read = _review_to_read(review, is_verified_checkin=review.user_id in checked_in_users)

    await db.commit()
    return review_read


async def get_reviews_for_spot(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ReviewRead] | None:
    """Spot bulunamazsa `None` döner; varsa (boş liste dahil) yorum listesini döner."""
    spot_exists = await db.scalar(select(Spot.id).where(Spot.id == spot_id))
    if spot_exists is None:
        return None

    stmt = (
        select(Review)
        .where(Review.spot_id == spot_id, Review.is_active.is_(True))
        .order_by(Review.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    reviews = list((await db.execute(stmt)).scalars().all())

    # N+1 DEĞİL: check-in yapmış kullanıcı kümesi TEK sorguyla çekilip
    # bellekte kesiştiriliyor (bkz. modül docstring'i).
    checked_in_users = await _check_in_user_ids_for_spot(db, spot_id=spot_id)

    return [
        _review_to_read(review, is_verified_checkin=review.user_id in checked_in_users)
        for review in reviews
    ]


async def get_spot_dimension_ratings(db: AsyncSession, *, spot_id: uuid.UUID) -> SpotDimensionRatings:
    """
    Spot'un TÜM yorumlarındaki 7 ölçütün ortalama+adedi - TEK sorguda (7
    `avg`/7 `count` aynı SELECT'te). SADECE nokta DETAY endpoint'i çağırır
    (bkz. `spots.py::read_spot`) - bbox listesinde KULLANILMAZ, bu yüzden
    haritanın toplu sorgu performansını etkilemez (görev tanımındaki kural).
    """
    columns = [
        func.avg(getattr(Review, f"{key}_rating")) for key in DIMENSION_KEYS
    ] + [
        func.count(getattr(Review, f"{key}_rating")) for key in DIMENSION_KEYS
    ]
    row = (
        await db.execute(select(*columns).where(Review.spot_id == spot_id, Review.is_active.is_(True)))
    ).one()

    n = len(DIMENSION_KEYS)
    averages = row[:n]
    counts = row[n:]

    stats = {
        key: DimensionRatingStat(
            average=round(float(avg), 2) if avg is not None else None,
            count=count,
        )
        for key, avg, count in zip(DIMENSION_KEYS, averages, counts, strict=True)
    }
    return SpotDimensionRatings(**stats)


async def get_my_review(db: AsyncSession, *, spot_id: uuid.UUID, current_user: User) -> ReviewRead | None:
    """Kullanıcının bu noktadaki AKTİF değerlendirmesi (yoksa None) - istemci "yaz" yerine "düzenle" göstersin diye."""
    review = await db.scalar(
        select(Review).where(
            Review.spot_id == spot_id, Review.user_id == current_user.id, Review.is_active.is_(True)
        )
    )
    if review is None:
        return None
    checked_in_users = await _check_in_user_ids_for_spot(db, spot_id=spot_id)
    return _review_to_read(review, is_verified_checkin=current_user.id in checked_in_users)
