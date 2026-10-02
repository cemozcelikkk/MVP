"""Release regressions: real PostgreSQL and HTTP, provider calls stubbed."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.request_limits import allow_request
from app.core.security import create_access_token, hash_password
from app.models.account_token import AccountToken, RequestQuota
from app.models.enums import UserRole
from app.models.field_verification import VerifiableField
from app.models.spot import Spot
from app.models.user import User
from app.schemas.spot import SpotUpdate
from app.schemas.user import PasswordResetRequest
from app.services.field_freshness import evaluate_field
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def disable_http_quota(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


def test_entry_coordinates_and_password_validation():
    with pytest.raises(ValidationError):
        SpotUpdate(entry_latitude=39)
    with pytest.raises(ValidationError):
        SpotUpdate(entry_latitude=None)
    assert SpotUpdate(entry_latitude=None, entry_longitude=None).entry_latitude is None
    with pytest.raises(ValidationError):
        SpotUpdate(overnight_status="maybe")
    with pytest.raises(ValidationError):
        PasswordResetRequest(token="x" * 32, password="ş" * 40)
    assert SpotUpdate(entry_latitude=39, entry_longitude=33).entry_longitude == 33


@pytest.mark.parametrize(
    "field",
    [
        VerifiableField.TOILET,
        VerifiableField.TRASH_BINS,
        VerifiableField.PRICE,
        VerifiableField.CAMPING_BEHAVIOR,
    ],
)
def test_new_fields_unverified(field):
    result = evaluate_field(field, [], now=datetime.now(UTC))
    assert result.status == "unverified"
    assert result.confidence == "low"


async def test_travel_fields_permissions_history_and_filters(
    api_client, make_user, make_spot, db_session
):
    owner = await make_user()
    stranger = await make_user()
    staff = await make_user()
    staff.role = UserRole.MODERATOR
    await db_session.commit()
    spot_id = await make_spot(created_by=owner.id)
    url = f"/api/v1/spots/{spot_id}"
    payload = {
        "overnight_status": "allowed",
        "max_stay_nights": 3,
        "rule_source": "Tabela",
        "entry_latitude": 39.001,
        "entry_longitude": 33.002,
        "approach_description": "Doğu kapısı",
        "amenities": {
            "has_toilet": True,
            "has_trash_bins": True,
            "is_free": True,
            "rule_information_known": True,
        },
    }
    response = await api_client.patch(url, headers=auth_headers(owner), json=payload)
    assert response.status_code == 200, response.text
    props = response.json()["properties"]
    assert props["entry_latitude"] == 39.001
    assert props["amenities"]["rule_information_known"]
    assert (
        await api_client.patch(url, headers=auth_headers(stranger), json={"title": "Başka kişi"})
    ).status_code == 403
    assert (
        await api_client.patch(
            url,
            headers=auth_headers(owner),
            json={"coordinates": {"latitude": 40, "longitude": 34}},
        )
    ).status_code == 403
    response = await api_client.patch(
        url, headers=auth_headers(staff), json={"coordinates": {"latitude": 40, "longitude": 34}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["geometry"]["coordinates"] == [34, 40]
    response = await api_client.get(f"{url}/changes", headers=auth_headers(owner))
    assert response.status_code == 403
    response = await api_client.get(f"{url}/changes", headers=auth_headers(staff))
    assert response.status_code == 200, response.text
    assert len(response.json()) == 3
    params = {
        "min_lon": 33.9,
        "min_lat": 39.9,
        "max_lon": 34.1,
        "max_lat": 40.1,
        "has_toilet": True,
        "is_free": True,
        "overnight_allowed": True,
    }
    response = await api_client.get("/api/v1/spots/bbox", params=params)
    assert response.status_code == 200, response.text
    assert str(spot_id) in [f["properties"]["id"] for f in response.json()["features"]]
    await api_client.patch(
        url, headers=auth_headers(owner), json={"amenities": {"rule_information_known": False}}
    )
    response = await api_client.get("/api/v1/spots/bbox", params=params)
    assert str(spot_id) not in [f["properties"]["id"] for f in response.json()["features"]]
    response = await api_client.get(f"{url}/field-freshness")
    fields = {item["field"] for item in response.json()["primary"] + response.json()["secondary"]}
    assert {"toilet", "trash_bins", "price", "camping_behavior"} <= fields
    response = await api_client.delete(url, headers=auth_headers(owner))
    assert response.status_code == 204, response.text
    assert (await api_client.get(url)).status_code == 404
    response = await api_client.get(f"{url}/changes", headers=auth_headers(staff))
    assert response.json()[0]["action"] == "deleted"


async def test_content_report_moderation_and_duplicate(
    api_client, make_user, make_spot, db_session
):
    user = await make_user()
    staff = await make_user()
    staff.role = UserRole.MODERATOR
    await db_session.commit()
    spot_id = await make_spot(created_by=user.id)
    payload = {
        "target_id": str(spot_id),
        "reason": "closed",
        "description": "Alan kalıcı olarak kapanmış.",
    }
    url = f"/api/v1/spots/{spot_id}/content-reports"
    assert (await api_client.post(url, json=payload)).status_code == 401
    response = await api_client.post(url, headers=auth_headers(user), json=payload)
    assert response.status_code == 201, response.text
    report_id = response.json()["id"]
    assert "reporter_id" not in response.json()
    assert (await api_client.post(url, headers=auth_headers(user), json=payload)).status_code == 409
    queue = "/api/v1/moderation/content-reports"
    assert (await api_client.get(queue, headers=auth_headers(user))).status_code == 403
    response = await api_client.post(
        f"{queue}/{report_id}/resolve",
        headers=auth_headers(staff),
        json={"action": "hide", "note": "Kapanış teyit edildi."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "resolved"
    assert (await api_client.get(f"/api/v1/spots/{spot_id}")).status_code == 404
    assert (
        await api_client.post(
            f"{queue}/{report_id}/resolve",
            headers=auth_headers(staff),
            json={"action": "reject", "note": "Tekrar işlem"},
        )
    ).status_code == 409


async def test_report_target_must_belong_to_spot(api_client, make_user, make_spot):
    user = await make_user()
    first = await make_spot()
    second = await make_spot()
    response = await api_client.post(
        f"/api/v1/spots/{first}/content-reports",
        headers=auth_headers(user),
        json={"target_id": str(second), "reason": "other", "description": "Yanlış hedef kaydı"},
    )
    assert response.status_code == 404


async def test_spot_search_literal_and_nearby(api_client, make_spot):
    first = await make_spot(title="QA Wildcard % " + uuid.uuid4().hex)
    response = await api_client.get("/api/v1/spots/search", params={"q": "QA Wildcard %"})
    assert response.status_code == 200, response.text
    assert str(first) in [f["properties"]["id"] for f in response.json()["features"]]
    response = await api_client.get(
        "/api/v1/spots/search", params={"latitude": 39, "longitude": 33, "radius_km": 1}
    )
    assert response.status_code == 200, response.text
    assert str(first) in [f["properties"]["id"] for f in response.json()["features"]]
    assert (
        await api_client.get("/api/v1/spots/search", params={"latitude": 39})
    ).status_code == 422


async def test_place_search_cache(api_client, monkeypatch, db_session):
    from app.api.v1.endpoints import search
    from app.models.account_token import PlaceCache

    query = "qa-" + uuid.uuid4().hex
    calls = []

    def provider(q):
        calls.append(q)
        return [
            {
                "label": "Test ilçe",
                "latitude": 39,
                "longitude": 33,
                "attribution": "© OpenStreetMap contributors",
            }
        ]

    monkeypatch.setattr(search, "query_places", provider)
    try:
        for _ in range(2):
            response = await api_client.get("/api/v1/places/search", params={"q": query})
            assert response.status_code == 200, response.text
            assert response.json()[0]["latitude"] == 39
        assert len(calls) == 1
    finally:
        await db_session.execute(delete(PlaceCache).where(PlaceCache.query == query))
        await db_session.commit()


def read_mail_token(directory):
    file = next(Path(directory).glob("*.eml"))
    msg = message_from_bytes(file.read_bytes())
    content = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8")
    link = next(line for line in content.splitlines() if line.startswith("http"))
    return parse_qs(urlparse(link).fragment)["token"][0]


async def test_account_tokens_single_use_and_session_revocation(
    api_client, make_user, db_session, monkeypatch, tmp_path
):
    user = await make_user()
    user.hashed_password = hash_password("old-password-123")
    await db_session.commit()
    monkeypatch.setattr(settings, "MAIL_BACKEND", "file")
    monkeypatch.setattr(settings, "MAIL_OUTBOX_DIR", tmp_path)
    old_token = create_access_token(subject=user.id)
    response = await api_client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert response.status_code == 200, response.text
    raw = read_mail_token(tmp_path)
    stored = await db_session.scalar(select(AccountToken).where(AccountToken.user_id == user.id))
    assert stored.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert stored.token_hash != raw
    response = await api_client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "password": "new-password-123"}
    )
    assert response.status_code == 200, response.text
    assert (
        await api_client.post(
            "/api/v1/auth/reset-password", json={"token": raw, "password": "another-password"}
        )
    ).status_code == 400
    assert (
        await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    ).status_code == 401
    response = await api_client.post(
        "/api/v1/auth/login", data={"username": user.email, "password": "new-password-123"}
    )
    assert response.status_code == 200, response.text
    fresh_header = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert (await api_client.get("/api/v1/auth/me", headers=fresh_header)).status_code == 200
    for file in tmp_path.glob("*.eml"):
        file.unlink()
    assert (
        await api_client.post("/api/v1/auth/request-verification", headers=fresh_header)
    ).status_code == 200
    raw = read_mail_token(tmp_path)
    assert (
        await api_client.post("/api/v1/auth/verify-email", json={"token": raw})
    ).status_code == 200
    assert (await api_client.get("/api/v1/auth/me", headers=fresh_header)).json()["email_verified"]
    assert (
        await api_client.post("/api/v1/auth/verify-email", json={"token": raw})
    ).status_code == 400


async def test_expired_reset_and_generic_email_response(api_client, make_user, db_session):
    user = await make_user()
    raw = "expired-" + uuid.uuid4().hex
    db_session.add(
        AccountToken(
            user_id=user.id,
            purpose="reset",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()
    response = await api_client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "password": "password-123"}
    )
    assert response.status_code == 400
    response = await api_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "missing-" + uuid.uuid4().hex + "@example.com"},
    )
    assert response.status_code == 200
    assert "token" not in response.json()


async def test_account_deletion_keeps_shared_spot(api_client, db_session):
    from app.schemas.spot import SpotCreate
    from app.services.spot_service import create_spot

    user = User(
        email=f"delete-{uuid.uuid4().hex}@example.com",
        display_name="Delete Test",
        hashed_password=hash_password("password-123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    user_id = user.id
    feature = await create_spot(
        db_session,
        data=SpotCreate(
            title="Delete test spot",
            category="wild_camping",
            coordinates={"latitude": 39, "longitude": 33},
            passability={"road_type": "asphalt"},
            amenities={},
        ),
        created_by=user_id,
    )
    spot_id = feature.properties.id
    try:
        headers = auth_headers(user)
        bad = await api_client.request(
            "DELETE",
            "/api/v1/users/me",
            headers=headers,
            json={"password": "bad", "confirmation": "HESABIMI SİL"},
        )
        assert bad.status_code == 400
        response = await api_client.request(
            "DELETE",
            "/api/v1/users/me",
            headers=headers,
            json={"password": "password-123", "confirmation": "HESABIMI SİL"},
        )
        assert response.status_code == 204, response.text
        assert (await api_client.get("/api/v1/auth/me", headers=headers)).status_code == 401
        response = await api_client.get(f"/api/v1/spots/{spot_id}")
        assert response.status_code == 200
        assert response.json()["properties"]["created_by"] is None
    finally:
        await db_session.execute(delete(Spot).where(Spot.id == spot_id))
        await db_session.execute(delete(User).where(User.id == user_id))
        await db_session.commit()


async def test_shared_request_quota(db_session):
    identity = "qa-" + uuid.uuid4().hex
    assert (await allow_request(db_session, identity, 2))[0]
    assert (await allow_request(db_session, identity, 2))[0]
    allowed, retry = await allow_request(db_session, identity, 2)
    assert not allowed and retry > 0
    await db_session.execute(
        delete(RequestQuota).where(
            RequestQuota.key == hashlib.sha256(identity.encode()).hexdigest()
        )
    )
    await db_session.commit()
