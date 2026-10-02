"""
`spots` çekirdek şemaları.

Buradaki en kritik nokta geometri dönüşümüdür: ORM tarafında
`Spot.coordinates` bir GeoAlchemy2 WKBElement'tir; API'de ise düz
`Coordinates(latitude, longitude)` veya GeoJSON `PointGeometry` olarak
görünür. `SpotRead._extract_orm_geometry` bu dönüşümü model_validate
sırasında şeffaf biçimde yapar, böylece router/servis katmanı manuel
dönüşüm yazmak zorunda kalmaz.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import SpotCategory
from app.schemas.common import Coordinates
from app.schemas.compatibility import SpotCompatibilitySummary
from app.schemas.dynamic_status import DynamicStatusRead
from app.schemas.geojson import Feature, PointGeometry
from app.schemas.live_report import SpotLiveSummary
from app.schemas.review import SpotDimensionRatings
from app.schemas.spot_amenities import SpotAmenitiesCreate, SpotAmenitiesRead, SpotAmenitiesUpdate
from app.schemas.spot_passability import SpotPassabilityCreate, SpotPassabilityRead
from app.schemas.spot_photo import SpotPhotoRead
from app.utils.geo import wkb_to_lonlat


class SpotBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: SpotCategory
    altitude: float | None = Field(default=None, description="Metre cinsinden rakım")

    overnight_status: Literal["allowed", "not_allowed", "unknown"] = "unknown"
    max_stay_nights: int | None = Field(default=None, ge=1, le=365)
    rule_description: str | None = Field(default=None, max_length=2000)
    rule_source: str | None = Field(default=None, max_length=300)
    rule_checked_on: date | None = None
    private_property_permission: Literal["required", "not_required", "unknown"] = "unknown"
    entry_latitude: float | None = Field(default=None, ge=-90, le=90)
    entry_longitude: float | None = Field(default=None, ge=-180, le=180)
    approach_description: str | None = Field(default=None, max_length=2000)
    access_season: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_entry(self):
        if (self.entry_latitude is None) != (self.entry_longitude is None):
            raise ValueError("Giriş enlemi ve boylamı birlikte girilmeli.")
        if self.rule_checked_on and self.rule_checked_on > date.today():
            raise ValueError("Kural kontrol tarihi gelecekte olamaz.")
        return self


class SpotCreate(SpotBase):
    """POST /spots istek gövdesi: konum + ilişkili alt kayıtlar birlikte gönderilir."""

    # Sadece MODERATOR/ADMIN oluşturuyorsa dikkate alınır; sıradan bir
    # kullanıcı True gönderse bile spot_service.create_spot bunu False'a
    # zorlar (bkz. o fonksiyonun docstring'i).
    is_verified: bool = Field(
        default=False,
        description="Yalnızca moderatör/admin isteklerinde True olarak işlenir.",
    )
    coordinates: Coordinates
    passability: SpotPassabilityCreate
    amenities: SpotAmenitiesCreate


class SpotVerifyUpdate(BaseModel):
    """PATCH /spots/{id}/verify istek gövdesi (sadece moderatör/admin)."""

    is_verified: bool


class SpotUpdate(BaseModel):
    """Partial content update. Explicit null clears nullable fields.

    Coordinates can only be corrected by moderators/admins (service enforced).
    Entry coordinates must be supplied together. Omitted fields are preserved.
    """

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: SpotCategory | None = None
    altitude: float | None = None
    passability: SpotPassabilityCreate | None = None
    amenities: SpotAmenitiesUpdate | None = None
    coordinates: Coordinates | None = None
    overnight_status: Literal["allowed", "not_allowed", "unknown"] | None = None
    max_stay_nights: int | None = Field(default=None, ge=1, le=365)
    rule_description: str | None = Field(default=None, max_length=2000)
    rule_source: str | None = Field(default=None, max_length=300)
    rule_checked_on: date | None = None
    private_property_permission: Literal["required", "not_required", "unknown"] | None = None
    entry_latitude: float | None = Field(default=None, ge=-90, le=90)
    entry_longitude: float | None = Field(default=None, ge=-180, le=180)
    approach_description: str | None = Field(default=None, max_length=2000)
    access_season: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_entry(self):
        if ("entry_latitude" in self.model_fields_set) != (
            "entry_longitude" in self.model_fields_set
        ):
            raise ValueError("Giriş enlemi ve boylamı birlikte gönderilmeli.")
        if (self.entry_latitude is None) != (self.entry_longitude is None):
            raise ValueError("Giriş enlemi ve boylamı birlikte girilmeli.")
        if self.rule_checked_on and self.rule_checked_on > date.today():
            raise ValueError("Kural kontrol tarihi gelecekte olamaz.")
        return self


def _orm_to_dict_with_lonlat(spot: Any) -> dict:
    """Bir Spot ORM nesnesini, WKBElement'i lat/lon'a çevirerek dict'e indirger."""
    longitude, latitude = wkb_to_lonlat(spot.coordinates)
    return {
        "id": spot.id,
        "title": spot.title,
        "description": spot.description,
        "category": spot.category,
        "altitude": spot.altitude,
        "overnight_status": spot.overnight_status,
        "max_stay_nights": spot.max_stay_nights,
        "rule_description": spot.rule_description,
        "rule_source": spot.rule_source,
        "rule_checked_on": spot.rule_checked_on,
        "private_property_permission": spot.private_property_permission,
        "entry_latitude": spot.entry_latitude,
        "entry_longitude": spot.entry_longitude,
        "approach_description": spot.approach_description,
        "access_season": spot.access_season,
        "is_verified": spot.is_verified,
        "created_by": spot.created_by,
        "created_at": spot.created_at,
        "updated_at": spot.updated_at,
        "latitude": latitude,
        "longitude": longitude,
        "passability": spot.passability,
        "amenities": spot.amenities,
        # dynamic_statuses, model'de reported_at DESC sıralı geldiği için ilk eleman en güncelidir.
        "latest_status": spot.dynamic_statuses[0] if spot.dynamic_statuses else None,
        # Hafif aktif canlı durum özeti - `dynamic_statuses` zaten (tek sorguyla) yüklü olduğu için
        # EK SORGU YOK: bbox'ta pin başına ayrı çağrı/N+1 oluşmaz, geçmiş bbox'a HİÇ girmez.
        "live_status": SpotLiveSummary.from_statuses(spot.dynamic_statuses),
        # Denormalize edilmiş yorum özeti; review_service.add_review() tarafından
        # her yeni yorumda yeniden hesaplanır (bkz. app/models/spot.py).
        "average_rating": spot.average_rating,
        "review_count": spot.review_count,
        "photos": spot.photos,
    }


class SpotRead(SpotBase):
    """Standart (düz) JSON gösterimi - mobil istemcinin SQLite'a yazacağı satır formatına yakın."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    latitude: float
    longitude: float
    is_verified: bool
    # Sahiplik kontrolü (düzenle/sil butonlarının görünürlüğü) için -
    # auth eklenmeden önce oluşturulmuş seed verisinde NULL olabilir.
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    passability: SpotPassabilityRead | None = None
    amenities: SpotAmenitiesRead | None = None
    latest_status: DynamicStatusRead | None = None
    live_status: SpotLiveSummary | None = None
    average_rating: float | None = None
    review_count: int = 0
    photos: list[SpotPhotoRead] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _extract_orm_geometry(cls, data: Any) -> Any:
        # Zaten bir dict ise (örn. mobil senkron payload'ından okunuyorsa)
        # dokunmadan geçir; sadece ham ORM nesnesi geldiğinde dönüştür.
        if isinstance(data, dict):
            return data
        return _orm_to_dict_with_lonlat(data)


class SpotProperties(SpotBase):
    """GeoJSON Feature.properties gövdesi (geometry ayrı taşındığı için lat/lon içermez)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_verified: bool
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    passability: SpotPassabilityRead | None = None
    amenities: SpotAmenitiesRead | None = None
    latest_status: DynamicStatusRead | None = None
    live_status: SpotLiveSummary | None = None
    average_rating: float | None = None
    review_count: int = 0
    photos: list[SpotPhotoRead] = Field(default_factory=list)
    # SADECE `GET /spots/bbox?with_compatibility=true` (kimliği doğrulanmış +
    # aktif araç profili olan kullanıcı) doldurur - bkz. `spots.py::read_spots_in_bbox`.
    # Diğer tüm durumlarda (varsayılan) None - mevcut yanıt şekli/performansı bozulmaz.
    compatibility: SpotCompatibilitySummary | None = None
    # SADECE `GET /spots/{id}` (tekil detay) doldurur - bkz.
    # `spots.py::read_spot`. bbox/liste uçları BUNU HİÇ hesaplamaz (görev
    # tanımı: "toplu harita bbox sorgusunu yavaşlatma").
    dimension_ratings: SpotDimensionRatings | None = None


class SpotSummary(SpotBase):
    """
    Favoriler/liste görünümleri için HAFİF spot özeti - `SpotRead`'in
    aksine passability/amenities/photos/latest_status içermez, bu yüzden
    onu üreten sorgu hiçbir `selectinload` gerektirmez (sadece düz
    `select(Spot)`). Bir seyahat listesi kartında görülmesi yeterli
    alanlar: kimlik, konum, kategori, doğrulama ve puan özeti.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    latitude: float
    longitude: float
    is_verified: bool
    average_rating: float | None = None
    review_count: int = 0

    @model_validator(mode="before")
    @classmethod
    def _extract_orm_geometry(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        longitude, latitude = wkb_to_lonlat(data.coordinates)
        return {
            "id": data.id,
            "title": data.title,
            "description": data.description,
            "category": data.category,
            "altitude": data.altitude,
            "overnight_status": data.overnight_status,
            "max_stay_nights": data.max_stay_nights,
            "rule_description": data.rule_description,
            "rule_source": data.rule_source,
            "rule_checked_on": data.rule_checked_on,
            "private_property_permission": data.private_property_permission,
            "entry_latitude": data.entry_latitude,
            "entry_longitude": data.entry_longitude,
            "approach_description": data.approach_description,
            "access_season": data.access_season,
            "is_verified": data.is_verified,
            "average_rating": data.average_rating,
            "review_count": data.review_count,
            "latitude": latitude,
            "longitude": longitude,
        }


def spot_to_feature(
    spot: Any,
    *,
    compatibility: SpotCompatibilitySummary | None = None,
    dimension_ratings: SpotDimensionRatings | None = None,
) -> Feature[SpotProperties]:
    """
    Bir Spot ORM nesnesini GeoJSON Feature'a çevirir (bbox/list endpoint'leri için).

    `compatibility` ve `dimension_ratings` opsiyoneldir ve SIRASIYLA sadece
    `read_spots_in_bbox`'ın `with_compatibility=true` dalından ve
    `read_spot` (tekil detay) endpoint'inden geçirilir - diğer tüm
    çağıranlar (create/update/verify) hiçbir değişiklik yapmadan eskisi
    gibi çalışmaya devam eder (varsayılan `None`).
    """
    longitude, latitude = wkb_to_lonlat(spot.coordinates)
    properties = SpotProperties.model_validate(_orm_to_dict_with_lonlat(spot))
    if compatibility is not None:
        properties.compatibility = compatibility
    if dimension_ratings is not None:
        properties.dimension_ratings = dimension_ratings
    return Feature[SpotProperties](
        id=spot.id,
        geometry=PointGeometry(coordinates=(longitude, latitude)),
        properties=properties,
    )
