"""Düşük zoom harita POI'leri: içe aktarma (scripts/import_basemap_pois.py) + `/basemap-pois`."""
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.models.basemap_poi import BasemapPoi
from scripts.import_basemap_pois import element_to_row, elements_to_rows, grid_cells, prune_unseen, upsert_pois

URL = "/api/v1/basemap-pois"
# Gerçek veriyle çakışmasın diye okyanusta, (0, 0) civarında.
BBOX = {"min_lat": 0.0, "max_lat": 1.0, "min_lng": 0.0, "max_lng": 1.0}
TEST_PREFIX = "node/99100"
OLD = datetime(2000, 1, 1, tzinfo=UTC)
NEWER = datetime(2000, 1, 2, tzinfo=UTC)


def _node(n: int, amenity: str, name: str | None = None, lat: float = 0.5, lon: float = 0.5) -> dict:
    tags = {"amenity": amenity, **({"name": name} if name else {})}
    return {"type": "node", "id": int(f"99100{n}"), "lat": lat, "lon": lon, "tags": tags}


def test_element_to_row_keeps_only_supported_amenities():
    row = element_to_row(_node(1, "hospital", "Devlet Hastanesi"))
    assert row is not None and row["category"] == "hospital" and row["name"] == "Devlet Hastanesi"
    assert element_to_row(_node(2, "pharmacy"))["name"] is None  # adsız da tutulur (ikon gösterilir)
    assert element_to_row(_node(3, "restaurant")) is None
    way = {"type": "way", "id": 5, "center": {"lat": 1, "lon": 2}, "tags": {"amenity": "fuel"}}
    assert element_to_row(way)["osm_id"] == "way/5"


def test_grid_cells_cover_the_bbox_without_gaps():
    cells = grid_cells((35.8, 25.6, 42.2, 44.9))
    assert min(c[0] for c in cells) == 35.8 and max(c[2] for c in cells) == 42.2
    assert min(c[1] for c in cells) == 25.6 and max(c[3] for c in cells) == 44.9
    assert all(c[0] < c[2] and c[1] < c[3] for c in cells)


async def test_upsert_updates_and_prune_removes_unseen(db_session):
    by_prefix = BasemapPoi.osm_id.like(f"{TEST_PREFIX}%")
    try:
        await upsert_pois(db_session, elements_to_rows([_node(1, "hospital", "Eski Ad"), _node(2, "fuel")]), OLD)
        # İkinci çalıştırma: 1 adını değiştirdi, 2 OSM'den kalktı.
        await upsert_pois(db_session, elements_to_rows([_node(1, "hospital", "Yeni Ad")]), NEWER)
        rows = (await db_session.execute(select(BasemapPoi.osm_id, BasemapPoi.name).where(by_prefix))).all()
        assert sorted(rows) == [(f"{TEST_PREFIX}1", "Yeni Ad"), (f"{TEST_PREFIX}2", None)]

        # Sadece NEWER'dan önce görülenler silinir (gerçek veri 2000'den yeni -> dokunulmaz).
        assert await prune_unseen(db_session, NEWER) == 1
        remaining = (await db_session.execute(select(BasemapPoi.osm_id).where(by_prefix))).scalars().all()
        assert remaining == [f"{TEST_PREFIX}1"]
    finally:
        await db_session.execute(delete(BasemapPoi).where(by_prefix))
        await db_session.commit()


async def test_endpoint_filters_by_bbox_and_category_and_orders_by_priority(api_client, db_session):
    by_prefix = BasemapPoi.osm_id.like(f"{TEST_PREFIX}%")
    elements = [
        _node(1, "pharmacy", "Eczane"),
        _node(2, "hospital", "Hastane"),
        _node(3, "fuel", "Akaryakıt"),
        _node(4, "hospital", "Kutu Dışı", lat=1.5),
    ]
    try:
        await upsert_pois(db_session, elements_to_rows(elements), datetime.now(UTC))

        response = await api_client.get(URL, params=BBOX)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"].startswith("public")
        cats = [f["properties"]["category"] for f in response.json()["features"]]
        assert cats == ["hospital", "fuel", "pharmacy"]  # önem sırası, kutu dışı yok

        limited = await api_client.get(URL, params={**BBOX, "limit": 1})
        assert [f["properties"]["name"] for f in limited.json()["features"]] == ["Hastane"]

        filtered = await api_client.get(URL, params={**BBOX, "category": "fuel,pharmacy"})
        assert sorted(f["properties"]["category"] for f in filtered.json()["features"]) == ["fuel", "pharmacy"]
        feature = filtered.json()["features"][0]
        assert feature["geometry"] == {"type": "Point", "coordinates": [0.5, 0.5]}

        assert (await api_client.get(URL, params={**BBOX, "category": "restaurant"})).status_code == 422
        assert (await api_client.get(URL, params={**BBOX, "min_lat": 2})).status_code == 400
    finally:
        await db_session.execute(delete(BasemapPoi).where(by_prefix))
        await db_session.commit()
