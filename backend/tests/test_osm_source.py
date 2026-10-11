"""Harici (OpenStreetMap) hizmet noktası kaynağı: etiket eşlemesi, hücre önbelleği,
hata/geri çekilme, KaravanTR kayıtlarıyla birleştirme ve katkıda somutlaşma.

Gerçek Overpass'a HİÇ gidilmez: `osm_enabled` fixture'ı sahte bir kaynak kurar."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.config import settings
from app.models.basemap_poi import BasemapPoi
from app.models.enums import ServicePointCategory
from app.models.osm_cache import OsmPoi, OsmTile, osm_virtual_id
from app.models.service_point import ServicePoint
from app.services import osm_source
from app.services.osm_source import ExternalStatus, classify, element_to_poi, fee_status_from_tags
from app.utils.geo import lonlat_to_wkb
from app.utils.text_match import names_match
from tests.conftest import auth_headers

URL = "/api/v1/service-points"
# Okyanusta tek bir 0.05° hücresi: (0.30-0.35, 0.30-0.35).
CELL = {"min_lat": 0.301, "max_lat": 0.349, "min_lng": 0.301, "max_lng": 0.349}
NODE_BASE = 991_000_000


def _node(n: int, lat: float, lng: float, **tags) -> dict:
    return {"type": "node", "id": NODE_BASE + n, "lat": lat, "lon": lng, "tags": tags}


class FakeOverpass:
    def __init__(self, elements=None, fail: bool = False):
        self.elements = elements or []
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, query: str):
        self.calls.append(query)
        if self.fail:
            raise osm_source.OverpassError("test: down", retryable=True)
        return self.elements


@pytest_asyncio.fixture
async def osm_enabled(monkeypatch, db_session):
    """Harici kaynağı açar, Overpass'ı sahte kaynakla değiştirir ve test sonunda bu
    test bölgesine ait cache/kayıtları temizler."""
    fake = FakeOverpass()
    monkeypatch.setattr(settings, "OSM_EXTERNAL_ENABLED", True)
    monkeypatch.setattr(settings, "OSM_FETCH_IN_BACKGROUND", False)  # deterministik: aynı istekte çek
    monkeypatch.setattr(osm_source, "fetch_overpass_with_fallback", lambda q: fake(q))

    async def allow():
        return True

    monkeypatch.setattr(osm_source, "_allow_global_request", allow)
    yield fake
    prefix = f"{settings.OSM_TILE_DEGREES}:"
    await db_session.execute(delete(OsmPoi).where(OsmPoi.osm_id.like(f"node/{str(NODE_BASE)[:3]}%")))
    await db_session.execute(delete(OsmTile).where(OsmTile.key.in_([f"{prefix}6:6", f"{prefix}7:6", f"{prefix}6:7"])))
    await db_session.execute(delete(ServicePoint).where(ServicePoint.osm_id.like(f"node/{str(NODE_BASE)[:3]}%")))
    await db_session.commit()


@pytest_asyncio.fixture
async def cleanup_points(db_session):
    ids: list[uuid.UUID] = []
    yield ids
    if ids:
        await db_session.execute(delete(ServicePoint).where(ServicePoint.id.in_(ids)))
        await db_session.commit()


# --- Saf fonksiyonlar ----------------------------------------------------------------


def test_classify_maps_osm_tags_to_categories():
    assert classify({"amenity": "hospital"}) == ServicePointCategory.HOSPITAL
    assert classify({"amenity": "clinic"}) == ServicePointCategory.HEALTH_CENTER
    assert classify({"amenity": "restaurant", "cuisine": "turkish;fish"}) == ServicePointCategory.FISH_RESTAURANT
    assert classify({"amenity": "restaurant", "cuisine": "regional; meat"}) == ServicePointCategory.MEAT_RESTAURANT
    assert classify({"amenity": "fast_food", "cuisine": "kebab"}) == ServicePointCategory.MEAT_RESTAURANT
    assert classify({"amenity": "restaurant", "cuisine": "pizza"}) == ServicePointCategory.OTHER_RESTAURANT
    assert classify({"amenity": "cafe"}) == ServicePointCategory.OTHER_RESTAURANT
    assert classify({"amenity": "toilets"}) == ServicePointCategory.WC
    assert classify({"amenity": "shower"}) == ServicePointCategory.SHOWER
    assert classify({"amenity": "toilets", "access": "customers"}) is None
    assert classify({"tourism": "hotel"}) is None


def test_element_to_poi_rules():
    poi = element_to_poi({"type": "way", "id": 42, "center": {"lat": 37.01, "lon": 35.33},
                          "tags": {"amenity": "toilets", "fee": "no", "addr:street": "Sahil Yolu", "addr:city": "Kaş"}})
    assert poi["osm_id"] == "way/42" and poi["category"] == ServicePointCategory.WC
    assert poi["tags"] == {"fee": "no", "address": "Sahil Yolu, Kaş"}
    assert element_to_poi({"type": "node", "id": 8, "lat": 37, "lon": 35, "tags": {"amenity": "cafe"}}) is None  # adsız kafe
    assert fee_status_from_tags({"fee": "yes"}) == "paid"
    assert fee_status_from_tags({"charge": "5 TRY"}) == "paid"
    assert fee_status_from_tags({}) == "unknown"


def test_virtual_id_is_stable():
    assert osm_virtual_id("node/1") == osm_virtual_id("node/1") != osm_virtual_id("node/2")


def test_name_matching():
    assert names_match("Deniz Balık Restaurant", "Deniz Balık Evi") is True
    assert names_match("Şehir Hastanesi", "Sehir Hastanesi") is True
    assert names_match("Kaptan Balık", "Mavi Köşk Kafe") is False
    assert names_match(None, "Mavi Köşk") is None
    assert names_match("Restoran", "Kafe") is None  # yalnızca genel sözcükler


# --- Önbellek ------------------------------------------------------------------------


async def test_tile_is_fetched_once_and_cached(api_client, osm_enabled, db_session):
    osm_enabled.elements = [
        _node(1, 0.32, 0.32, amenity="restaurant", cuisine="seafood", name="OSM Balıkçı"),
        _node(2, 0.33, 0.33, amenity="toilets", fee="no"),
        _node(3, 0.36, 0.36, amenity="shower"),  # istenen hücrenin dışında -> yazılmaz
    ]
    first = await api_client.get(URL, params=CELL)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["external_status"] == "ok"
    assert body["attribution"] and "OpenStreetMap" in body["attribution"]
    by_osm = {f["properties"]["osm_id"]: f["properties"] for f in body["features"]}
    assert set(by_osm) == {f"node/{NODE_BASE + 1}", f"node/{NODE_BASE + 2}"}
    wc = by_osm[f"node/{NODE_BASE + 2}"]
    assert wc["is_external"] is True and wc["source"] == "OVERPASS_OSM"
    assert wc["fee_status"] == "free" and wc["availability_status"] == "unknown" and wc["status_checked_at"] is None
    assert wc["id"] == str(osm_virtual_id(f"node/{NODE_BASE + 2}"))

    second = await api_client.get(URL, params=CELL)
    assert len(second.json()["features"]) == 2
    assert len(osm_enabled.calls) == 1  # TTL içinde Overpass'a tekrar gidilmez
    assert await db_session.scalar(select(ServicePoint.id).where(ServicePoint.osm_id.like("node/991%"))) is None


async def test_overpass_failure_backs_off_and_user_points_still_work(api_client, osm_enabled, make_user, cleanup_points):
    user = await make_user()
    created = await api_client.post(
        URL, json={"category": "WC", "coordinates": {"latitude": 0.31, "longitude": 0.31}}, headers=auth_headers(user)
    )
    cleanup_points.append(uuid.UUID(created.json()["id"]))
    osm_enabled.fail = True

    response = await api_client.get(URL, params=CELL)
    assert response.status_code == 200
    assert response.json()["external_status"] == "unavailable"
    assert [f["id"] for f in response.json()["features"]] == [created.json()["id"]]

    await api_client.get(URL, params=CELL)
    assert len(osm_enabled.calls) == 1  # geri çekilme süresinde tekrar denenmez


async def test_wide_view_skips_external_and_disabled_flag(api_client, osm_enabled, monkeypatch):
    wide = await api_client.get(URL, params={"min_lat": 0.0, "max_lat": 1.0, "min_lng": 0.0, "max_lng": 1.0})
    assert wide.json()["external_status"] == "too_wide"
    assert osm_enabled.calls == []
    health_only = await api_client.get(URL, params={**CELL, "group": "health"})
    assert health_only.json()["external_status"] == "not_needed"
    monkeypatch.setattr(settings, "OSM_EXTERNAL_ENABLED", False)
    assert (await api_client.get(URL, params=CELL)).json()["external_status"] == "disabled"


async def test_removed_osm_objects_drop_from_cache_on_refetch(osm_enabled, db_session):
    osm_enabled.elements = [_node(4, 0.32, 0.32, amenity="shower"), _node(5, 0.33, 0.33, amenity="shower")]
    assert await osm_source.ensure_tiles(db_session, min_lon=0.301, min_lat=0.301, max_lon=0.349, max_lat=0.349) is ExternalStatus.OK
    # TTL'i geçmiş say ve OSM'den bir nesne silinmiş olsun.
    tile = await db_session.get(OsmTile, osm_source.tile_key(6, 6))
    tile.fetched_at = tile.fetched_at.replace(year=2000)
    await db_session.commit()
    osm_enabled.elements = [_node(4, 0.32, 0.32, amenity="shower")]
    await osm_source.ensure_tiles(db_session, min_lon=0.301, min_lat=0.301, max_lon=0.349, max_lat=0.349)
    ids = set((await db_session.scalars(select(OsmPoi.osm_id).where(OsmPoi.tile_key == osm_source.tile_key(6, 6)))).all())
    assert ids == {f"node/{NODE_BASE + 4}"}


# --- Birleştirme / mükerrer önleme ----------------------------------------------------


async def test_user_point_suppresses_matching_osm_duplicate(api_client, osm_enabled, make_user, cleanup_points):
    user = await make_user()
    osm_enabled.elements = [
        _node(6, 0.320, 0.320, amenity="restaurant", cuisine="seafood", name="Deniz Balık Restaurant"),
        _node(7, 0.3201, 0.320, amenity="restaurant", name="Mavi Köşk Kafe"),  # ~11 m, farklı işletme
    ]
    await api_client.get(URL, params=CELL)  # cache dolsun
    # Kullanıcı aynı balıkçıyı biraz farklı adla eklemek isterse: mevcut OSM noktası önerilir.
    conflict = await api_client.post(
        URL,
        json={"category": "FISH_RESTAURANT", "name": "Deniz Balık Evi", "coordinates": {"latitude": 0.32002, "longitude": 0.32}},
        headers=auth_headers(user),
    )
    assert conflict.status_code == 409
    assert conflict.json()["existing_id"] == str(osm_virtual_id(f"node/{NODE_BASE + 6}"))

    # OSM'de olmayan, eski bir kullanıcı kaydı aynı yerde duruyorsa haritada TEK marker kalır.
    user_row = ServicePoint(
        category=ServicePointCategory.MEAT_RESTAURANT, name="Deniz Balıkçısı", created_by=user.id,
        coordinates=lonlat_to_wkb(0.32, 0.32001),
    )
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db.add(user_row)
        await db.commit()
        cleanup_points.append(user_row.id)

    features = (await api_client.get(URL, params=CELL)).json()["features"]
    names = sorted(f["properties"]["name"] for f in features)
    assert names == ["Deniz Balıkçısı", "Mavi Köşk Kafe"]


async def test_contribution_materializes_osm_point_with_same_id(api_client, osm_enabled, make_user, db_session):
    user = await make_user()
    osm_enabled.elements = [_node(8, 0.33, 0.31, amenity="toilets", fee="yes")]
    await api_client.get(URL, params=CELL)
    point_id = str(osm_virtual_id(f"node/{NODE_BASE + 8}"))

    detail = await api_client.get(f"{URL}/{point_id}")
    assert detail.status_code == 200 and detail.json()["properties"]["is_external"] is True
    assert (await api_client.get(f"{URL}/{point_id}/status-history")).json() == []

    updated = await api_client.post(f"{URL}/{point_id}/status", json={"availability_status": "available"}, headers=auth_headers(user))
    assert updated.status_code == 200, updated.text
    props = updated.json()["properties"]
    assert props["id"] == point_id and props["is_external"] is False
    assert props["osm_id"] == f"node/{NODE_BASE + 8}" and props["fee_status"] == "paid"
    assert props["status_checked_at"] is not None

    features = (await api_client.get(URL, params=CELL)).json()["features"]
    assert [f["id"] for f in features] == [point_id]  # OSM kopyası değil, KaravanTR kaydı
    assert features[0]["properties"]["availability_status"] == "available"


async def test_removed_point_keeps_osm_copy_hidden(api_client, osm_enabled, make_user, db_session):
    reporter, moderator = await make_user(), await make_user()
    from app.models.enums import UserRole

    moderator.role = UserRole.MODERATOR
    await db_session.commit()
    osm_enabled.elements = [_node(9, 0.34, 0.34, amenity="shower")]
    await api_client.get(URL, params=CELL)
    point_id = str(osm_virtual_id(f"node/{NODE_BASE + 9}"))

    report = await api_client.post(f"{URL}/{point_id}/reports", json={"reason": "closed"}, headers=auth_headers(reporter))
    assert report.status_code == 201
    resolved = await api_client.post(
        f"/api/v1/moderation/service-point-reports/{report.json()['id']}/resolve",
        json={"action": "resolve", "remove_point": True}, headers=auth_headers(moderator),
    )
    assert resolved.status_code == 200
    assert (await api_client.get(URL, params=CELL)).json()["features"] == []
    assert (await api_client.get(f"{URL}/{point_id}")).status_code == 404


async def test_health_comes_from_basemap_pois_and_nearby_is_sorted(api_client, osm_enabled, db_session):
    near = BasemapPoi(osm_id=f"node/{NODE_BASE + 10}", category="hospital", name="Test Devlet Hastanesi",
                      coordinates=lonlat_to_wkb(0.321, 0.32))
    far = BasemapPoi(osm_id=f"node/{NODE_BASE + 11}", category="clinic", name=None,
                     coordinates=lonlat_to_wkb(0.34, 0.32))
    db_session.add_all([near, far])
    await db_session.commit()
    try:
        response = await api_client.get(
            f"{URL}/nearby", params={"latitude": 0.32, "longitude": 0.32, "radius_m": 3000, "group": "health"}
        )
        assert response.status_code == 200, response.text
        props = [f["properties"] for f in response.json()["features"]]
        assert [p["osm_id"] for p in props] == [f"node/{NODE_BASE + 10}", f"node/{NODE_BASE + 11}"]
        assert props[0]["distance_m"] < props[1]["distance_m"] <= 3000
        assert props[1]["category"] == "HEALTH_CENTER" and props[1]["name"] is None
        assert osm_enabled.calls == []  # sağlık için Overpass'a gidilmez
        assert response.json()["external_status"] == "not_needed"
    finally:
        await db_session.execute(delete(BasemapPoi).where(BasemapPoi.id.in_([near.id, far.id])))
        await db_session.commit()


@pytest.mark.parametrize("radius", [50, 25_000])
async def test_nearby_validates_radius(api_client, radius):
    response = await api_client.get(f"{URL}/nearby", params={"latitude": 0.3, "longitude": 0.3, "radius_m": radius})
    assert response.status_code == 422


async def test_background_fetch_returns_partial_then_fills(api_client, osm_enabled, monkeypatch):
    """API varsayılanı: Overpass beklenmez - ilk yanıt "partial", arka plan görevi bitince veri gelir."""
    import asyncio

    monkeypatch.setattr(settings, "OSM_FETCH_IN_BACKGROUND", True)
    osm_enabled.elements = [_node(12, 0.32, 0.32, amenity="shower")]
    first = await api_client.get(URL, params=CELL)
    assert first.json()["external_status"] == "partial"
    assert first.json()["features"] == []
    for _ in range(50):
        if not osm_source._IN_FLIGHT:
            break
        await asyncio.sleep(0.05)
    second = await api_client.get(URL, params=CELL)
    assert second.json()["external_status"] == "ok"
    assert [f["properties"]["osm_id"] for f in second.json()["features"]] == [f"node/{NODE_BASE + 12}"]
    assert len(osm_enabled.calls) == 1


async def test_nearby_wide_radius_keeps_health_and_returns_nearest_first(api_client, osm_enabled, db_session, monkeypatch):
    # 10 km yarıçap harita görünüm sınırını (24 hücre) aşar ama "yakınımdakiler" için geçerlidir.
    monkeypatch.setattr(settings, "OSM_MAX_TILES_PER_FETCH", 200)  # sahte kaynak: tek seferde hepsi
    pois = [
        BasemapPoi(osm_id=f"node/{NODE_BASE + 20 + i}", category="hospital", name=f"Test H{i}",
                   coordinates=lonlat_to_wkb(0.32 + 0.01 * i, 0.32))
        for i in range(5)
    ]
    db_session.add_all(pois)
    await db_session.commit()
    try:
        response = await api_client.get(
            f"{URL}/nearby", params={"latitude": 0.32, "longitude": 0.32, "radius_m": 10_000, "group": "health", "limit": 3}
        )
        body = response.json()
        assert body["external_status"] == "not_needed"
        assert [f["properties"]["name"] for f in body["features"]] == ["Test H0", "Test H1", "Test H2"]
        wide_view = await api_client.get(URL, params={"min_lat": 0.23, "max_lat": 0.41, "min_lng": 0.23, "max_lng": 0.41})
        assert wide_view.json()["external_status"] == "too_wide"
    finally:
        await db_session.execute(delete(BasemapPoi).where(BasemapPoi.id.in_([p.id for p in pois])))
        await db_session.commit()


async def test_duplicates_inside_osm_are_merged_but_distinct_unnamed_points_are_kept(api_client, osm_enabled):
    osm_enabled.elements = [
        _node(30, 0.3200, 0.3200, amenity="restaurant", name="Giant Stride"),
        _node(31, 0.3200, 0.3200, amenity="cafe", name="Giant Stride"),  # aynı yer, OSM'de iki kez
        _node(32, 0.3300, 0.3300, amenity="toilets"),
        _node(33, 0.3301, 0.3300, amenity="toilets"),  # ~11 m ötede ayrı bir WC
    ]
    features = (await api_client.get(URL, params=CELL)).json()["features"]
    names = sorted((f["properties"]["category"], f["properties"]["name"] or "") for f in features)
    assert names == [("OTHER_RESTAURANT", "Giant Stride"), ("WC", ""), ("WC", "")]
