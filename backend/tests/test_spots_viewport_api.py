"""`GET /api/v1/spots` - harita viewport (bbox) + kategori filtresi."""
import uuid

import pytest_asyncio
from sqlalchemy import delete

from app.models.enums import SpotCategory, SpotSource
from app.models.spot import Spot
from app.schemas.common import Coordinates
from app.schemas.spot import SpotCreate
from app.schemas.spot_amenities import SpotAmenitiesCreate
from app.schemas.spot_passability import SpotPassabilityCreate
from app.services.spot_service import create_spot
from app.utils.geo import lonlat_to_wkb

# Gerçek dev verisiyle çakışmaması için okyanusta, (0, 0) civarında küçük bir kutu.
BBOX = {"min_lat": 0.0, "max_lat": 1.0, "min_lng": 0.0, "max_lng": 1.0}
URL = "/api/v1/spots"


@pytest_asyncio.fixture
async def viewport_spots(db_session):
    created: dict[str, uuid.UUID] = {}
    rows = [
        ("camp", SpotCategory.CAMPING, 0.5, 0.5, {"water": True, "nearby_hospital_km": 2.5}),
        ("camp2", SpotCategory.CAMPING, 0.2, 0.8, {}),
        ("outside", SpotCategory.CAMPING, 1.5, 0.5, {}),
    ]
    for key, category, lat, lng, extra in rows:
        feature = await create_spot(
            db_session,
            data=SpotCreate(
                title=f"Viewport test {key}",
                category=category,
                coordinates=Coordinates(latitude=lat, longitude=lng),
                passability=SpotPassabilityCreate(road_type="asphalt"),
                amenities=SpotAmenitiesCreate(),
                extra_amenities=extra,
            ),
        )
        created[key] = feature.properties.id
    # Eski (yeni eklemeye kapalı) HOTEL_POOL kaydı: API ile oluşturulamaz ama haritada okunur kalır.
    pool = Spot(
        title="Viewport test pool", category=SpotCategory.HOTEL_POOL, source=SpotSource.USER_ADDED,
        coordinates=lonlat_to_wkb(0.4, 0.6), is_verified=False,
    )
    db_session.add(pool)
    await db_session.commit()
    created["pool"] = pool.id
    yield created
    await db_session.execute(delete(Spot).where(Spot.id.in_(created.values())))
    await db_session.commit()


def _ids(response) -> set[uuid.UUID]:
    return {uuid.UUID(f["id"]) for f in response.json()["features"]}


async def test_returns_only_spots_inside_the_viewport_as_geojson(api_client, viewport_spots):
    response = await api_client.get(URL, params=BBOX)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert _ids(response) == {viewport_spots[k] for k in ("camp", "camp2", "pool")}

    camp = next(f for f in body["features"] if f["id"] == str(viewport_spots["camp"]))
    assert camp["geometry"] == {"type": "Point", "coordinates": [0.5, 0.5]}
    props = camp["properties"]
    assert isinstance(props["latitude"], float) and isinstance(props["longitude"], float)
    assert props["category"] == "CAMPING"
    assert props["source"] == SpotSource.USER_ADDED.value
    assert props["extra_amenities"] == {"water": True, "nearby_hospital_km": 2.5}


async def test_category_filter_accepts_comma_and_repeated_params(api_client, viewport_spots):
    expected = {viewport_spots["camp"], viewport_spots["camp2"], viewport_spots["pool"]}

    comma = await api_client.get(URL, params={**BBOX, "category": "CAMPING,hotel_pool"})
    assert comma.status_code == 200, comma.text
    assert _ids(comma) == expected

    repeated = await api_client.get(
        URL, params=[*BBOX.items(), ("category", "CAMPING"), ("category", "HOTEL_POOL")]
    )
    assert repeated.status_code == 200, repeated.text
    assert _ids(repeated) == expected

    only_pool = await api_client.get(URL, params={**BBOX, "category": "HOTEL_POOL"})
    assert _ids(only_pool) == {viewport_spots["pool"]}


async def test_invalid_category_and_bbox_are_rejected(api_client):
    bad_category = await api_client.get(URL, params={**BBOX, "category": "CAMPING,wild_camping"})
    assert bad_category.status_code == 422

    inverted = await api_client.get(URL, params={**BBOX, "min_lat": 2.0})
    assert inverted.status_code == 400

    missing = await api_client.get(URL, params={"min_lat": 0, "max_lat": 1})
    assert missing.status_code == 422
