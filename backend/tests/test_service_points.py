"""`/api/v1/service-points` - restoran / sağlık / WC / duş noktaları (kamp noktalarından ayrı)."""
import uuid

import pytest_asyncio
from sqlalchemy import delete, select

from app.models.basemap_poi import BasemapPoi
from app.models.enums import UserRole
from app.models.service_point import ServicePoint, ServicePointStatusUpdate
from app.utils.geo import lonlat_to_wkb
from tests.conftest import auth_headers

URL = "/api/v1/service-points"
# Gerçek dev verisiyle çakışmasın diye okyanusta, (0, 0) civarında.
BBOX = {"min_lat": 0.0, "max_lat": 1.0, "min_lng": 0.0, "max_lng": 1.0}


def _coords(lat: float, lng: float) -> dict:
    return {"latitude": lat, "longitude": lng}


@pytest_asyncio.fixture
async def cleanup_points(db_session):
    """Testin oluşturduğu nokta id'lerini toplar ve sonunda hard-delete eder (alt kayıtlar CASCADE)."""
    ids: list[uuid.UUID] = []
    yield ids
    if ids:
        await db_session.execute(delete(ServicePoint).where(ServicePoint.id.in_(ids)))
        await db_session.commit()


async def _create(api_client, user, cleanup, **payload) -> dict:
    response = await api_client.post(URL, json=payload, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    body = response.json()
    cleanup.append(uuid.UUID(body["id"]))
    return body


async def test_minimal_create_flows_per_group(api_client, make_user, cleanup_points):
    user = await make_user()

    # Sağlık: tür + konum yeterli, ad zorunlu değil.
    clinic = await _create(api_client, user, cleanup_points, category="HEALTH_CENTER", coordinates=_coords(0.5, 0.5))
    assert clinic["properties"]["group"] == "health"
    assert clinic["properties"]["name"] is None
    assert clinic["properties"]["review_count"] == 0

    # Temel ihtiyaç: duş bağımsız bir tür; ilk durum opsiyonel.
    shower = await _create(api_client, user, cleanup_points, category="SHOWER", coordinates=_coords(0.51, 0.5))
    assert shower["properties"]["group"] == "basic"
    assert shower["properties"]["fee_status"] == "unknown"
    assert shower["properties"]["status_checked_at"] is None

    # Restoran: ad zorunlu.
    no_name = await api_client.post(
        URL, json={"category": "OTHER_RESTAURANT", "coordinates": _coords(0.52, 0.5), "name": "  "},
        headers=auth_headers(user),
    )
    assert no_name.status_code == 422
    cafe = await _create(
        api_client, user, cleanup_points, category="OTHER_RESTAURANT", name="Yol Kafe", coordinates=_coords(0.52, 0.5)
    )
    assert cafe["properties"]["group"] == "food"

    # Ücret bilgisi yalnızca WC/duşta.
    bad = await api_client.post(
        URL, json={"category": "HOSPITAL", "coordinates": _coords(0.53, 0.5), "fee_status": "free"},
        headers=auth_headers(user),
    )
    assert bad.status_code == 422

    listing = await api_client.get(URL, params={**BBOX, "group": "health,basic"})
    assert listing.status_code == 200
    ids = {f["id"] for f in listing.json()["features"]}
    assert clinic["id"] in ids and shower["id"] in ids and cafe["id"] not in ids


async def test_create_requires_auth_and_rejects_duplicates(api_client, make_user, cleanup_points):
    anonymous = await api_client.post(URL, json={"category": "WC", "coordinates": _coords(0.6, 0.6)})
    assert anonymous.status_code == 401

    user = await make_user()
    await _create(api_client, user, cleanup_points, category="WC", coordinates=_coords(0.6, 0.6))
    # ~11 m ötede aynı tür -> mükerrer.
    duplicate = await api_client.post(
        URL, json={"category": "WC", "coordinates": _coords(0.6001, 0.6)}, headers=auth_headers(user)
    )
    assert duplicate.status_code == 409
    # Aynı yerde FARKLI tür serbest.
    await _create(api_client, user, cleanup_points, category="SHOWER", coordinates=_coords(0.6001, 0.6))


async def test_food_reviews_are_single_active_per_user_and_update_summary(api_client, make_user, cleanup_points):
    owner, other = await make_user(), await make_user()
    point = await _create(
        api_client, owner, cleanup_points, category="FISH_RESTAURANT", name="Test Balıkçı", coordinates=_coords(0.7, 0.7)
    )
    reviews_url = f"{URL}/{point['id']}/reviews"

    first = await api_client.post(reviews_url, json={"rating": 5, "comment": "Taze"}, headers=auth_headers(owner))
    assert first.status_code == 201, first.text
    again = await api_client.post(reviews_url, json={"rating": 3}, headers=auth_headers(owner))
    assert again.status_code == 409
    star_only = await api_client.post(reviews_url, json={"rating": 2}, headers=auth_headers(other))
    assert star_only.status_code == 201
    assert star_only.json()["comment"] is None

    detail = (await api_client.get(f"{URL}/{point['id']}")).json()["properties"]
    assert detail["review_count"] == 2 and detail["average_rating"] == 3.5

    review_id = first.json()["id"]
    forbidden = await api_client.patch(f"{reviews_url}/{review_id}", json={"rating": 1}, headers=auth_headers(other))
    assert forbidden.status_code == 403
    edited = await api_client.patch(f"{reviews_url}/{review_id}", json={"rating": 4}, headers=auth_headers(owner))
    assert edited.status_code == 200 and edited.json()["rating"] == 4

    mine = await api_client.get(f"{reviews_url}/me", headers=auth_headers(owner))
    assert mine.json()["id"] == review_id

    deleted = await api_client.delete(f"{reviews_url}/{review_id}", headers=auth_headers(owner))
    assert deleted.status_code == 204
    detail = (await api_client.get(f"{URL}/{point['id']}")).json()["properties"]
    assert detail["review_count"] == 1 and detail["average_rating"] == 2.0
    # Silindikten sonra yeniden değerlendirebilir.
    assert (await api_client.post(reviews_url, json={"rating": 5}, headers=auth_headers(owner))).status_code == 201


async def test_health_and_basic_points_have_no_reviews(api_client, make_user, cleanup_points):
    user = await make_user()
    hospital = await _create(api_client, user, cleanup_points, category="HOSPITAL", coordinates=_coords(0.8, 0.8))
    wc = await _create(api_client, user, cleanup_points, category="WC", coordinates=_coords(0.81, 0.8))
    for point in (hospital, wc):
        response = await api_client.post(f"{URL}/{point['id']}/reviews", json={"rating": 5}, headers=auth_headers(user))
        assert response.status_code == 422


async def test_basic_status_updates_record_history_and_freshness(api_client, make_user, cleanup_points, db_session):
    user = await make_user()
    wc = await _create(api_client, user, cleanup_points, category="WC", coordinates=_coords(0.9, 0.9))
    status_url = f"{URL}/{wc['id']}/status"

    empty = await api_client.post(status_url, json={}, headers=auth_headers(user))
    assert empty.status_code == 422

    paid = await api_client.post(status_url, json={"fee_status": "paid"}, headers=auth_headers(user))
    assert paid.status_code == 200, paid.text
    props = paid.json()["properties"]
    assert props["fee_status"] == "paid" and props["availability_status"] == "unknown"
    assert props["status_checked_at"] is not None

    closed = await api_client.post(status_url, json={"availability_status": "unavailable"}, headers=auth_headers(user))
    props = closed.json()["properties"]
    assert props["fee_status"] == "paid" and props["availability_status"] == "unavailable"

    history = await api_client.get(f"{URL}/{wc['id']}/status-history")
    assert [h["availability_status"] for h in history.json()] == ["unavailable", None]
    rows = await db_session.scalars(
        select(ServicePointStatusUpdate).where(ServicePointStatusUpdate.service_point_id == uuid.UUID(wc["id"]))
    )
    assert len(rows.all()) == 2

    # Restoranda durum bilgisi yok.
    cafe = await _create(api_client, user, cleanup_points, category="OTHER_RESTAURANT", name="Kafe", coordinates=_coords(0.91, 0.9))
    assert (await api_client.post(f"{URL}/{cafe['id']}/status", json={"fee_status": "free"}, headers=auth_headers(user))).status_code == 422


async def test_reports_flow_to_moderation_and_can_remove_point(api_client, make_user, cleanup_points, db_session):
    reporter, moderator = await make_user(), await make_user()
    moderator.role = UserRole.MODERATOR
    await db_session.commit()
    point = await _create(api_client, reporter, cleanup_points, category="SHOWER", coordinates=_coords(0.95, 0.95))
    reports_url = f"{URL}/{point['id']}/reports"

    report = await api_client.post(reports_url, json={"reason": "closed"}, headers=auth_headers(reporter))
    assert report.status_code == 201, report.text
    again = await api_client.post(reports_url, json={"reason": "duplicate"}, headers=auth_headers(reporter))
    assert again.status_code == 409

    queue_url = "/api/v1/moderation/service-point-reports"
    assert (await api_client.get(queue_url, headers=auth_headers(reporter))).status_code == 403
    queue = await api_client.get(queue_url, params={"limit": 100}, headers=auth_headers(moderator))
    item = next(row for row in queue.json() if row["id"] == report.json()["id"])
    assert item["point"]["category"] == "SHOWER"

    invalid = await api_client.post(
        f"{queue_url}/{item['id']}/resolve", json={"action": "reject", "remove_point": True}, headers=auth_headers(moderator)
    )
    assert invalid.status_code == 422
    resolved = await api_client.post(
        f"{queue_url}/{item['id']}/resolve", json={"action": "resolve", "remove_point": True}, headers=auth_headers(moderator)
    )
    assert resolved.status_code == 200 and resolved.json()["state"] == "resolved"
    assert (await api_client.get(f"{URL}/{point['id']}")).status_code == 404


async def test_owner_can_edit_within_group_only(api_client, make_user, cleanup_points):
    owner, other = await make_user(), await make_user()
    point = await _create(api_client, owner, cleanup_points, category="HOSPITAL", coordinates=_coords(0.3, 0.3))
    point_url = f"{URL}/{point['id']}"

    assert (await api_client.patch(point_url, json={"name": "X"}, headers=auth_headers(other))).status_code == 403
    renamed = await api_client.patch(point_url, json={"name": "Devlet Hastanesi", "category": "HEALTH_CENTER"}, headers=auth_headers(owner))
    assert renamed.status_code == 200 and renamed.json()["properties"]["category"] == "HEALTH_CENTER"
    cross = await api_client.patch(point_url, json={"category": "WC"}, headers=auth_headers(owner))
    assert cross.status_code == 422
    moved = await api_client.patch(point_url, json={"coordinates": _coords(0.31, 0.3)}, headers=auth_headers(owner))
    assert moved.status_code == 403  # konumu yalnızca moderatör düzeltir


async def test_name_suggestion_uses_nearby_osm_health_poi(api_client, db_session):
    poi = BasemapPoi(osm_id=f"node/test-{uuid.uuid4().hex[:8]}", category="hospital", name="Test Devlet Hastanesi",
                     coordinates=lonlat_to_wkb(0.25, 0.25))
    db_session.add(poi)
    await db_session.commit()
    try:
        near = await api_client.get(f"{URL}/name-suggestion", params={"category": "HOSPITAL", "latitude": 0.2504, "longitude": 0.25})
        assert near.status_code == 200 and near.json()["name"] == "Test Devlet Hastanesi"
        far = await api_client.get(f"{URL}/name-suggestion", params={"category": "HOSPITAL", "latitude": 0.26, "longitude": 0.25})
        assert far.json()["name"] is None
        wc = await api_client.get(f"{URL}/name-suggestion", params={"category": "WC", "latitude": 0.2504, "longitude": 0.25})
        assert wc.json()["name"] is None
    finally:
        await db_session.execute(delete(BasemapPoi).where(BasemapPoi.id == poi.id))
        await db_session.commit()


async def test_spots_endpoint_only_accepts_camping(api_client, make_user):
    user = await make_user()
    response = await api_client.post(
        "/api/v1/spots",
        json={
            "title": "Balıkçı", "category": "FISH_RESTAURANT", "coordinates": _coords(0.5, 0.5),
            "passability": {"road_type": "asphalt"}, "amenities": {},
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 422
    assert "service-points" in response.text


async def test_confirmation_is_once_per_day_and_works_for_health(api_client, make_user, cleanup_points):
    first, second = await make_user(), await make_user()
    hospital = await _create(api_client, first, cleanup_points, category="HOSPITAL", coordinates=_coords(0.45, 0.45))
    confirm_url = f"{URL}/{hospital['id']}/confirm"

    ok = await api_client.post(confirm_url, headers=auth_headers(first))
    assert ok.status_code == 200, ok.text
    props = ok.json()["properties"]
    assert props["confirmation_count"] == 1 and props["last_confirmed_at"] is not None
    assert props["review_count"] == 0 and props["average_rating"] is None  # teyit puan değildir
    assert (await api_client.post(confirm_url, headers=auth_headers(first))).status_code == 409
    assert (await api_client.post(confirm_url, headers=auth_headers(second))).json()["properties"]["confirmation_count"] == 2


async def test_only_moderators_can_verify(api_client, make_user, cleanup_points, db_session):
    user, moderator = await make_user(), await make_user()
    moderator.role = UserRole.MODERATOR
    await db_session.commit()
    wc = await _create(api_client, user, cleanup_points, category="WC", coordinates=_coords(0.46, 0.46))
    verify_url = f"{URL}/{wc['id']}/verify"
    assert (await api_client.patch(verify_url, json={"is_verified": True}, headers=auth_headers(user))).status_code == 403
    verified = await api_client.patch(verify_url, json={"is_verified": True}, headers=auth_headers(moderator))
    assert verified.status_code == 200 and verified.json()["properties"]["is_verified"] is True


async def test_per_user_quotas_and_status_cooldown(api_client, make_user, cleanup_points, monkeypatch):
    from app.core.config import settings
    from app.services import service_point_service as svc

    monkeypatch.setattr(settings, "SERVICE_POINT_QUOTAS_ENABLED", True)
    monkeypatch.setitem(svc.QUOTAS, "create", (2, 86_400, "Günlük nokta ekleme sınırına ulaştınız."))
    user = await make_user()
    await _create(api_client, user, cleanup_points, category="WC", coordinates=_coords(0.47, 0.47))
    shower = await _create(api_client, user, cleanup_points, category="SHOWER", coordinates=_coords(0.48, 0.48))
    third = await api_client.post(URL, json={"category": "WC", "coordinates": _coords(0.49, 0.49)}, headers=auth_headers(user))
    assert third.status_code == 429 and "Retry-After" in third.headers

    status_url = f"{URL}/{shower['id']}/status"
    for value in ("available", "unavailable", "available"):
        assert (await api_client.post(status_url, json={"availability_status": value}, headers=auth_headers(user))).status_code == 200
    flip = await api_client.post(status_url, json={"availability_status": "unavailable"}, headers=auth_headers(user))
    assert flip.status_code == 429
