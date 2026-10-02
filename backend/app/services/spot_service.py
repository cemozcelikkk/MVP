"""
Spot'larla ilgili veritabanı erişim / iş mantığı katmanı.

Router'lar doğrudan SQLAlchemy sorgusu yazmaz; tüm mekansal ve
ilişkisel sorgular burada toplanır ki `/spots/bbox`, `/spots/sync` gibi
endpoint'ler aynı eager-loading ve filtre mantığını paylaşsın.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.dynamic_status import ACTIVE_REPORT_CONDITION, DynamicStatus  # noqa: F401
from app.models.enums import ClearanceRequired, SpotCategory, UserRole
from app.models.spot import Spot
from app.models.spot_amenities import SpotAmenities
from app.models.spot_passability import SpotPassability
from app.models.spot_photo import SpotPhoto
from app.models.user import User
from app.schemas.dynamic_status import DynamicStatusCreate
from app.schemas.geojson import Feature
from app.schemas.spot import SpotCreate, SpotProperties, SpotUpdate, spot_to_feature
from app.schemas.spot_amenities import SpotAmenitiesBase
from app.utils.geo import lonlat_to_wkb

_PRIVILEGED_ROLES = (UserRole.MODERATOR, UserRole.ADMIN)


class SpotNotFoundError(Exception):
    """Spot yok ya da zaten soft-delete edilmiş."""


class SpotPermissionError(Exception):
    """Giriş yapan kullanıcı ne spot'un sahibi ne de MODERATOR/ADMIN."""


# Aktif canlı durum koşulu (`dynamic_status.ACTIVE_REPORT_CONDITION`): moderasyon durumu
# pending/confirmed VE süresi dolmamış. Süresi dolan / geri çekilen / reddedilen satırlar
# latest_status ve canlı özetlerde GÖSTERİLMEZ, ama veritabanından SİLİNMEZ (tarihsel kayıt) -
# bu sadece bir sorgu-katmanı filtresidir; cron yok, aktiflik sorgu anında belirlenir.
# `valid_until IS NULL` (eski "süresiz" kayıtlar) `reported_at + 24 saat` sayılır.
_ACTIVE_STATUS_CONDITION = ACTIVE_REPORT_CONDITION

_SPOT_RELATIONSHIP_OPTIONS = (
    # N+1 sorgusunu önlemek için: GeoJSON Feature.properties bu ilişkilere
    # ihtiyaç duyuyor (spot_to_feature / SpotRead dönüşümü).
    selectinload(Spot.passability),
    selectinload(Spot.amenities),
    # `.and_()`, selectinload'ın ikincil sorgusuna EK bir WHERE koşulu
    # ekler (relationship'in kendi order_by'ını etkilemez); böylece
    # `spot.dynamic_statuses[0]` her zaman "en güncel AKTİF durum" olur.
    selectinload(Spot.dynamic_statuses.and_(_ACTIVE_STATUS_CONDITION)),
    selectinload(Spot.photos.and_(SpotPhoto.is_hidden.is_(False))),
)


async def get_spots_in_bbox(
    db: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    categories: list[SpotCategory] | None = None,
    only_verified: bool = False,
    has_fresh_water: bool | None = None,
    has_black_water: bool | None = None,
    has_electricity: bool | None = None,
    has_toilet: bool | None = None,
    has_trash_bins: bool | None = None,
    is_free: bool | None = None,
    camping_behavior_allowed: bool | None = None,
    overnight_allowed: bool | None = None,
    max_vehicle_length: float | None = None,
    requires_4x4: bool | None = None,
    caravan_type: str | None = None,
    limit: int = settings.SPOTS_BBOX_DEFAULT_LIMIT,
) -> list[Spot]:
    """
    Ekranda görünen dörtgen (bounding box) içindeki spot'ları, opsiyonel
    altyapı/geçiş filtreleriyle birlikte döndürür.

    `ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)` istemcinin
    harita viewport'una karşılık gelen bir dikdörtgen polygon oluşturur;
    `ST_Intersects` bu polygon ile kesişen noktaları `spots.coordinates`
    üzerindeki GiST mekansal index'i kullanarak bulur - bu HER ZAMAN ilk
    ve ana filtredir. `spot_amenities`/`spot_passability`'a JOIN, sadece
    ilgili filtre parametreleri fiilen verildiğinde eklenir; filtresiz bir
    bbox isteği ekstra JOIN taşımadan aynı hızda kalır. JOIN'ler PK=FK
    (spot_id) üzerinden olduğu için (her ikisi de spots ile 1-1) satır
    çoğaltmaz ve GiST index kullanımını hiçbir şekilde etkilemez - sadece
    GiST'in zaten daralttığı aday kümeye ek WHERE koşulu bindirir.
    """
    limit = min(limit, settings.SPOTS_BBOX_MAX_LIMIT)

    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)

    stmt = (
        select(Spot)
        .where(func.ST_Intersects(Spot.coordinates, envelope))
        .where(Spot.deleted_at.is_(None))
        .options(*_SPOT_RELATIONSHIP_OPTIONS)
    )

    if categories:
        stmt = stmt.where(Spot.category.in_(categories))
    if only_verified:
        stmt = stmt.where(Spot.is_verified.is_(True))

    # --- Altyapı (amenities) filtreleri ---
    if any(v is not None for v in (has_fresh_water, has_black_water, has_electricity)):
        stmt = stmt.join(Spot.amenities)
        if has_fresh_water is not None:
            stmt = stmt.where(SpotAmenities.fresh_water_thread.is_(has_fresh_water))
        if has_black_water is not None:
            stmt = stmt.where(SpotAmenities.black_water.is_(has_black_water))
        if has_electricity is not None:
            stmt = stmt.where(SpotAmenities.electricity_220v.is_(has_electricity))

    for name, value in {
        "has_toilet": has_toilet,
        "has_trash_bins": has_trash_bins,
        "is_free": is_free,
        "camping_behavior_allowed": camping_behavior_allowed,
    }.items():
        if value is not None:
            condition = getattr(SpotAmenities, name).is_(value)
            if name in ("is_free", "camping_behavior_allowed"):
                condition = condition & SpotAmenities.rule_information_known.is_(True)
            stmt = stmt.where(Spot.amenities.has(condition))
    if overnight_allowed is not None:
        stmt = stmt.where(
            Spot.overnight_status == ("allowed" if overnight_allowed else "not_allowed")
        )

    # --- Geçiş/yol (passability) filtreleri ---
    if any(v is not None for v in (max_vehicle_length, requires_4x4, caravan_type)):
        stmt = stmt.join(Spot.passability)
        if max_vehicle_length is not None:
            # Aracın uzunluğu, spot'un azami sınırını AŞMIYORSA göster;
            # sınır hiç girilmemişse (NULL) o spot zaten sınırsız kabul edilir.
            stmt = stmt.where(
                or_(
                    SpotPassability.max_vehicle_length.is_(None),
                    SpotPassability.max_vehicle_length >= max_vehicle_length,
                )
            )
        if requires_4x4 is False:
            # Kullanıcı "4x4'üm yok" dedi -> sadece 4x4 gerektiren noktaları ele.
            # requires_4x4=True/None iken filtre uygulanmaz (4x4 sahibi zaten her yere gidebilir).
            stmt = stmt.where(SpotPassability.clearance_required != ClearanceRequired.HIGH_4X4)
        if caravan_type is not None:
            # caravan_types_allowed, DB'de ARRAY(String) olarak tutulur (bkz.
            # SpotPassability modeli); CaravanType enum'unda henüz olmayan
            # değerler (ör. "trailer_single_axle") de dizi elemanı olabilir,
            # bu yüzden burada kasıtlı olarak serbest string kabul ediyoruz.
            stmt = stmt.where(SpotPassability.caravan_types_allowed.any(caravan_type))

    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def get_spot_by_id(db: AsyncSession, *, spot_id: uuid.UUID) -> Spot | None:
    """Tekil spot detayı. Soft-delete edilmişse `None` döner (endpoint 404 çevirir)."""
    stmt = (
        select(Spot)
        .where(Spot.id == spot_id, Spot.deleted_at.is_(None))
        .options(*_SPOT_RELATIONSHIP_OPTIONS)
    )
    return await db.scalar(stmt)


async def set_spot_verified(
    db: AsyncSession, *, spot_id: uuid.UUID, is_verified: bool, actor_id: uuid.UUID | None = None
) -> Feature[SpotProperties] | None:
    """
    Bir spot'un `is_verified` durumunu değiştirir (PATCH /spots/{id}/verify -
    sadece MODERATOR/ADMIN; yetki kontrolü router'da `require_moderator`
    dependency'si ile yapılır, burada tekrar edilmez). Spot bulunamazsa
    `None` döner.

    Diğer servis fonksiyonlarıyla aynı atomiklik deseni: flush -> yanıtı kur
    -> commit; sadece `is_verified`/`updated_at` tazelenir, diğer ilişkiler
    zaten `get_spot_by_id` ile önceden yüklenmiş olduğu için dokunulmaz.
    """
    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None:
        return None

    from app.services.content_service import record_change, snapshot_spot

    before = snapshot_spot(spot)
    spot.is_verified = is_verified
    record_change(db, spot, actor_id, "verified", before)
    await db.flush()
    await db.refresh(spot, attribute_names=["updated_at"])

    feature = spot_to_feature(spot)

    await db.commit()
    return feature


async def create_spot(
    db: AsyncSession,
    *,
    data: SpotCreate,
    created_by: uuid.UUID | None = None,
    created_by_role: UserRole = UserRole.USER,
) -> Feature[SpotProperties]:
    """
    Yeni bir spot'u; passability ve amenities alt kayıtlarıyla birlikte tek
    transaction içinde oluşturur VE GeoJSON yanıtını da o transaction
    KAPANMADAN ÖNCE kurar.

    Sıra kasıtlı: `flush()` (commit değil) satırları DB'ye yazıp
    server_default'ları (created_at/updated_at) hesaplatır ama transaction'ı
    açık bırakır; yanıt (`spot_to_feature`) bu hâlâ-açık transaction
    içindeyken inşa edilir. Yanıt kurulumu (pydantic doğrulama/serileştirme)
    herhangi bir nedenle patlarsa `commit()` hiç çağrılmaz ve `get_db()`
    bağımlılığı transaction'ı rollback eder - istemci 500 alsa bile
    veritabanında "yarım" ya da hayalet bir kayıt kalmaz. (Önceki halinde
    commit önce yapılıyordu; yanıt kurulumu sırasında çıkan bir hata DB'de
    zaten kalıcı olmuş ama istemciye hiç dönmemiş bir spot bırakabiliyordu -
    tam olarak bu, geliştirme sırasında bir MissingGreenlet hatasıyla
    yaşandı ve elle temizlenmesi gerekti.)

    `data.is_verified` sadece `created_by_role` MODERATOR/ADMIN ise dikkate
    alınır; sıradan bir kullanıcı payload'da `is_verified: true` gönderse
    bile burada sessizce False'a zorlanır.
    """
    is_verified = data.is_verified if created_by_role in _PRIVILEGED_ROLES else False

    spot = Spot(
        title=data.title,
        description=data.description,
        category=data.category,
        altitude=data.altitude,
        overnight_status=data.overnight_status,
        max_stay_nights=data.max_stay_nights,
        rule_description=data.rule_description,
        rule_source=data.rule_source,
        rule_checked_on=data.rule_checked_on,
        private_property_permission=data.private_property_permission,
        entry_latitude=data.entry_latitude,
        entry_longitude=data.entry_longitude,
        approach_description=data.approach_description,
        access_season=data.access_season,
        coordinates=lonlat_to_wkb(data.coordinates.longitude, data.coordinates.latitude),
        created_by=created_by,
        is_verified=is_verified,
    )
    spot.passability = SpotPassability(
        road_type=data.passability.road_type,
        max_vehicle_length=data.passability.max_vehicle_length,
        max_vehicle_width=data.passability.max_vehicle_width,
        max_vehicle_height=data.passability.max_vehicle_height,
        max_vehicle_weight_kg=data.passability.max_vehicle_weight_kg,
        clearance_required=data.passability.clearance_required,
        caravan_types_allowed=[c.value for c in data.passability.caravan_types_allowed],
        steep_incline=data.passability.steep_incline,
    )
    spot.amenities = SpotAmenities(
        fresh_water_thread=data.amenities.fresh_water_thread,
        black_water=data.amenities.black_water,
        grey_water=data.amenities.grey_water,
        electricity_220v=data.amenities.electricity_220v,
        rule_information_known=data.amenities.rule_information_known,
        has_toilet=data.amenities.has_toilet,
        has_trash_bins=data.amenities.has_trash_bins,
        is_free=data.amenities.is_free,
        price_description=None if data.amenities.is_free else data.amenities.price_description,
        camping_behavior_allowed=data.amenities.camping_behavior_allowed,
        gsm_signals={
            operator: strength.value for operator, strength in data.amenities.gsm_signals.items()
        },
    )

    db.add(spot)
    await db.flush()
    # `dynamic_statuses`'a Python tarafından doğrudan dokunmak (okuma dahil)
    # SQLAlchemy'nin senkron lazy-load'ını tetikler; AsyncSession'da
    # desteklenmediği için MissingGreenlet fırlatır. `db.refresh()` ise
    # düzgün await edilen bir sorgu olduğu için güvenlidir.
    await db.refresh(
        spot, attribute_names=["created_at", "updated_at", "dynamic_statuses", "photos"]
    )

    from app.services.content_service import record_change

    record_change(db, spot, created_by, "created")
    feature = spot_to_feature(spot)

    await db.commit()
    return feature


def _check_owner_or_privileged(
    *, owner_id: uuid.UUID | None, current_user: User, spot_id: uuid.UUID
) -> None:
    """`soft_delete_spot`/`update_spot` arasında paylaşılan yetki kontrolü."""
    is_owner = owner_id is not None and owner_id == current_user.id
    is_privileged = current_user.role in _PRIVILEGED_ROLES
    if not (is_owner or is_privileged):
        raise SpotPermissionError(spot_id)


async def update_spot(
    db: AsyncSession, *, spot_id: uuid.UUID, data: SpotUpdate, current_user: User
) -> Feature[SpotProperties]:
    """
    Bir spot'un düzenlenebilir alanlarını (title/description/category/altitude
    ve passability/amenities alt kayıtlarını) günceller. Konum burada
    KASITLI OLARAK yok - `SpotUpdate` şemasında `coordinates` alanı hiç
    tanımlı değil, bu uç sadece içerik günceller, taşımaz.

    Yetki: `soft_delete_spot` ile aynı kural (sahibi veya MODERATOR/ADMIN).
    `data`'daki `None` alanlar değiştirilmez (bkz. `SpotUpdate` docstring'i).

    Raises:
        SpotNotFoundError: spot yok ya da zaten soft-delete edilmiş.
        SpotPermissionError: kullanıcı ne sahibi ne de yetkili.
    """
    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None:
        raise SpotNotFoundError(spot_id)

    _check_owner_or_privileged(owner_id=spot.created_by, current_user=current_user, spot_id=spot_id)

    from app.services.content_service import record_change, snapshot_spot

    before = snapshot_spot(spot)
    if data.coordinates is not None:
        if current_user.role not in _PRIVILEGED_ROLES:
            raise SpotPermissionError(spot_id)
        spot.coordinates = lonlat_to_wkb(data.coordinates.longitude, data.coordinates.latitude)
    for name in [
        "overnight_status",
        "max_stay_nights",
        "rule_description",
        "rule_source",
        "rule_checked_on",
        "private_property_permission",
        "entry_latitude",
        "entry_longitude",
        "approach_description",
        "access_season",
    ]:
        if name in data.model_fields_set:
            value = getattr(data, name)
            if name in ("overnight_status", "private_property_permission") and value is None:
                continue
            setattr(spot, name, value)
    if (spot.entry_latitude is None) != (spot.entry_longitude is None):
        raise ValueError("Giriş koordinatları birlikte girilmeli.")

    if data.title is not None:
        spot.title = data.title
    if "description" in data.model_fields_set:
        spot.description = data.description
    if data.category is not None:
        spot.category = data.category
    if "altitude" in data.model_fields_set:
        spot.altitude = data.altitude

    if data.passability is not None:
        spot.passability.road_type = data.passability.road_type
        spot.passability.max_vehicle_length = data.passability.max_vehicle_length
        spot.passability.max_vehicle_width = data.passability.max_vehicle_width
        spot.passability.max_vehicle_height = data.passability.max_vehicle_height
        spot.passability.max_vehicle_weight_kg = data.passability.max_vehicle_weight_kg
        spot.passability.clearance_required = data.passability.clearance_required
        spot.passability.caravan_types_allowed = [
            c.value for c in data.passability.caravan_types_allowed
        ]
        spot.passability.steep_incline = data.passability.steep_incline

    if data.amenities is not None:
        if spot.amenities is None:
            spot.amenities = SpotAmenities(**SpotAmenitiesBase().model_dump())
        for name, value in data.amenities.model_dump(exclude_unset=True).items():
            setattr(spot.amenities, name, value)
        if spot.amenities.is_free:
            spot.amenities.price_description = None
        spot.updated_at = func.now()

    record_change(db, spot, current_user.id, "updated", before)
    spot.updated_at = func.now()
    await db.flush()
    await db.refresh(spot, attribute_names=["updated_at"])
    feature = spot_to_feature(spot)

    await db.commit()
    return feature


async def soft_delete_spot(db: AsyncSession, *, spot_id: uuid.UUID, current_user: User) -> None:
    """
    Spot'u fiziksel olarak silmez; `deleted_at` damgası basar. Böylece
    offline istemciler `/spots/sync` üzerinden "bu nokta kaldırıldı"
    bilgisini delta olarak alıp yerel SQLite kopyalarını temizleyebilir.

    Sadece spot'un sahibi (`created_by == current_user.id`) veya
    MODERATOR/ADMIN rolündeki kullanıcılar silebilir. `created_by` NULL ise
    (ör. auth eklenmeden önce oluşturulmuş seed verisi) sahiplik iddia
    edilemez; sadece moderatör/admin silebilir.

    Raises:
        SpotNotFoundError: spot yok ya da zaten soft-delete edilmiş.
        SpotPermissionError: kullanıcı ne sahibi ne de yetkili.
    """
    row = (
        await db.execute(
            select(Spot.created_by)
            .where(Spot.id == spot_id, Spot.deleted_at.is_(None))
            .with_for_update()
        )
    ).first()
    if row is None:
        raise SpotNotFoundError(spot_id)
    owner_id = row[0]

    _check_owner_or_privileged(owner_id=owner_id, current_user=current_user, spot_id=spot_id)

    from app.services.content_service import record_change, snapshot_spot

    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None:
        raise SpotNotFoundError(spot_id)
    before = snapshot_spot(spot)
    from datetime import UTC

    spot.deleted_at = datetime.now(UTC)
    record_change(db, spot, current_user.id, "deleted", before)

    spot.updated_at = func.now()
    await db.commit()


async def add_dynamic_status(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    data: DynamicStatusCreate,
    reported_by: uuid.UUID | None = None,
) -> "DynamicStatus | None":
    """
    ESKİ canlı durum ucu (zabıta + kalabalık) - geriye dönük uyumluluk için korunur; artık
    `live_report_service.create_legacy_status` üzerinden AYNI süreli/moderasyonlu modele yazar
    (zabıta müdahalesi/`full` doluluk türlü bildirim olur, geri kalanı bilgi satırı kalır).
    Yeni istemciler `POST /spots/{id}/live-reports` kullanmalıdır.

    Süresi dolan bildirimler burada silinmez - `_ACTIVE_STATUS_CONDITION` ile sorgu katmanında
    aktif sonuçlardan düşer. Spot bulunamazsa/soft-delete ise `None` döner (endpoint 404).

    Raises: `DuplicateActiveReportError` (aynı kullanıcı+tür için aktif bildirim varken),
    `InvalidExpiryError` (`valid_until` geçmişte).
    """
    # Döngüsel import'u önlemek için lazy (live_report_service spot_service'e bağımlı).
    from app.services.live_report_service import create_legacy_status

    try:
        return await create_legacy_status(db, spot_id=spot_id, data=data, reported_by=reported_by)
    except SpotNotFoundError:
        return None


async def get_spots_sync(
    db: AsyncSession,
    *,
    since: datetime,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = settings.SPOTS_BBOX_DEFAULT_LIMIT,
) -> tuple[list[Spot], list[uuid.UUID], datetime]:
    """
    Delta senkron sorgusu: `since` tarihinden sonra eklenen/güncellenen
    spot'ları ve bu pencerede soft-delete edilmiş spot id'lerini döndürür.

    Checkpoint güvenliği: `server_time`, ana sorgu ÇALIŞTIRILMADAN ÖNCE
    veritabanının kendi saatinden (`clock_timestamp()`) okunur. Böylece
    sorgumuz çalışırken commit olan başka bir yazının `updated_at` değeri
    kaçınılmaz olarak bu checkpoint'ten büyük/eşit olur ve bir SONRAKİ
    `since=server_time` çağrısında yakalanır - hiçbir güncelleme sessizce
    kaybolmaz. (Checkpoint'i sorgudan SONRA veya app sunucusunun kendi
    saatinden almak, DB/app arasında saat kayması ya da sorgu sırasında
    commit edilen satırların gözden kaçması riskini taşır.)
    """
    limit = min(limit, settings.SPOTS_BBOX_MAX_LIMIT)

    checkpoint = await db.scalar(select(func.clock_timestamp()))

    filters = [Spot.updated_at > since]
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
        filters.append(func.ST_Intersects(Spot.coordinates, envelope))

    upserts_stmt = (
        select(Spot)
        .where(*filters, Spot.deleted_at.is_(None))
        .options(*_SPOT_RELATIONSHIP_OPTIONS)
        .order_by(Spot.updated_at.asc())
        .limit(limit)
    )
    upserts = list((await db.execute(upserts_stmt)).scalars().unique().all())

    deleted_stmt = (
        select(Spot.id)
        .where(*filters, Spot.deleted_at.isnot(None))
        .order_by(Spot.updated_at.asc())
        .limit(limit)
    )
    deleted_ids = list((await db.execute(deleted_stmt)).scalars().all())

    return upserts, deleted_ids, checkpoint
