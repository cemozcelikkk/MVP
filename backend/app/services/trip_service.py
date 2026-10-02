import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.request import Request, urlopen

from fastapi import HTTPException
from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.models.account_token import PlaceCache
from app.models.spot import Spot
from app.schemas.spot import SpotSummary


def query_route(coordinates):
    points = ";".join(f"{lon},{lat}" for lon, lat in coordinates)
    url = (
        settings.ROUTING_URL.rstrip("/")
        + "/"
        + points
        + "?overview=full&geometries=geojson&steps=false"
    )
    with urlopen(Request(url, headers={"User-Agent": "KaravanTR/0.1"}), timeout=15) as response:
        result = json.load(response)
    if result.get("code") != "Ok" or not result.get("routes"):
        raise ValueError("No route")
    route = result["routes"][0]
    if (
        route["geometry"].get("type") != "LineString"
        or len(route["geometry"].get("coordinates", [])) < 2
    ):
        raise ValueError("Invalid route geometry")
    return {
        "geometry": route["geometry"],
        "distance_km": round(route["distance"] / 1000, 1),
        "duration_minutes": round(route["duration"] / 60),
    }


async def build_trip_route(db, detail, corridor_km):
    if not 2 <= len(detail.items) <= 10:
        raise HTTPException(422, "Rota için 2 ile 10 durak gerekli.")
    coordinates = [
        (
            item.spot.entry_longitude
            if item.spot.entry_longitude is not None
            else item.spot.longitude,
            item.spot.entry_latitude
            if item.spot.entry_latitude is not None
            else item.spot.latitude,
        )
        for item in detail.items
    ]
    key = "route:" + hashlib.sha256(json.dumps(coordinates).encode()).hexdigest()
    cached = await db.get(PlaceCache, key)
    if cached and cached.updated_at > datetime.now(UTC) - timedelta(hours=6):
        route = cached.results[0]
    else:
        try:
            route = await asyncio.to_thread(query_route, coordinates)
        except Exception:
            raise HTTPException(
                503, "Rota servisine ulaşılamadı. Duraklarınızı Google Haritalar'da açabilirsiniz."
            )
        await db.execute(
            insert(PlaceCache)
            .values(query=key, results=[route])
            .on_conflict_do_update(
                index_elements=[PlaceCache.query],
                set_={"results": [route], "updated_at": func.now()},
            )
        )
    line = cast(
        func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(route["geometry"])), 4326), Geography
    )
    geom = cast(Spot.coordinates, Geography)
    rows = (
        await db.scalars(
            select(Spot)
            .where(
                Spot.deleted_at.is_(None),
                Spot.id.not_in([item.spot_id for item in detail.items]),
                func.ST_DWithin(geom, line, corridor_km * 1000),
            )
            .order_by(func.ST_Distance(geom, line), Spot.id)
            .limit(30)
        )
    ).all()
    await db.commit()
    return {
        **route,
        "nearby_spots": [SpotSummary.model_validate(spot).model_dump(mode="json") for spot in rows],
        "notice": "Standart araç rotasıdır; karavanın yükseklik, ağırlık ve yol kısıtlarını değerlendirmez.",
    }
