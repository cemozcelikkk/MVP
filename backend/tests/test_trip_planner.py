import uuid
from io import BytesIO
import pytest
from PIL import Image
from sqlalchemy import delete
from app.core.config import settings
from app.models.saved_list import SavedList
from app.models.account_token import PlaceCache
from app.models.enums import UserRole
from tests.conftest import auth_headers

@pytest.fixture(autouse=True)
def disable_http_quota(monkeypatch):
    monkeypatch.setattr(settings,"RATE_LIMIT_ENABLED",False)

async def test_order_dates_notes_and_ownership(api_client,make_user,make_spot):
    owner=await make_user();stranger=await make_user();headers=auth_headers(owner)
    first=await make_spot();second=await make_spot()
    response=await api_client.post("/api/v1/lists",headers=headers,json={"title":"Trip regression"})
    assert response.status_code==201,response.text
    list_id=response.json()["id"];url=f"/api/v1/lists/{list_id}"
    for spot_id in (first,second):
        response=await api_client.post(f"{url}/items",headers=headers,json={"spot_id":str(spot_id)})
        assert response.status_code==201,response.text
    response=await api_client.get("/api/v1/lists",headers=headers)
    assert list_id in [item["id"] for item in response.json()]
    assert (await api_client.get(url,headers=auth_headers(stranger))).status_code==403
    response=await api_client.put(f"{url}/order",headers=headers,json={"spot_ids":[str(second),str(first)]})
    assert response.status_code==200,response.text
    assert [item["spot_id"] for item in response.json()["items"]]==[str(second),str(first)]
    assert (await api_client.put(f"{url}/order",headers=headers,json={"spot_ids":[str(first),str(first)]})).status_code==422
    assert (await api_client.put(f"{url}/order",headers=auth_headers(stranger),json={"spot_ids":[str(second),str(first)]})).status_code==403
    response=await api_client.patch(f"{url}/items/{first}",headers=headers,json={"notes":"Doğu girişinden gel","planned_on":"2026-10-15"})
    assert response.status_code==200,response.text
    item=next(item for item in response.json()["items"] if item["spot_id"]==str(first))
    assert item["planned_on"]=="2026-10-15" and item["notes"]=="Doğu girişinden gel"
    assert (await api_client.delete(url,headers=headers)).status_code==204
    assert (await api_client.get(url,headers=headers)).status_code==404

async def test_route_cache_and_corridor(api_client,make_user,make_spot,monkeypatch,db_session):
    from app.services import trip_service
    user=await make_user();headers=auth_headers(user)
    first=await make_spot();second=await make_spot();nearby=await make_spot()
    response=await api_client.post("/api/v1/lists",headers=headers,json={"title":"Route cache regression"})
    list_id=response.json()["id"];url=f"/api/v1/lists/{list_id}"
    for spot in (first,second):await api_client.post(f"{url}/items",headers=headers,json={"spot_id":str(spot)})
    calls=[]
    def provider(coords):
        calls.append(coords)
        return {"geometry":{"type":"LineString","coordinates":[[32.99,39],[33.01,39]]},"distance_km":2,"duration_minutes":5}
    monkeypatch.setattr(trip_service,"query_route",provider)
    await db_session.execute(delete(PlaceCache).where(PlaceCache.query.like("route:%")));await db_session.commit()
    for _ in range(2):
        response=await api_client.get(f"{url}/route",headers=headers)
        assert response.status_code==200,response.text
        assert str(nearby) in [item["id"] for item in response.json()["nearby_spots"]]
        assert str(first) not in [item["id"] for item in response.json()["nearby_spots"]]
    assert len(calls)==1
    await api_client.delete(url,headers=headers)

async def test_entrance_photo_and_moderation(api_client,make_user,make_spot,monkeypatch,tmp_path,db_session):
    from app.services.storage import get_storage
    user=await make_user();staff=await make_user();staff.role=UserRole.MODERATOR;await db_session.commit()
    spot_id=await make_spot()
    monkeypatch.setattr(settings,"UPLOAD_DIR",tmp_path);get_storage.cache_clear()
    buffer=BytesIO();Image.new("RGB",(32,32),(50,120,70)).save(buffer,format="PNG")
    try:
        response=await api_client.post(f"/api/v1/spots/{spot_id}/photos",headers=auth_headers(user),files={"file":("entrance.png",buffer.getvalue(),"image/png")},data={"photo_kind":"entrance"})
        assert response.status_code==201,response.text
        assert response.json()["photo_kind"]=="entrance"
        photo_id=response.json()["id"]
        response=await api_client.post(f"/api/v1/spots/{spot_id}/content-reports",headers=auth_headers(user),json={"target_kind":"photo","target_id":photo_id,"reason":"inappropriate","description":"Fotoğraf test bildirimi"})
        assert response.status_code==201,response.text
        report_id=response.json()["id"]
        response=await api_client.post(f"/api/v1/moderation/content-reports/{report_id}/resolve",headers=auth_headers(staff),json={"action":"hide","note":"İnceleme sonrası gizlendi."})
        assert response.status_code==200,response.text
        response=await api_client.get(f"/api/v1/spots/{spot_id}")
        assert photo_id not in [photo["id"] for photo in response.json()["properties"]["photos"]]
    finally:get_storage.cache_clear()

async def test_new_community_answers(api_client,make_user,make_spot,make_check_in):
    user=await make_user();spot_id=await make_spot();await make_check_in(user,spot_id)
    response=await api_client.post(f"/api/v1/spots/{spot_id}/verifications",headers=auth_headers(user),json={"answers":{"toilet":"working","trash_bins":"not_working","price":"paid","camping_behavior":"allowed"}})
    assert response.status_code==201,response.text
    response=await api_client.get(f"/api/v1/spots/{spot_id}/field-freshness")
    fields={field["field"]:field for field in response.json()["primary"]+response.json()["secondary"]}
    assert fields["price"]["consensus_answer"]=="paid"
    assert fields["trash_bins"]["status"]=="service_issue_reported"
    response=await api_client.post(f"/api/v1/spots/{spot_id}/verifications",headers=auth_headers(user),json={"answers":{"price":"working"}})
    assert response.status_code==422

async def test_quota_http_response(api_client,monkeypatch,db_session):
    from app.models.account_token import RequestQuota
    monkeypatch.setattr(settings,"RATE_LIMIT_ENABLED",True)
    monkeypatch.setattr(settings,"RATE_LIMIT_READ_PER_MINUTE",1)
    await db_session.execute(delete(RequestQuota));await db_session.commit()
    first=await api_client.get("/api/v1/spots/search",params={"q":"quota regression"},headers={"Origin":"http://localhost:5173"})
    assert first.status_code==200,first.text
    second=await api_client.get("/api/v1/spots/search",params={"q":"quota regression"},headers={"Origin":"http://localhost:5173"})
    assert second.status_code==429
    assert int(second.headers["Retry-After"])>0
    assert second.headers["Access-Control-Allow-Origin"]=="http://localhost:5173"
    assert second.headers["X-Request-ID"]
    await db_session.execute(delete(RequestQuota));await db_session.commit()
