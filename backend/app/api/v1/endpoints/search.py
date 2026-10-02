import asyncio
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geography
from sqlalchemy import cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.request_limits import allow_request
from app.models.account_token import PlaceCache
from app.models.spot import Spot
from app.schemas.geojson import FeatureCollection
from app.schemas.spot import SpotProperties, spot_to_feature
from app.services.spot_service import _SPOT_RELATIONSHIP_OPTIONS

router = APIRouter(tags=["search"])


@router.get("/spots/search", response_model=FeatureCollection[SpotProperties])
async def spot_search(
    q: str = Query("", max_length=100),
    latitude: float | None = Query(None, ge=-90, le=90),
    longitude: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(25, gt=0, le=200),
    db: AsyncSession = Depends(get_db),
):
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, "Enlem ve boylam birlikte girilmeli.")
    if not q.strip() and latitude is None:
        raise HTTPException(422, "Arama metni veya konum gerekli.")
    stmt = select(Spot).where(Spot.deleted_at.is_(None)).options(*_SPOT_RELATIONSHIP_OPTIONS)
    if q.strip():
        # Escape wildcard characters; user text is a literal substring.
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            or_(Spot.title.ilike(term, escape="\\"), Spot.description.ilike(term, escape="\\"))
        )
    if latitude is not None:
        origin = cast(func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326), Geography)
        geom = cast(Spot.coordinates, Geography)
        stmt = stmt.where(func.ST_DWithin(geom, origin, radius_km * 1000)).order_by(
            func.ST_Distance(geom, origin), Spot.id
        )
    else:
        stmt = stmt.order_by(Spot.title, Spot.id)
    rows = (await db.scalars(stmt.limit(50))).all()
    return FeatureCollection[SpotProperties](features=[spot_to_feature(row) for row in rows])


def query_places(query):
    params = urlencode(
        {"q": query, "format": "jsonv2", "countrycodes": "tr", "limit": 5, "accept-language": "tr"}
    )
    req = Request(
        settings.GEOCODER_URL + "?" + params, headers={"User-Agent": settings.GEOCODER_USER_AGENT}
    )
    with urlopen(req, timeout=10) as response:
        rows = json.load(response)
    return [
        {
            "label": row["display_name"],
            "latitude": float(row["lat"]),
            "longitude": float(row["lon"]),
            "attribution": "© OpenStreetMap contributors",
        }
        for row in rows
    ]


@router.get("/places/search")
async def place_search(
    q: str = Query(min_length=2, max_length=100), db: AsyncSession = Depends(get_db)
):
    query = q.strip().casefold()
    # Advisory lock serializes cache misses across workers, no autocomplete traffic.
    await db.execute(text("SELECT pg_advisory_xact_lock(734821)"))
    row = await db.get(PlaceCache, query)
    if row and row.updated_at > datetime.now(UTC) - timedelta(days=7):
        return row.results
    # Shared provider throttle; use a separate transaction so the advisory lock is retained.
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as quota_db:
        allowed, retry = await allow_request(quota_db, "geocoder-global", 1, seconds=1)
    if not allowed:
        raise HTTPException(
            429, "Yer araması için bir saniye bekleyin.", headers={"Retry-After": str(retry)}
        )
    try:
        results = await asyncio.to_thread(query_places, q.strip())
    except Exception:
        raise HTTPException(503, "Yer arama servisine ulaşılamadı. Nokta adıyla arayabilirsiniz.")
    await db.execute(
        insert(PlaceCache)
        .values(query=query, results=results)
        .on_conflict_do_update(
            index_elements=[PlaceCache.query], set_={"results": results, "updated_at": func.now()}
        )
    )
    await db.commit()
    return results
