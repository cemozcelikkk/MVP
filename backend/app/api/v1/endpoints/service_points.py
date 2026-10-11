"""`/api/v1/service-points` - restoran, sağlık, WC ve duş gibi çevresel hizmet noktaları.

Kamp/karavan noktalarından (`/spots`) ayrı bir kaynaktır - bkz. app/models/service_point.py.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_moderator
from app.core.config import settings
from app.core.database import get_db
from app.models.enums import SERVICE_POINT_GROUP_CATEGORIES, ServicePointCategory, ServicePointGroup
from app.models.user import User
from app.schemas.geojson import Feature
from app.schemas.service_point import (
    OSM_ATTRIBUTION,
    CategoryReviewDecision,
    CategoryReviewItem,
    ServicePointVerifyUpdate,
    NameSuggestion,
    ServicePointCollection,
    ServicePointCreate,
    ServicePointProperties,
    ServicePointReportCreate,
    ServicePointReportQueueItem,
    ServicePointReportRead,
    ServicePointReportResolution,
    ServicePointReviewCreate,
    ServicePointReviewRead,
    ServicePointReviewUpdate,
    ServicePointStatusCreate,
    ServicePointStatusUpdateRead,
    ServicePointUpdate,
    point_view_to_feature,
    service_point_to_feature,
)
from app.services import service_point_service as svc
from app.services import category_migration
from app.services.service_point_service import (
    ServicePointConflictError,
    ServicePointNotFoundError,
    ServicePointPermissionError,
    ServicePointRateLimitError,
    ServicePointRuleError,
    enforce_quota,
)

router = APIRouter(tags=["service points"])

_NOT_FOUND = "Nokta bulunamadı."


def _conflict_response(exc: ServicePointConflictError) -> JSONResponse:
    """409 + (varsa) mevcut noktanın id'si - istemci "mevcut noktayı aç" sunabilsin."""
    body: dict = {"detail": str(exc)}
    if exc.existing_id is not None:
        body["existing_id"] = str(exc.existing_id)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ServicePointNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    if isinstance(exc, ServicePointPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok.")
    if isinstance(exc, ServicePointConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ServicePointRuleError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ServicePointRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    raise exc


_DOMAIN_ERRORS = (
    ServicePointRateLimitError,
    ServicePointNotFoundError,
    ServicePointPermissionError,
    ServicePointConflictError,
    ServicePointRuleError,
)


def _parse_categories(
    raw_categories: list[str] | None, raw_groups: list[str] | None
) -> list[ServicePointCategory] | None:
    """`category` ve `group` (virgülle veya tekrarlanarak) birleşimi; ikisi de yoksa None (hepsi)."""
    selected: list[ServicePointCategory] = []
    try:
        for item in raw_categories or []:
            selected += [ServicePointCategory(p.strip().upper()) for p in item.split(",") if p.strip()]
        for item in raw_groups or []:
            for part in (p.strip().lower() for p in item.split(",") if p.strip()):
                selected += SERVICE_POINT_GROUP_CATEGORIES[ServicePointGroup(part)]
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                "Geçersiz kategori/grup. Kategoriler: "
                + ", ".join(c.value for c in ServicePointCategory)
                + "; gruplar: "
                + ", ".join(g.value for g in ServicePointGroup)
            ),
        )
    return list(dict.fromkeys(selected)) or None


def _collection(rows, external_status) -> ServicePointCollection:
    features = [point_view_to_feature(view, distance) for view, distance in rows]
    has_osm = any(f.properties.source.value == "OVERPASS_OSM" for f in features)
    return ServicePointCollection(
        features=features,
        external_status=external_status.value,
        attribution=OSM_ATTRIBUTION if has_osm else None,
    )


@router.get("/service-points", response_model=ServicePointCollection)
async def list_service_points(
    min_lat: Annotated[float, Query(ge=-90, le=90)],
    max_lat: Annotated[float, Query(ge=-90, le=90)],
    min_lng: Annotated[float, Query(ge=-180, le=180)],
    max_lng: Annotated[float, Query(ge=-180, le=180)],
    category: Annotated[list[str] | None, Query(description="ör. WC,SHOWER")] = None,
    group: Annotated[list[str] | None, Query(description="food, health, basic")] = None,
    limit: Annotated[int, Query(ge=1, le=settings.SPOTS_BBOX_MAX_LIMIT)] = settings.SPOTS_BBOX_DEFAULT_LIMIT,
    db: AsyncSession = Depends(get_db),
) -> ServicePointCollection:
    """Görünür alandaki hizmet noktaları (GeoJSON): KaravanTR kayıtları + OpenStreetMap
    önbelleği, aynı yerin ikinci kopyası ayıklanmış. `category` ve `group` birlikte
    verilirse birleşimi alınır. `external_status` harici kaynağın durumunu bildirir;
    kaynak erişilemese de KaravanTR kayıtları her zaman döner."""
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz bounding box.")
    points, external_status = await svc.list_merged(
        db,
        min_lon=min_lng,
        min_lat=min_lat,
        max_lon=max_lng,
        max_lat=max_lat,
        categories=_parse_categories(category, group),
        limit=limit,
    )
    return _collection([(p, None) for p in points], external_status)


@router.get("/service-points/nearby", response_model=ServicePointCollection)
async def nearby_service_points(
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[int, Query(ge=100, le=20_000, description="Yarıçap (metre)")] = 5000,
    category: Annotated[list[str] | None, Query(description="ör. WC,SHOWER")] = None,
    group: Annotated[list[str] | None, Query(description="food, health, basic")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    db: AsyncSession = Depends(get_db),
) -> ServicePointCollection:
    """"Yakınımdakiler": bir merkezin (kullanıcı konumu veya seçili kamp noktası) çevresindeki
    hizmetler, yakından uzağa sıralı; her özellikte `distance_m` bulunur."""
    rows, external_status = await svc.list_nearby(
        db,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        categories=_parse_categories(category, group),
        limit=limit,
    )
    return _collection(rows, external_status)


@router.get("/service-points/name-suggestion", response_model=NameSuggestion)
async def name_suggestion(
    category: ServicePointCategory,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    db: AsyncSession = Depends(get_db),
) -> NameSuggestion:
    """Sağlık kuruluşu eklerken: seçilen konumun yakınındaki OSM kaydının adı (yoksa `name: null`)."""
    return await svc.suggest_name(db, category=category, latitude=latitude, longitude=longitude)


@router.get("/service-points/{point_id}", response_model=Feature[ServicePointProperties])
async def read_service_point(point_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return point_view_to_feature(await svc.get_point_view(db, point_id))
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.post("/service-points", response_model=Feature[ServicePointProperties], status_code=status.HTTP_201_CREATED)
async def create_service_point(
    payload: ServicePointCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await enforce_quota("create", user)
        return service_point_to_feature(await svc.create_point(db, data=payload, user=user))
    except ServicePointConflictError as exc:
        return _conflict_response(exc)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.patch("/service-points/{point_id}", response_model=Feature[ServicePointProperties])
async def update_service_point(
    point_id: uuid.UUID,
    payload: ServicePointUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return service_point_to_feature(await svc.update_point(db, point_id=point_id, data=payload, user=user))
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.delete("/service-points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service_point(
    point_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await svc.delete_point(db, point_id=point_id, user=user)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


# --- Yeme & İçme değerlendirmeleri ---------------------------------------------


@router.get("/service-points/{point_id}/reviews", response_model=list[ServicePointReviewRead])
async def list_service_point_reviews(
    point_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.list_reviews(db, point_id=point_id, limit=limit, offset=offset)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.get("/service-points/{point_id}/reviews/me", response_model=ServicePointReviewRead | None)
async def my_service_point_review(
    point_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await svc.get_my_review(db, point_id=point_id, user=user)


@router.post(
    "/service-points/{point_id}/reviews", response_model=ServicePointReviewRead, status_code=status.HTTP_201_CREATED
)
async def create_service_point_review(
    point_id: uuid.UUID,
    payload: ServicePointReviewCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await enforce_quota("review", user)
        return await svc.add_review(db, point_id=point_id, user=user, data=payload)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.patch("/service-points/{point_id}/reviews/{review_id}", response_model=ServicePointReviewRead)
async def update_service_point_review(
    point_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: ServicePointReviewUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.update_review(db, point_id=point_id, review_id=review_id, user=user, data=payload)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.delete("/service-points/{point_id}/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service_point_review(
    point_id: uuid.UUID,
    review_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await svc.delete_review(db, point_id=point_id, review_id=review_id, user=user)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


# --- WC / duş durum bilgisi -----------------------------------------------------


@router.post("/service-points/{point_id}/status", response_model=Feature[ServicePointProperties])
async def update_service_point_status(
    point_id: uuid.UUID,
    payload: ServicePointStatusCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await enforce_quota("status", user, point_id=point_id)
        return service_point_to_feature(await svc.add_status_update(db, point_id=point_id, user=user, data=payload))
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.get("/service-points/{point_id}/status-history", response_model=list[ServicePointStatusUpdateRead])
async def service_point_status_history(point_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await svc.list_status_updates(db, point_id=point_id)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


# --- Sorun bildirimi + moderasyon ------------------------------------------------


@router.post(
    "/service-points/{point_id}/reports", response_model=ServicePointReportRead, status_code=status.HTTP_201_CREATED
)
async def report_service_point(
    point_id: uuid.UUID,
    payload: ServicePointReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await enforce_quota("report", user)
        return await svc.create_report(db, point_id=point_id, user=user, data=payload)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.get("/moderation/service-point-reports", response_model=list[ServicePointReportQueueItem])
async def service_point_report_queue(
    state: Annotated[str, Query(pattern="^(pending|resolved|rejected)$")] = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
):
    rows = await svc.report_queue(db, state=state, limit=limit, offset=offset)
    return [
        ServicePointReportQueueItem(
            **ServicePointReportRead.model_validate(report).model_dump(),
            point=service_point_to_feature(point).properties,
        )
        for report, point in rows
    ]


@router.post("/moderation/service-point-reports/{report_id}/resolve", response_model=ServicePointReportRead)
async def resolve_service_point_report(
    report_id: uuid.UUID,
    payload: ServicePointReportResolution,
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.resolve_report(db, report_id=report_id, moderator=user, data=payload)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


# --- Doğrulama --------------------------------------------------------------------


@router.post("/service-points/{point_id}/confirm", response_model=Feature[ServicePointProperties])
async def confirm_service_point(
    point_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """"Bu yer hâlâ burada / hizmet veriyor" - tüm türlerde (sağlık dahil). Kullanıcı başına
    nokta başına 24 saatte bir; harici (OSM) noktada önce KaravanTR kaydı oluşturulur."""
    try:
        await enforce_quota("confirm", user)
        return service_point_to_feature(await svc.confirm_point(db, point_id=point_id, user=user))
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


@router.patch("/service-points/{point_id}/verify", response_model=Feature[ServicePointProperties])
async def verify_service_point(
    point_id: uuid.UUID,
    payload: ServicePointVerifyUpdate,
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
):
    try:
        return service_point_to_feature(await svc.set_verified(db, point_id=point_id, is_verified=payload.is_verified))
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc)


# --- Kategori geçişi: belirsiz eski kayıtlar (moderatör) ------------------------------


@router.get("/moderation/category-review", response_model=list[CategoryReviewItem])
async def category_review_queue(user: User = Depends(require_moderator), db: AsyncSession = Depends(get_db)):
    """Taşıma sırasında kamp verisi taşıdığı için OTOMATİK taşınmayan restoran/sağlık kayıtları."""
    items = []
    for spot in await category_migration.pending_reviews(db):
        reasons = [r for r in str(spot.extra_amenities.get("category_review_reasons") or "").split(",") if r]
        items.append(
            CategoryReviewItem(
                spot_id=spot.id,
                title=spot.title,
                category=spot.category.value,
                latitude=spot.latitude,
                longitude=spot.longitude,
                reasons=reasons,
                reason_labels=[category_migration.REASON_LABELS.get(r, r) for r in reasons],
                review_count=spot.review_count,
                created_at=spot.created_at,
            )
        )
    return items


@router.post("/moderation/category-review/{spot_id}")
async def resolve_category_review(
    spot_id: uuid.UUID,
    payload: CategoryReviewDecision,
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await category_migration.resolve_category_review(
            db, spot_id=spot_id, action=payload.action, moderator=user
        )
    except category_migration.CategoryReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {k: (str(v) if v is not None else None) for k, v in result.items()}
