"""`/api/v1/service-points` istek/yanıt şemaları - bkz. app/models/service_point.py."""
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.enums import (
    ServicePointCategory,
    ServicePointGroup,
    SpotSource,
    service_point_group,
)
from app.schemas.common import Coordinates
from app.schemas.geojson import Feature, PointGeometry

FeeStatus = Literal["free", "paid", "unknown"]
AvailabilityStatus = Literal["available", "unavailable", "unknown"]
ReportReason = Literal["wrong_location", "closed", "duplicate", "wrong_info", "other"]

OptionalName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None


def _blank_to_none(value: str | None) -> str | None:
    return value or None


def _require_name_for_food(category: ServicePointCategory | None, name: str | None) -> None:
    if category is not None and service_point_group(category) is ServicePointGroup.FOOD and not name:
        raise ValueError("Restoran eklerken işletme adı zorunludur.")


class ServicePointCreate(BaseModel):
    """Kısa ekleme akışı: tür + konum (+ restoranlarda ad). WC/duşta ilk durum opsiyonel."""

    category: ServicePointCategory
    coordinates: Coordinates
    name: OptionalName = None
    fee_status: FeeStatus | None = None
    availability_status: AvailabilityStatus | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ServicePointCreate":
        self.name = _blank_to_none(self.name)
        _require_name_for_food(self.category, self.name)
        is_basic = service_point_group(self.category) is ServicePointGroup.BASIC
        if not is_basic and (self.fee_status is not None or self.availability_status is not None):
            raise ValueError("Ücret/kullanılabilirlik bilgisi yalnızca WC ve duş için girilebilir.")
        return self


class ServicePointUpdate(BaseModel):
    """Sahip veya moderatör: ad ve aynı grup içinde tür. Konumu yalnızca moderatör değiştirir."""

    name: OptionalName = None
    category: ServicePointCategory | None = None
    coordinates: Coordinates | None = None


class ServicePointProperties(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: ServicePointCategory
    group: ServicePointGroup
    name: str | None
    latitude: float
    longitude: float
    source: SpotSource
    # Karşılık gelen OpenStreetMap nesnesi ("node/123"), varsa.
    osm_id: str | None = None
    # true: yalnızca harici (OSM) veri - henüz hiçbir KaravanTR katkısı yok. İstemci bunu
    # "harita verisi, doğrulanmamış" olarak gösterir; açık/çalışıyor bilgisi VERMEZ.
    is_external: bool = False
    # Yalnızca `/service-points/nearby`: merkeze uzaklık (metre).
    distance_m: float | None = None
    extra: dict = Field(default_factory=dict)
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Yalnızca Yeme & İçme (diğerlerinde None/0).
    average_rating: float | None = None
    review_count: int = 0
    # Yalnızca WC/duş (diğerlerinde "unknown"/None).
    fee_status: FeeStatus = "unknown"
    availability_status: AvailabilityStatus = "unknown"
    status_checked_at: datetime | None = None
    # Doğrulama (tüm türler): moderatör onayı + "hâlâ burada" topluluk teyidi.
    is_verified: bool = False
    confirmation_count: int = 0
    last_confirmed_at: datetime | None = None


OSM_ATTRIBUTION = "© OpenStreetMap katkıcıları (ODbL)"


def point_view_to_feature(view, distance_m: float | None = None) -> Feature[ServicePointProperties]:
    """KaravanTR kaydı (`ServicePoint`) veya harici `ExternalPoint` -> GeoJSON Feature."""
    from app.services.service_point_service import ExternalPoint

    if isinstance(view, ExternalPoint):
        feature = external_to_feature(view)
    else:
        feature = service_point_to_feature(view)
    feature.properties.distance_m = round(distance_m, 1) if distance_m is not None else None
    return feature


def external_to_feature(point) -> Feature[ServicePointProperties]:
    from app.services.osm_source import BASIC_CATEGORIES, fee_status_from_tags

    seen = point.fetched_at or datetime.now(UTC)
    return Feature[ServicePointProperties](
        id=point.id,
        geometry=PointGeometry(coordinates=(point.longitude, point.latitude)),
        properties=ServicePointProperties(
            id=point.id,
            category=point.category,
            group=service_point_group(point.category),
            name=point.name,
            latitude=point.latitude,
            longitude=point.longitude,
            source=SpotSource.OVERPASS_OSM,
            osm_id=point.osm_id,
            is_external=True,
            extra={**point.tags, "osm_url": f"https://www.openstreetmap.org/{point.osm_id}"},
            created_at=seen,
            updated_at=seen,
            # OSM `fee` etiketi gösterilir ama saha doğrulaması sayılmaz (status_checked_at boş).
            fee_status=fee_status_from_tags(point.tags) if point.category in BASIC_CATEGORIES else "unknown",
        ),
    )


class ServicePointCollection(BaseModel):
    """FeatureCollection + harici kaynağın bu yanıttaki durumu (bkz. osm_source.ExternalStatus)."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature[ServicePointProperties]]
    external_status: Literal["ok", "partial", "unavailable", "too_wide", "disabled", "not_needed"]
    # Harici veri içeriyorsa gösterilmesi gereken atıf (ODbL).
    attribution: str | None = None


def service_point_to_feature(point) -> Feature[ServicePointProperties]:
    longitude, latitude = point.longitude, point.latitude
    return Feature[ServicePointProperties](
        id=point.id,
        geometry=PointGeometry(coordinates=(longitude, latitude)),
        properties=ServicePointProperties(
            id=point.id,
            category=point.category,
            group=service_point_group(point.category),
            name=point.name,
            latitude=latitude,
            longitude=longitude,
            source=point.source,
            osm_id=point.osm_id,
            extra=point.extra or {},
            created_by=point.created_by,
            created_at=point.created_at,
            updated_at=point.updated_at,
            average_rating=point.average_rating,
            review_count=point.review_count,
            fee_status=point.fee_status,
            availability_status=point.availability_status,
            status_checked_at=point.status_checked_at,
            is_verified=point.is_verified,
            confirmation_count=point.confirmation_count,
            last_confirmed_at=point.last_confirmed_at,
        ),
    )


class ServicePointReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ServicePointReviewUpdate(BaseModel):
    """PATCH: `None` = değiştirme. Yorumu silmek için boş metin gönderilir."""

    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ServicePointReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_point_id: uuid.UUID
    user_id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


class ServicePointStatusCreate(BaseModel):
    """WC/duş durum güncellemesi - en az bir alan. "unknown" da geçerli bir yanıttır
    ("baktım ama anlayamadım"), son doğrulama zamanını yine tazeler."""

    fee_status: FeeStatus | None = None
    availability_status: AvailabilityStatus | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "ServicePointStatusCreate":
        if self.fee_status is None and self.availability_status is None:
            raise ValueError("En az bir durum bilgisi gönderilmelidir.")
        return self


class ServicePointStatusUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fee_status: FeeStatus | None
    availability_status: AvailabilityStatus | None
    created_at: datetime


class ServicePointReportCreate(BaseModel):
    reason: ReportReason
    description: str | None = Field(default=None, max_length=1000)


class ServicePointReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_point_id: uuid.UUID
    reason: ReportReason
    description: str | None
    state: Literal["pending", "resolved", "rejected"]
    resolution_note: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class ServicePointReportQueueItem(ServicePointReportRead):
    """Moderatör kuyruğu satırı: bildirilen noktanın kısa özeti de taşınır."""

    point: ServicePointProperties


class ServicePointReportResolution(BaseModel):
    action: Literal["resolve", "reject"]
    # true: bildirim haklı ve nokta kaldırılmalı (kapanmış/mükerrer) -> soft-delete.
    remove_point: bool = False
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _remove_only_on_resolve(self) -> "ServicePointReportResolution":
        if self.remove_point and self.action != "resolve":
            raise ValueError("Nokta yalnızca bildirim onaylanırken kaldırılabilir.")
        return self


class NameSuggestion(BaseModel):
    """Seçilen konumun yakınındaki, harita verisinden (OSM) bilinen kuruluş adı."""

    name: str | None
    distance_m: float | None = None
    osm_id: str | None = None


class ServicePointVerifyUpdate(BaseModel):
    is_verified: bool


class CategoryReviewItem(BaseModel):
    """Taşıma sırasında belirsiz bulunup `spots`'ta bırakılan eski kayıt (bkz. category_migration)."""

    spot_id: uuid.UUID
    title: str
    category: str
    latitude: float
    longitude: float
    reasons: list[str]
    reason_labels: list[str]
    review_count: int
    created_at: datetime


class CategoryReviewDecision(BaseModel):
    action: Literal["keep_as_camping", "move_to_service", "keep_as_is"]
