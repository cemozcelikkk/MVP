import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import delete

from app.models.spot import Spot
from app.schemas.spot_amenities import SpotAmenitiesCreate
from tests.conftest import auth_headers


def test_defaults_and_price_limit():
    amenities = SpotAmenitiesCreate()
    assert not amenities.has_toilet
    assert not amenities.has_trash_bins
    assert amenities.is_free
    assert amenities.price_description is None
    assert amenities.camping_behavior_allowed
    with pytest.raises(ValidationError):
        SpotAmenitiesCreate(price_description="x" * 301)


async def test_create_update_and_read(api_client, make_user, db_session):
    user = await make_user()
    headers = auth_headers(user)
    url = "/api/v1/spots"
    amenities = dict(has_toilet=True, has_trash_bins=True, is_free=False,
                     price_description="Gecelik 400 TL", camping_behavior_allowed=False)
    response = await api_client.post(url, headers=headers, json={
        "title": "Amenities API test", "category": "campsite",
        "coordinates": {"latitude": 39, "longitude": 33},
        "passability": {"road_type": "asphalt"}, "amenities": amenities,
    })
    assert response.status_code == 201, response.text
    props = response.json()["properties"]
    spot_id = uuid.UUID(props["id"])
    try:
        assert all(props["amenities"][key] == value for key, value in amenities.items())
        response = await api_client.put(f"{url}/{spot_id}", headers=headers,
                                       json={"amenities": {"has_toilet": False}})
        assert response.status_code == 200, response.text
        updated = response.json()["properties"]["amenities"]
        assert not updated["has_toilet"]
        assert updated["has_trash_bins"]
        assert updated["price_description"] == "Gecelik 400 TL"
        assert not updated["camping_behavior_allowed"]
        response = await api_client.patch(f"{url}/{spot_id}", headers=headers,
                                         json={"amenities": {"is_free": True}})
        assert response.status_code == 200, response.text
        assert response.json()["properties"]["amenities"]["price_description"] is None
        response = await api_client.get(f"{url}/{spot_id}")
        assert response.status_code == 200
        assert response.json()["properties"]["amenities"]["is_free"]
    finally:
        await db_session.execute(delete(Spot).where(Spot.id == spot_id))
        await db_session.commit()


async def test_service_partial_update(make_user, make_spot, db_session):
    from app.schemas.spot import SpotUpdate
    from app.schemas.spot_amenities import SpotAmenitiesUpdate
    from app.services.spot_service import update_spot

    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    async def update(**values):
        return await update_spot(db_session, spot_id=spot_id, current_user=user,
                                data=SpotUpdate(amenities=SpotAmenitiesUpdate(**values)))
    result = await update(has_toilet=True, has_trash_bins=True, is_free=False,
                          price_description="Gecelik 400 TL", camping_behavior_allowed=False)
    assert result.properties.amenities.price_description == "Gecelik 400 TL"
    result = await update(has_toilet=False)
    assert not result.properties.amenities.has_toilet
    assert result.properties.amenities.has_trash_bins
    assert not result.properties.amenities.camping_behavior_allowed
    assert result.properties.amenities.price_description == "Gecelik 400 TL"
    result = await update(is_free=True)
    assert result.properties.amenities.price_description is None
