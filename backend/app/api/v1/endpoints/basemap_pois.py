"""`/api/v1/basemap-pois` - harita altlığı için düşük zoom (11-13) önemli OSM noktaları.

KaravanTR kayıtları DEĞİLDİR; `scripts/import_basemap_pois.py` ile periyodik
doldurulan `basemap_pois` tablosundan okunur (bkz. app/models/basemap_poi.py).
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.basemap_poi import BASEMAP_POI_CATEGORIES, BasemapPoi

router = APIRouter(prefix="/basemap-pois", tags=["basemap"])

DEFAULT_LIMIT = 1500
MAX_LIMIT = 3000
# Veri haftalık yenilenir; tarayıcı/CDN aynı bbox'ı bir saat önbellekte tutabilir.
CACHE_CONTROL = "public, max-age=3600"

BasemapPoiCategory = Literal["hospital", "fuel", "police", "clinic", "pharmacy"]


class BasemapPoiProperties(BaseModel):
    osm_id: str
    category: BasemapPoiCategory
    name: str | None


class BasemapPoiGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # [boylam, enlem]


class BasemapPoiFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: BasemapPoiGeometry
    properties: BasemapPoiProperties


class BasemapPoiCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[BasemapPoiFeature]


@router.get("", response_model=BasemapPoiCollection)
async def list_basemap_pois(
    response: Response,
    min_lat: Annotated[float, Query(ge=-90, le=90)],
    max_lat: Annotated[float, Query(ge=-90, le=90)],
    min_lng: Annotated[float, Query(ge=-180, le=180)],
    max_lng: Annotated[float, Query(ge=-180, le=180)],
    category: Annotated[
        list[str] | None,
        Query(description="Virgülle veya tekrarlanarak: hospital, fuel, police, clinic, pharmacy. Verilmezse hepsi."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    db: AsyncSession = Depends(get_db),
) -> BasemapPoiCollection:
    """
    Görünür alandaki önemli OSM noktalarını hafif bir GeoJSON olarak döndürür.

    Limit aşılırsa önem sırasına göre (hastane > akaryakıt > polis > sağlık
    ocağı > eczane) kesilir - yoğun şehirlerde eczaneler hastaneleri dışarıda
    bırakmaz. Ağır ORM nesneleri kurulmaz; yalnızca gereken sütunlar okunur.
    """
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz bounding box.")

    categories = list(BASEMAP_POI_CATEGORIES)
    if category:
        requested = {part.strip().lower() for item in category for part in item.split(",") if part.strip()}
        unknown = requested - set(BASEMAP_POI_CATEGORIES)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Geçersiz kategori: {', '.join(sorted(unknown))}. Geçerli: {', '.join(BASEMAP_POI_CATEGORIES)}",
            )
        categories = [c for c in BASEMAP_POI_CATEGORIES if c in requested]

    envelope = func.ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)
    priority = func.array_position(list(BASEMAP_POI_CATEGORIES), BasemapPoi.category)
    stmt = (
        select(
            BasemapPoi.osm_id,
            BasemapPoi.category,
            BasemapPoi.name,
            func.ST_X(BasemapPoi.coordinates),
            func.ST_Y(BasemapPoi.coordinates),
        )
        .where(func.ST_Intersects(BasemapPoi.coordinates, envelope))
        .where(BasemapPoi.category.in_(categories))
        .order_by(priority)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    response.headers["Cache-Control"] = CACHE_CONTROL
    return BasemapPoiCollection(
        features=[
            BasemapPoiFeature(
                geometry=BasemapPoiGeometry(coordinates=(lng, lat)),
                properties=BasemapPoiProperties(osm_id=osm_id, category=cat, name=name),
            )
            for osm_id, cat, name, lng, lat in rows
        ]
    )
