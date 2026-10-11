"""
Çevresel hizmet noktaları (`service_points`) iş mantığı - bkz. app/models/service_point.py.

Gruba özgü kurallar burada uygulanır (şema/CHECK kısıtları son savunma hattıdır):
yıldız/yorum yalnızca Yeme & İçme'de, ücret/kullanılabilirlik durumu yalnızca
WC/duşta; sağlık noktaları yalnızca tür + konum (+ opsiyonel ad) taşır.
"""
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geography

from app.core.config import settings
from app.models.basemap_poi import BasemapPoi
from app.models.enums import (
    ServicePointCategory,
    ServicePointGroup,
    SpotSource,
    UserRole,
    service_point_group,
)
from app.models.osm_cache import OsmPoi
from app.services import osm_source
from app.services.osm_source import ExternalStatus
from app.utils.text_match import names_match
from app.models.service_point import (
    ServicePoint,
    ServicePointConfirmation,
    ServicePointReport,
    ServicePointReview,
    ServicePointStatusUpdate,
)
from app.models.user import User
from app.schemas.service_point import (
    NameSuggestion,
    ServicePointCreate,
    ServicePointReportCreate,
    ServicePointReportResolution,
    ServicePointReviewCreate,
    ServicePointReviewUpdate,
    ServicePointStatusCreate,
    ServicePointUpdate,
)
from app.utils.geo import lonlat_to_wkb

_PRIVILEGED_ROLES = (UserRole.MODERATOR, UserRole.ADMIN)

# Aynı türden iki kayıt bu mesafeden yakınsa mükerrer sayılır (GPS sapması payı).
DUPLICATE_RADIUS_M = 25
# Sağlık kuruluşu adı önerisi: seçilen noktaya bu mesafedeki OSM kaydı aranır.
NAME_SUGGESTION_RADIUS_M = 150
_BASEMAP_CATEGORY = {
    ServicePointCategory.HOSPITAL: "hospital",
    ServicePointCategory.HEALTH_CENTER: "clinic",
}
_CATEGORY_LABEL = {
    ServicePointCategory.MEAT_RESTAURANT: "et restoranı",
    ServicePointCategory.FISH_RESTAURANT: "balık restoranı",
    ServicePointCategory.OTHER_RESTAURANT: "restoran/kafe",
    ServicePointCategory.HOSPITAL: "hastane",
    ServicePointCategory.HEALTH_CENTER: "sağlık ocağı",
    ServicePointCategory.WC: "WC",
    ServicePointCategory.SHOWER: "duş",
}


class ServicePointNotFoundError(Exception):
    """Nokta (veya değerlendirme/bildirim) yok ya da kaldırılmış."""


class ServicePointPermissionError(Exception):
    """Kullanıcı ne kaydın sahibi ne de MODERATOR/ADMIN."""


class ServicePointConflictError(Exception):
    """Mükerrer kayıt / tekrarlanan değerlendirme veya bildirim. `existing_id`: varsa mevcut nokta."""

    def __init__(self, message: str, existing_id: uuid.UUID | None = None):
        super().__init__(message)
        self.existing_id = existing_id


class ServicePointRuleError(Exception):
    """Bu nokta türü için geçerli olmayan işlem (ör. hastaneye yıldız vermek)."""


def _is_privileged(user: User) -> bool:
    return user.role in _PRIVILEGED_ROLES


def _check_owner_or_privileged(owner_id: uuid.UUID | None, user: User) -> None:
    if not ((owner_id is not None and owner_id == user.id) or _is_privileged(user)):
        raise ServicePointPermissionError()


def _point(longitude: float, latitude: float):
    return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)


def _distance_m(column, longitude: float, latitude: float):
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    return func.ST_Distance(cast(column, Geography), cast(point, Geography))


def _within_m(column, longitude: float, latitude: float, radius_m: float):
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    return func.ST_DWithin(cast(column, Geography), cast(point, Geography), radius_m)


async def list_in_bbox(
    db: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    categories: list[ServicePointCategory] | None = None,
    limit: int = settings.SPOTS_BBOX_DEFAULT_LIMIT,
    order_center: tuple[float, float] | None = None,
) -> list[ServicePoint]:
    """`order_center` (lng, lat) verilirse en yakından başlar - limit uygulanınca en yakınlar kalır."""
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    stmt = (
        select(ServicePoint)
        .where(func.ST_Intersects(ServicePoint.coordinates, envelope))
        .where(ServicePoint.deleted_at.is_(None))
    )
    if categories:
        stmt = stmt.where(ServicePoint.category.in_(categories))
    if order_center is not None:
        stmt = stmt.order_by(ServicePoint.coordinates.op("<->")(_point(*order_center)))
    stmt = stmt.limit(min(limit, settings.SPOTS_BBOX_MAX_LIMIT))
    return list((await db.scalars(stmt)).all())


async def get_point(db: AsyncSession, point_id: uuid.UUID) -> ServicePoint:
    point = await db.scalar(
        select(ServicePoint).where(ServicePoint.id == point_id, ServicePoint.deleted_at.is_(None))
    )
    if point is None:
        raise ServicePointNotFoundError(point_id)
    return point


# --- Harici (OpenStreetMap) noktalarla birleştirme ----------------------------------

# Bir harici nokta ile KaravanTR kaydı bu mesafeden yakın ve "aynı aileden" ise
# (ve adları çelişmiyorsa) aynı yer sayılır; haritada tek marker kalır.
EXTERNAL_MATCH_RADIUS_M = 40
_BASEMAP_TO_CATEGORY = {"hospital": ServicePointCategory.HOSPITAL, "clinic": ServicePointCategory.HEALTH_CENTER}
_CATEGORY_TO_BASEMAP = {v: k for k, v in _BASEMAP_TO_CATEGORY.items()}


@dataclass
class ExternalPoint:
    """OSM önbelleğinden (osm_pois / basemap_pois) gelen, henüz KaravanTR kaydı OLMAYAN nokta."""

    id: uuid.UUID  # kararlı sanal id - somutlaşınca service_points.id de bu olur
    osm_id: str
    category: ServicePointCategory
    name: str | None
    longitude: float
    latitude: float
    tags: dict = field(default_factory=dict)
    fetched_at: datetime | None = None


PointView = ServicePoint | ExternalPoint


def _same_family(a: ServicePointCategory, b: ServicePointCategory) -> bool:
    """Restoranlar ve sağlık kuruluşları grup içinde (OSM türü kaba olabilir), WC/duş birebir eşleşir."""
    group = service_point_group(a)
    if group is ServicePointGroup.BASIC:
        return a == b
    return group is service_point_group(b)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def is_same_place(
    a_category: ServicePointCategory, a_name: str | None, a_lon: float, a_lat: float,
    b_category: ServicePointCategory, b_name: str | None, b_lon: float, b_lat: float,
) -> bool:
    """Kategori ailesi + konum yakınlığı + (karar verilebiliyorsa) ad benzerliği."""
    if not _same_family(a_category, b_category):
        return False
    if haversine_m(a_lon, a_lat, b_lon, b_lat) > EXTERNAL_MATCH_RADIUS_M:
        return False
    return names_match(a_name, b_name) is not False


async def _external_points_in_bbox(
    db: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    categories: set[ServicePointCategory],
    include_tiles: bool,
    limit: int,
    order_center: tuple[float, float] | None = None,
) -> list[ExternalPoint]:
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    center = _point(*order_center) if order_center else None
    points: list[ExternalPoint] = []
    tile_categories = categories & osm_source.TILE_CATEGORIES
    if include_tiles and tile_categories:
        rows = (
            await db.execute(
                select(OsmPoi, func.ST_X(OsmPoi.coordinates), func.ST_Y(OsmPoi.coordinates))
                .where(func.ST_Intersects(OsmPoi.coordinates, envelope), OsmPoi.category.in_(tile_categories))
                .order_by(OsmPoi.coordinates.op("<->")(center) if center is not None else OsmPoi.osm_id)
                .limit(limit)
            )
        ).all()
        points += [
            ExternalPoint(
                id=row.virtual_id, osm_id=row.osm_id, category=row.category, name=row.name,
                longitude=lng, latitude=lat, tags=row.tags or {}, fetched_at=row.fetched_at,
            )
            for row, lng, lat in rows
        ]
    basemap_categories = [_CATEGORY_TO_BASEMAP[c] for c in categories if c in _CATEGORY_TO_BASEMAP]
    if basemap_categories:
        rows = (
            await db.execute(
                select(BasemapPoi, func.ST_X(BasemapPoi.coordinates), func.ST_Y(BasemapPoi.coordinates))
                .where(func.ST_Intersects(BasemapPoi.coordinates, envelope), BasemapPoi.category.in_(basemap_categories))
                .order_by(BasemapPoi.coordinates.op("<->")(center) if center is not None else BasemapPoi.osm_id)
                .limit(limit)
            )
        ).all()
        points += [
            ExternalPoint(
                id=row.virtual_id, osm_id=row.osm_id, category=_BASEMAP_TO_CATEGORY[row.category], name=row.name,
                longitude=lng, latitude=lat, tags=row.tags or {}, fetched_at=row.last_seen_at,
            )
            for row, lng, lat in rows
        ]
    return points


async def _linked_osm_ids(db: AsyncSession, osm_ids: list[str]) -> set[str]:
    """KaravanTR'de karşılığı olan OSM kimlikleri - SİLİNMİŞ kayıtlar dahil (kapanmış/mükerrer
    diye kaldırılan bir yer OSM'den tekrar görünmesin)."""
    if not osm_ids:
        return set()
    rows = await db.scalars(select(ServicePoint.osm_id).where(ServicePoint.osm_id.in_(osm_ids)))
    return set(rows.all())


def _dedupe_external(points: list[ServicePoint], external: list[ExternalPoint], linked: set[str]) -> list[ExternalPoint]:
    kept: list[ExternalPoint] = []
    seen: set[str] = set()
    for ext in external:
        if ext.osm_id in linked or ext.osm_id in seen:
            continue
        if any(
            is_same_place(ext.category, ext.name, ext.longitude, ext.latitude,
                          p.category, p.name, p.longitude, p.latitude)
            for p in points
        ):
            continue
        # OSM'nin kendi içindeki kopyalar (ör. aynı işletme hem nokta hem bina olarak
        # girilmiş): yalnızca ad AÇIKÇA eşleşiyorsa ya da aynı türde neredeyse aynı
        # koordinattaysa birleştirilir - yan yana iki ayrı adsız WC korunur.
        if any(_same_external_object(ext, other) for other in kept):
            continue
        seen.add(ext.osm_id)
        kept.append(ext)
    return kept


EXTERNAL_SAME_COORD_M = 3


def _same_external_object(a: ExternalPoint, b: ExternalPoint) -> bool:
    if not _same_family(a.category, b.category):
        return False
    distance = haversine_m(a.longitude, a.latitude, b.longitude, b.latitude)
    if distance > EXTERNAL_MATCH_RADIUS_M:
        return False
    if names_match(a.name, b.name) is True:
        return True
    return a.category == b.category and distance <= EXTERNAL_SAME_COORD_M


async def list_merged(
    db: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    categories: list[ServicePointCategory] | None = None,
    limit: int = settings.SPOTS_BBOX_DEFAULT_LIMIT,
    fetcher: osm_source.Fetcher | None = None,
    max_view_tiles: int | None = None,
    order_center: tuple[float, float] | None = None,
) -> tuple[list[PointView], ExternalStatus]:
    """KaravanTR kayıtları + OSM önbelleği, mükerrerleri ayıklanmış tek liste.

    Öncelik her zaman KaravanTR kaydındadır (topluluk katkısı orada). Harici kaynak
    hata verse bile KaravanTR kayıtları döner; durum ikinci değerde bildirilir.
    """
    wanted = set(categories or ServicePointCategory)
    points = await list_in_bbox(
        db, min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat, categories=list(wanted), limit=limit,
        order_center=order_center,
    )
    if not settings.OSM_EXTERNAL_ENABLED:
        return list(points), ExternalStatus.DISABLED
    # Çok geniş görünümde harici veri hiç eklenmez (sağlık dahil): binlerce noktanın
    # rastgele bir alt kümesi yanıltıcı olurdu. İstemci bu durumda yakınlaştırma ipucu gösterir.
    max_view_tiles = max_view_tiles or settings.OSM_MAX_TILES_PER_VIEW
    if len(osm_source.tiles_for_bbox(min_lon, min_lat, max_lon, max_lat)) > max_view_tiles:
        return list(points), ExternalStatus.TOO_WIDE

    if wanted & osm_source.TILE_CATEGORIES:
        status = await osm_source.ensure_tiles(
            db, min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat, fetcher=fetcher,
            max_view_tiles=max_view_tiles,
        )
    else:
        status = ExternalStatus.NOT_NEEDED
    external = await _external_points_in_bbox(
        db, min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat, categories=wanted,
        include_tiles=True, limit=limit, order_center=order_center,
    )
    linked = await _linked_osm_ids(db, [e.osm_id for e in external])
    external = _dedupe_external(points, external, linked)
    merged: list[PointView] = [*points, *external]
    return merged[: min(limit, settings.SPOTS_BBOX_MAX_LIMIT)], status


async def list_nearby(
    db: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_m: int,
    categories: list[ServicePointCategory] | None = None,
    limit: int = 200,
    fetcher: osm_source.Fetcher | None = None,
) -> tuple[list[tuple[PointView, float]], ExternalStatus]:
    """Bir merkez (kullanıcı konumu / seçili kamp noktası) çevresindeki hizmetler, mesafeye göre sıralı."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * max(math.cos(math.radians(latitude)), 0.01))
    points, status = await list_merged(
        db,
        min_lon=longitude - dlon, min_lat=latitude - dlat, max_lon=longitude + dlon, max_lat=latitude + dlat,
        categories=categories, limit=settings.SPOTS_BBOX_MAX_LIMIT, fetcher=fetcher,
        max_view_tiles=settings.OSM_MAX_TILES_PER_NEARBY, order_center=(longitude, latitude),
    )
    with_distance = [(p, haversine_m(longitude, latitude, p.longitude, p.latitude)) for p in points]
    within = sorted((pd for pd in with_distance if pd[1] <= radius_m), key=lambda pd: pd[1])
    return within[:limit], status


async def get_point_view(db: AsyncSession, point_id: uuid.UUID) -> PointView:
    """KaravanTR kaydı veya (henüz somutlaşmamış) harici OSM noktası. Kaldırılmışsa 404."""
    row = await db.get(ServicePoint, point_id)
    if row is not None:
        if row.deleted_at is not None:
            raise ServicePointNotFoundError(point_id)
        return row
    external = await _external_by_id(db, point_id)
    if external is None or await _linked_osm_ids(db, [external.osm_id]):
        raise ServicePointNotFoundError(point_id)
    return external


async def _external_by_id(db: AsyncSession, point_id: uuid.UUID) -> ExternalPoint | None:
    row = (
        await db.execute(
            select(OsmPoi, func.ST_X(OsmPoi.coordinates), func.ST_Y(OsmPoi.coordinates)).where(OsmPoi.virtual_id == point_id)
        )
    ).first()
    if row is not None:
        poi, lng, lat = row
        return ExternalPoint(id=poi.virtual_id, osm_id=poi.osm_id, category=poi.category, name=poi.name,
                             longitude=lng, latitude=lat, tags=poi.tags or {}, fetched_at=poi.fetched_at)
    row = (
        await db.execute(
            select(BasemapPoi, func.ST_X(BasemapPoi.coordinates), func.ST_Y(BasemapPoi.coordinates)).where(
                BasemapPoi.virtual_id == point_id, BasemapPoi.category.in_(list(_BASEMAP_TO_CATEGORY))
            )
        )
    ).first()
    if row is not None:
        poi, lng, lat = row
        return ExternalPoint(id=poi.virtual_id, osm_id=poi.osm_id, category=_BASEMAP_TO_CATEGORY[poi.category],
                             name=poi.name, longitude=lng, latitude=lat, tags=poi.tags or {}, fetched_at=poi.last_seen_at)
    return None


async def resolve_for_contribution(db: AsyncSession, point_id: uuid.UUID) -> ServicePoint:
    """Katkı (puan/durum/bildirim) yazılacak KaravanTR kaydı. Harici bir OSM noktasıysa
    önce `osm_id` ile bağlı bir `service_points` satırı olarak somutlaştırılır (aynı id ile);
    OSM verisi yalnızca başlangıç değeridir, doğrulanmış sayılmaz."""
    view = await get_point_view(db, point_id)
    if isinstance(view, ServicePoint):
        return view
    is_basic = view.category in osm_source.BASIC_CATEGORIES
    point = ServicePoint(
        id=view.id,
        category=view.category,
        name=view.name,
        coordinates=lonlat_to_wkb(view.longitude, view.latitude),
        source=SpotSource.OVERPASS_OSM,
        osm_id=view.osm_id,
        extra={**view.tags, "osm_url": f"https://www.openstreetmap.org/{view.osm_id}"},
        fee_status=osm_source.fee_status_from_tags(view.tags) if is_basic else "unknown",
    )
    db.add(point)
    try:
        await db.flush()
    except IntegrityError:
        # Eşzamanlı başka bir katkı aynı noktayı az önce somutlaştırdı.
        await db.rollback()
        return await get_point(db, point_id)
    return point


async def _find_duplicate(
    db: AsyncSession, *, category: ServicePointCategory, longitude: float, latitude: float, exclude: uuid.UUID | None = None
) -> ServicePoint | None:
    stmt = select(ServicePoint).where(
        ServicePoint.category == category,
        ServicePoint.deleted_at.is_(None),
        _within_m(ServicePoint.coordinates, longitude, latitude, DUPLICATE_RADIUS_M),
    )
    if exclude is not None:
        stmt = stmt.where(ServicePoint.id != exclude)
    return await db.scalar(stmt.limit(1))


async def _find_external_duplicate(
    db: AsyncSession, *, category: ServicePointCategory, name: str | None, longitude: float, latitude: float
) -> ExternalPoint | None:
    """Önbellekteki (OSM) noktalardan aynı yer sayılan ilki. Overpass'a GİTMEZ - yalnızca cache."""
    dlat = EXTERNAL_MATCH_RADIUS_M / 111_320
    dlon = EXTERNAL_MATCH_RADIUS_M / (111_320 * max(math.cos(math.radians(latitude)), 0.01))
    family = {c for c in ServicePointCategory if _same_family(category, c)}
    candidates = await _external_points_in_bbox(
        db, min_lon=longitude - dlon, min_lat=latitude - dlat, max_lon=longitude + dlon, max_lat=latitude + dlat,
        categories=family, include_tiles=True, limit=50,
    )
    linked = await _linked_osm_ids(db, [c.osm_id for c in candidates])
    for candidate in candidates:
        if candidate.osm_id not in linked and is_same_place(
            category, name, longitude, latitude,
            candidate.category, candidate.name, candidate.longitude, candidate.latitude,
        ):
            return candidate
    return None


async def create_point(db: AsyncSession, *, data: ServicePointCreate, user: User) -> ServicePoint:
    lon, lat = data.coordinates.longitude, data.coordinates.latitude
    if existing := await _find_duplicate(db, category=data.category, longitude=lon, latitude=lat):
        raise ServicePointConflictError(
            f"Bu konumun {DUPLICATE_RADIUS_M} m yakınında zaten bir {_CATEGORY_LABEL[data.category]} kaydı var.",
            existing_id=existing.id,
        )
    if settings.OSM_EXTERNAL_ENABLED and (
        external := await _find_external_duplicate(db, category=data.category, name=data.name, longitude=lon, latitude=lat)
    ):
        label = f"“{external.name}”" if external.name else f"bir {_CATEGORY_LABEL[external.category]}"
        raise ServicePointConflictError(
            f"Bu yer harita verisinde zaten var ({label}). Yeni kayıt yerine mevcut noktaya bilgi ekleyebilirsiniz.",
            existing_id=external.id,
        )

    point = ServicePoint(
        category=data.category,
        name=data.name,
        coordinates=lonlat_to_wkb(lon, lat),
        source=SpotSource.USER_ADDED,
        created_by=user.id,
    )
    if data.fee_status is not None or data.availability_status is not None:
        _apply_status(point, data.fee_status, data.availability_status)
    db.add(point)
    await db.flush()
    if point.status_checked_at is not None:
        db.add(
            ServicePointStatusUpdate(
                service_point_id=point.id,
                user_id=user.id,
                fee_status=data.fee_status,
                availability_status=data.availability_status,
            )
        )
    await db.commit()
    await db.refresh(point)
    return point


async def update_point(db: AsyncSession, *, point_id: uuid.UUID, data: ServicePointUpdate, user: User) -> ServicePoint:
    point = await get_point(db, point_id)
    _check_owner_or_privileged(point.created_by, user)

    if data.category is not None and data.category != point.category:
        if service_point_group(data.category) is not service_point_group(point.category):
            raise ServicePointRuleError("Tür yalnızca aynı grup içinde değiştirilebilir.")
        point.category = data.category
    if "name" in data.model_fields_set:
        point.name = data.name or None
    if service_point_group(point.category) is ServicePointGroup.FOOD and not point.name:
        raise ServicePointRuleError("Restoran kayıtlarında işletme adı zorunludur.")
    if data.coordinates is not None:
        if not _is_privileged(user):
            raise ServicePointPermissionError()
        point.coordinates = lonlat_to_wkb(data.coordinates.longitude, data.coordinates.latitude)

    point.updated_at = func.now()
    await db.commit()
    await db.refresh(point)
    return point


async def delete_point(db: AsyncSession, *, point_id: uuid.UUID, user: User) -> None:
    point = await get_point(db, point_id)
    _check_owner_or_privileged(point.created_by, user)
    point.deleted_at = datetime.now(UTC)
    point.updated_at = func.now()
    await db.commit()


# --- Yeme & İçme: yıldız + yorum -------------------------------------------------


def _require_group(point: "PointView", group: ServicePointGroup, message: str) -> None:
    if service_point_group(point.category) is not group:
        raise ServicePointRuleError(message)


async def _refresh_rating_summary(db: AsyncSession, point: ServicePoint) -> None:
    average, count = (
        await db.execute(
            select(func.avg(ServicePointReview.rating), func.count(ServicePointReview.id)).where(
                ServicePointReview.service_point_id == point.id, ServicePointReview.is_active.is_(True)
            )
        )
    ).one()
    point.average_rating = round(float(average), 2) if average is not None else None
    point.review_count = int(count)


async def list_reviews(db: AsyncSession, *, point_id: uuid.UUID, limit: int, offset: int) -> list[ServicePointReview]:
    if isinstance(await get_point_view(db, point_id), ExternalPoint):
        return []  # henüz kimse katkı yapmamış harici nokta
    stmt = (
        select(ServicePointReview)
        .where(ServicePointReview.service_point_id == point_id, ServicePointReview.is_active.is_(True))
        .order_by(ServicePointReview.created_at.desc(), ServicePointReview.id)
        .offset(offset)
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def get_my_review(db: AsyncSession, *, point_id: uuid.UUID, user: User) -> ServicePointReview | None:
    return await db.scalar(
        select(ServicePointReview).where(
            ServicePointReview.service_point_id == point_id,
            ServicePointReview.user_id == user.id,
            ServicePointReview.is_active.is_(True),
        )
    )


_NOT_FOOD = "Yıldız ve yorum yalnızca Yeme & İçme noktalarında kullanılabilir."


async def add_review(
    db: AsyncSession, *, point_id: uuid.UUID, user: User, data: ServicePointReviewCreate
) -> ServicePointReview:
    _require_group(await get_point_view(db, point_id), ServicePointGroup.FOOD, _NOT_FOOD)
    point = await resolve_for_contribution(db, point_id)
    if await get_my_review(db, point_id=point_id, user=user) is not None:
        raise ServicePointConflictError("Bu nokta için zaten bir değerlendirmeniz var; onu düzenleyebilirsiniz.")

    review = ServicePointReview(
        service_point_id=point_id, user_id=user.id, rating=data.rating, comment=(data.comment or "").strip() or None
    )
    db.add(review)
    try:
        await db.flush()
    except IntegrityError:
        # Eşzamanlı ikinci istek - kısmi unique index son sözü söyler.
        await db.rollback()
        raise ServicePointConflictError("Bu nokta için zaten bir değerlendirmeniz var.") from None
    await _refresh_rating_summary(db, point)
    await db.commit()
    await db.refresh(review)
    return review


async def _get_active_review(db: AsyncSession, point_id: uuid.UUID, review_id: uuid.UUID) -> ServicePointReview:
    review = await db.get(ServicePointReview, review_id)
    if review is None or not review.is_active or review.service_point_id != point_id:
        raise ServicePointNotFoundError(review_id)
    return review


async def update_review(
    db: AsyncSession, *, point_id: uuid.UUID, review_id: uuid.UUID, user: User, data: ServicePointReviewUpdate
) -> ServicePointReview:
    point = await get_point(db, point_id)
    review = await _get_active_review(db, point_id, review_id)
    _check_owner_or_privileged(review.user_id, user)
    if data.rating is not None:
        review.rating = data.rating
    if data.comment is not None:
        review.comment = data.comment.strip() or None
    review.updated_at = func.now()
    await db.flush()
    await _refresh_rating_summary(db, point)
    await db.commit()
    await db.refresh(review)
    return review


async def delete_review(db: AsyncSession, *, point_id: uuid.UUID, review_id: uuid.UUID, user: User) -> None:
    point = await get_point(db, point_id)
    review = await _get_active_review(db, point_id, review_id)
    _check_owner_or_privileged(review.user_id, user)
    review.is_active = False
    await db.flush()
    await _refresh_rating_summary(db, point)
    await db.commit()


# --- Temel ihtiyaçlar: ücret / kullanılabilirlik ----------------------------------


def _apply_status(point: ServicePoint, fee_status: str | None, availability_status: str | None) -> None:
    if fee_status is not None:
        point.fee_status = fee_status
    if availability_status is not None:
        point.availability_status = availability_status
    point.status_checked_at = datetime.now(UTC)


async def add_status_update(
    db: AsyncSession, *, point_id: uuid.UUID, user: User, data: ServicePointStatusCreate
) -> ServicePoint:
    _require_group(
        await get_point_view(db, point_id),
        ServicePointGroup.BASIC,
        "Ücret/kullanılabilirlik bilgisi yalnızca WC ve duş için girilebilir.",
    )
    point = await resolve_for_contribution(db, point_id)
    _apply_status(point, data.fee_status, data.availability_status)
    point.updated_at = func.now()
    db.add(
        ServicePointStatusUpdate(
            service_point_id=point.id,
            user_id=user.id,
            fee_status=data.fee_status,
            availability_status=data.availability_status,
        )
    )
    await db.commit()
    await db.refresh(point)
    return point


async def list_status_updates(db: AsyncSession, *, point_id: uuid.UUID, limit: int = 10) -> list[ServicePointStatusUpdate]:
    if isinstance(await get_point_view(db, point_id), ExternalPoint):
        return []
    stmt = (
        select(ServicePointStatusUpdate)
        .where(ServicePointStatusUpdate.service_point_id == point_id)
        .order_by(ServicePointStatusUpdate.created_at.desc(), ServicePointStatusUpdate.id)
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


# --- Sorun bildirimi (tüm türler) -------------------------------------------------


async def create_report(
    db: AsyncSession, *, point_id: uuid.UUID, user: User, data: ServicePointReportCreate
) -> ServicePointReport:
    await resolve_for_contribution(db, point_id)
    report = ServicePointReport(
        service_point_id=point_id,
        reporter_id=user.id,
        reason=data.reason,
        description=(data.description or "").strip() or None,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ServicePointConflictError(
            "Bu nokta için incelenmeyi bekleyen bir bildiriminiz zaten var."
        ) from None
    await db.commit()
    await db.refresh(report)
    return report


async def report_queue(
    db: AsyncSession, *, state: str, limit: int, offset: int
) -> list[tuple[ServicePointReport, ServicePoint]]:
    stmt = (
        select(ServicePointReport, ServicePoint)
        .join(ServicePoint, ServicePoint.id == ServicePointReport.service_point_id)
        .where(ServicePointReport.state == state)
        .order_by(ServicePointReport.created_at.desc(), ServicePointReport.id)
        .offset(offset)
        .limit(limit)
    )
    return [(report, point) for report, point in (await db.execute(stmt)).all()]


async def resolve_report(
    db: AsyncSession, *, report_id: uuid.UUID, moderator: User, data: ServicePointReportResolution
) -> ServicePointReport:
    report = await db.get(ServicePointReport, report_id)
    if report is None:
        raise ServicePointNotFoundError(report_id)
    if report.state != "pending":
        raise ServicePointConflictError("Bu bildirim zaten sonuçlandırılmış.")

    now = datetime.now(UTC)
    report.state = "resolved" if data.action == "resolve" else "rejected"
    report.resolution_note = (data.note or "").strip() or None
    report.resolved_by = moderator.id
    report.resolved_at = now

    if data.remove_point:
        point = await db.get(ServicePoint, report.service_point_id)
        if point is not None and point.deleted_at is None:
            point.deleted_at = now
            point.updated_at = func.now()
        # Aynı noktanın diğer bekleyen bildirimleri de bu kararla kapanır.
        others = await db.scalars(
            select(ServicePointReport).where(
                ServicePointReport.service_point_id == report.service_point_id,
                ServicePointReport.state == "pending",
                ServicePointReport.id != report.id,
            )
        )
        for other in others:
            other.state = "resolved"
            other.resolved_by = moderator.id
            other.resolved_at = now
            other.resolution_note = "Nokta kaldırıldı."

    await db.commit()
    await db.refresh(report)
    return report


# --- Sağlık kuruluşu adı önerisi --------------------------------------------------


async def suggest_name(
    db: AsyncSession, *, category: ServicePointCategory, latitude: float, longitude: float
) -> NameSuggestion:
    """Seçilen konuma en yakın, adı bilinen OSM sağlık kaydı (yalnızca hastane/sağlık ocağı).

    Kaynak `basemap_pois` (periyodik OSM içe aktarımı); bulunamazsa `name=None` - istemci
    alanı boş bırakır, sağlık noktalarında ad zaten zorunlu değildir.
    """
    basemap_category = _BASEMAP_CATEGORY.get(category)
    if basemap_category is None:
        return NameSuggestion(name=None)
    distance = _distance_m(BasemapPoi.coordinates, longitude, latitude)
    row = (
        await db.execute(
            select(BasemapPoi.name, BasemapPoi.osm_id, distance.label("distance"))
            .where(
                BasemapPoi.category == basemap_category,
                BasemapPoi.name.isnot(None),
                _within_m(BasemapPoi.coordinates, longitude, latitude, NAME_SUGGESTION_RADIUS_M),
            )
            .order_by(distance)
            .limit(1)
        )
    ).first()
    if row is None:
        return NameSuggestion(name=None)
    return NameSuggestion(name=row.name, osm_id=row.osm_id, distance_m=round(float(row.distance), 1))


# --- Doğrulama: topluluk teyidi + moderatör onayı ---------------------------------

# Aynı kullanıcı aynı noktayı bu süre dolmadan yeniden teyit edemez (sayaç şişirilemez).
CONFIRMATION_COOLDOWN = timedelta(hours=24)


async def confirm_point(db: AsyncSession, *, point_id: uuid.UUID, user: User) -> ServicePoint:
    """"Bu yer hâlâ burada / hizmet veriyor" teyidi - tüm türler (sağlık dahil; puan değildir)."""
    point = await resolve_for_contribution(db, point_id)
    now = datetime.now(UTC)
    existing = await db.scalar(
        select(ServicePointConfirmation).where(
            ServicePointConfirmation.service_point_id == point.id, ServicePointConfirmation.user_id == user.id
        )
    )
    if existing is not None and existing.confirmed_at > now - CONFIRMATION_COOLDOWN:
        raise ServicePointConflictError("Bu noktayı son 24 saatte zaten teyit ettiniz.")
    if existing is None:
        db.add(ServicePointConfirmation(service_point_id=point.id, user_id=user.id, confirmed_at=now))
    else:
        existing.confirmed_at = now
    await db.flush()
    point.confirmation_count = await db.scalar(
        select(func.count()).select_from(ServicePointConfirmation).where(
            ServicePointConfirmation.service_point_id == point.id
        )
    )
    point.last_confirmed_at = now
    point.updated_at = func.now()
    await db.commit()
    await db.refresh(point)
    return point


async def set_verified(db: AsyncSession, *, point_id: uuid.UUID, is_verified: bool) -> ServicePoint:
    """Moderatör onayı (yetki kontrolü router'da `require_moderator` ile)."""
    point = await resolve_for_contribution(db, point_id)
    point.is_verified = is_verified
    point.updated_at = func.now()
    await db.commit()
    await db.refresh(point)
    return point


# --- Kötüye kullanım önlemleri: kullanıcı başına kotalar ---------------------------
# IP başına genel yazma sınırı zaten HTTP katmanında var (app/core/http_middleware.py);
# bunlar hesap başınadır ve birden çok IP'den gelen toplu eklemeyi/oynamayı da sınırlar.

QUOTAS: dict[str, tuple[int, int, str]] = {
    # eylem: (azami, pencere saniye, mesaj)
    "create": (30, 86_400, "Günlük nokta ekleme sınırına ulaştınız. Yarın tekrar deneyin."),
    "review": (30, 86_400, "Günlük değerlendirme sınırına ulaştınız."),
    "status": (60, 3_600, "Çok sık durum güncellemesi gönderdiniz. Biraz sonra tekrar deneyin."),
    "report": (20, 86_400, "Günlük bildirim sınırına ulaştınız."),
    "confirm": (100, 86_400, "Günlük teyit sınırına ulaştınız."),
}
# Aynı kullanıcı aynı noktanın durumunu kısa sürede art arda değiştiremez (ör. açık/kapalı oynatma).
STATUS_PER_POINT = (3, 600, "Bu noktanın durumunu kısa süre içinde birkaç kez güncellediniz. 10 dakika sonra tekrar deneyin.")


class ServicePointRateLimitError(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


async def enforce_quota(action: str, user: User, *, point_id: uuid.UUID | None = None) -> None:
    """Kotayı ayrı bir oturumda sayar - asıl işlemin transaction'ını commit etmez."""
    if not settings.SERVICE_POINT_QUOTAS_ENABLED:
        return
    from app.core.database import AsyncSessionLocal
    from app.core.request_limits import allow_request

    checks = [(f"sp:{action}:{user.id}", *QUOTAS[action])]
    if action == "status" and point_id is not None:
        checks.append((f"sp:status:{user.id}:{point_id}", *STATUS_PER_POINT))
    async with AsyncSessionLocal() as quota_db:
        for identity, maximum, seconds, message in checks:
            allowed, retry_after = await allow_request(quota_db, identity, maximum, seconds=seconds)
            if not allowed:
                raise ServicePointRateLimitError(message, retry_after)
