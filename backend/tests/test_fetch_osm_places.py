"""`scripts/fetch_osm_places.py` - OSM etiket eşlemesi ve tekrar çalıştırılabilir toplu ekleme."""
from sqlalchemy import delete, func, select

from app.models.enums import SpotCategory, SpotSource
from app.models.spot import Spot
from scripts.fetch_osm_places import bulk_insert_spots, classify, element_to_row, elements_to_rows


def test_classify_maps_osm_tags_to_categories():
    assert classify({"amenity": "hospital"}) == SpotCategory.HOSPITAL
    assert classify({"amenity": "clinic"}) == SpotCategory.HEALTH_CENTER
    assert classify({"amenity": "restaurant", "cuisine": "seafood"}) == SpotCategory.FISH_RESTAURANT
    assert classify({"amenity": "restaurant", "cuisine": "turkish;fish"}) == SpotCategory.FISH_RESTAURANT
    assert classify({"amenity": "restaurant", "cuisine": "steak_house"}) == SpotCategory.MEAT_RESTAURANT
    assert classify({"amenity": "restaurant", "cuisine": "regional; meat"}) == SpotCategory.MEAT_RESTAURANT
    assert classify({"tourism": "hotel"}) == SpotCategory.HOTEL_POOL
    assert classify({"leisure": "swimming_pool", "name": "Belediye Havuzu"}) == SpotCategory.HOTEL_POOL
    # Eşleşmeyenler atlanır.
    assert classify({"amenity": "restaurant", "cuisine": "pizza"}) is None
    assert classify({"leisure": "swimming_pool"}) is None  # adsız havuz
    assert classify({"leisure": "swimming_pool", "name": "Site Havuzu", "access": "private"}) is None
    assert classify({"amenity": "pharmacy"}) is None


def test_element_to_row_uses_center_for_ways_and_keeps_useful_tags():
    row = element_to_row({
        "type": "way", "id": 42, "center": {"lat": 37.01, "lon": 35.33},
        "tags": {"amenity": "hospital", "name": "Şehir Hastanesi", "phone": "+90 322 000 00 00",
                 "addr:street": "Atatürk Cd.", "addr:housenumber": "5", "addr:city": "Adana"},
    })
    assert row is not None
    assert row["title"] == "Şehir Hastanesi"
    assert row["source"] == SpotSource.OVERPASS_OSM
    assert row["extra_amenities"]["osm_id"] == "way/42"
    assert row["extra_amenities"]["phone"] == "+90 322 000 00 00"
    assert row["extra_amenities"]["address"] == "Atatürk Cd. 5, Adana"

    unnamed = element_to_row({"type": "node", "id": 7, "lat": 37.0, "lon": 35.3, "tags": {"amenity": "clinic"}})
    assert unnamed is not None and unnamed["title"] == "Sağlık Ocağı (OSM)"
    assert element_to_row({"type": "relation", "id": 1, "tags": {"amenity": "hospital"}}) is None  # konumsuz


async def test_bulk_insert_is_idempotent(db_session):
    # Gerçek veriyle çakışmasın diye okyanusta, (0, 0) civarında.
    elements = [
        {"type": "node", "id": 990000001, "lat": 0.5, "lon": 0.5, "tags": {"amenity": "hospital", "name": "OSM Test Hospital"}},
        {"type": "node", "id": 990000002, "lat": 0.6, "lon": 0.4, "tags": {"amenity": "restaurant", "cuisine": "seafood", "name": "OSM Test Fish"}},
        {"type": "node", "id": 990000002, "lat": 0.6, "lon": 0.4, "tags": {"amenity": "restaurant", "cuisine": "seafood", "name": "OSM Test Fish"}},
    ]
    osm_ids = ["node/990000001", "node/990000002"]
    by_osm_id = Spot.extra_amenities["osm_id"].astext.in_(osm_ids)
    try:
        assert await bulk_insert_spots(db_session, elements_to_rows(elements)) == 2
        # İkinci çalıştırma (yeni uuid'lerle) hiçbir şey eklemez.
        assert await bulk_insert_spots(db_session, elements_to_rows(elements)) == 0
        rows = (await db_session.execute(select(Spot.category, Spot.source).where(by_osm_id))).all()
        assert sorted(r.category.value for r in rows) == ["FISH_RESTAURANT", "HOSPITAL"]
        assert {r.source for r in rows} == {SpotSource.OVERPASS_OSM}
        assert await db_session.scalar(select(func.count()).select_from(Spot).where(by_osm_id)) == 2
    finally:
        await db_session.execute(delete(Spot).where(by_osm_id))
        await db_session.commit()


async def test_imported_spot_without_passability_can_be_edited(db_session, make_user):
    from app.models.enums import UserRole
    from app.schemas.spot import SpotUpdate
    from app.schemas.spot_passability import SpotPassabilityCreate
    from app.services.spot_service import update_spot

    user = await make_user()
    user.role = UserRole.MODERATOR
    await db_session.commit()
    rows = elements_to_rows([
        {"type": "node", "id": 990000003, "lat": 0.5, "lon": 0.5, "tags": {"tourism": "hotel", "name": "OSM Test Hotel"}},
    ])
    spot_id = rows[0]["id"]
    try:
        assert await bulk_insert_spots(db_session, rows) == 1
        feature = await update_spot(
            db_session, spot_id=spot_id, current_user=user,
            data=SpotUpdate(passability=SpotPassabilityCreate(road_type="gravel")),
        )
        assert feature.properties.passability is not None
        assert feature.properties.passability.road_type.value == "gravel"
        assert feature.properties.amenities is None  # içe aktarımda uydurulmaz
    finally:
        await db_session.execute(delete(Spot).where(Spot.id == spot_id))
        await db_session.commit()
