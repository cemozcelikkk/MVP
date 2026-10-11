"""Eski restoran/sağlık `spots` kayıtlarının yeni modele geçişi: belirsiz kayıtlar
otomatik taşınmaz, moderatör kararıyla ve VERİ KAYBETMEDEN ele alınır."""
import ast
import re
import uuid
from pathlib import Path

import pytest_asyncio
from sqlalchemy import delete, select

from app.models.check_in import CheckIn
from app.models.enums import SpotCategory, UserRole
from app.models.review import Review
from app.models.service_point import ServicePoint, ServicePointReview
from app.models.spot import Spot
from app.services import category_migration
from app.utils.geo import lonlat_to_wkb
from tests.conftest import auth_headers

MIGRATION = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "e3a9c5d1f7b4_add_service_points.py"
QUEUE = "/api/v1/moderation/category-review"


def test_migration_uses_the_same_rules_as_the_service_module():
    """Migration bağımsız bir kopya taşır; kurallar ayrışırsa rapor ile gerçek taşıma farklı olur."""
    source = MIGRATION.read_text(encoding="utf-8")
    literal = re.search(r"_CAMP_SIGNALS = (\[.*?\n\])", source, re.S).group(1)
    assert ast.literal_eval(literal) == category_migration.CAMP_SIGNALS


@pytest_asyncio.fixture
async def legacy_spots(db_session, make_user):
    """Eski kategorilerde iki kayıt: temiz bir balıkçı ve check-in'i olan (belirsiz) bir et restoranı."""
    user = await make_user()
    clean = Spot(title="Eski Temiz Balıkçı", category=SpotCategory.FISH_RESTAURANT,
                 coordinates=lonlat_to_wkb(2.61, 2.61), is_verified=False)
    ambiguous = Spot(title="Eski Gecelemeli Kebapçı", category=SpotCategory.MEAT_RESTAURANT,
                     coordinates=lonlat_to_wkb(2.62, 2.62), is_verified=False, review_count=1, average_rating=4)
    db_session.add_all([clean, ambiguous])
    await db_session.flush()
    db_session.add(CheckIn(spot_id=ambiguous.id, user_id=user.id))
    db_session.add(Review(spot_id=ambiguous.id, user_id=user.id, rating=4, comment="karavanla kaldık"))
    await db_session.commit()
    clean_id, ambiguous_id = clean.id, ambiguous.id
    ids = {"clean": clean_id, "ambiguous": ambiguous_id, "user": user}
    yield ids
    # Check-in/yorum satırları açıkça silinir ve oturum tazelenir; aksi halde make_user'ın
    # ORM silmesi oturumdaki CheckIn'in user_id'sini NULL'lamaya çalışır.
    await db_session.execute(delete(CheckIn).where(CheckIn.spot_id.in_([clean_id, ambiguous_id])))
    await db_session.execute(delete(Review).where(Review.spot_id.in_([clean_id, ambiguous_id])))
    await db_session.execute(delete(ServicePoint).where(ServicePoint.id.in_([clean_id, ambiguous_id])))
    await db_session.execute(delete(Spot).where(Spot.id.in_([clean_id, ambiguous_id])))
    await db_session.commit()
    db_session.expire_all()


async def test_classification_flags_camp_data_and_moves_only_clean_records(db_session, legacy_spots):
    rows = {row["id"]: row for row in await category_migration.classify_legacy_spots(db_session)}
    assert rows[legacy_spots["clean"]]["decision"] == "move"
    assert rows[legacy_spots["ambiguous"]]["decision"] == "review"
    assert rows[legacy_spots["ambiguous"]]["reasons"] == ["check_in"]


async def _flag_pending(db_session, spot_id):
    spot = await db_session.get(Spot, spot_id)
    spot.extra_amenities = {"category_review": "pending", "category_review_reasons": "check_in"}
    await db_session.commit()


async def test_moderator_queue_and_keep_as_camping(api_client, db_session, legacy_spots, make_user):
    moderator = await make_user()
    moderator.role = UserRole.MODERATOR
    await db_session.commit()
    mod_headers = auth_headers(moderator)  # expire_all sonrası moderator.id okunamaz
    await _flag_pending(db_session, legacy_spots["ambiguous"])

    assert (await api_client.get(QUEUE, headers=auth_headers(legacy_spots["user"]))).status_code == 403
    queue = (await api_client.get(QUEUE, headers=mod_headers)).json()
    item = next(i for i in queue if i["spot_id"] == str(legacy_spots["ambiguous"]))
    assert item["reasons"] == ["check_in"] and item["reason_labels"] == ["check-in kaydı var"]

    decided = await api_client.post(
        f"{QUEUE}/{legacy_spots['ambiguous']}", json={"action": "keep_as_camping"}, headers=mod_headers
    )
    assert decided.status_code == 200, decided.text
    db_session.expire_all()
    spot = await db_session.get(Spot, legacy_spots["ambiguous"])
    assert spot.category is SpotCategory.CAMPING and spot.deleted_at is None
    assert "category_review" not in spot.extra_amenities
    # Kamp verisi yerinde: check-in ve 7 boyutlu sisteme ait yorum kaybolmadı.
    assert await db_session.scalar(select(CheckIn.id).where(CheckIn.spot_id == spot.id)) is not None
    assert await db_session.scalar(select(Review.id).where(Review.spot_id == spot.id)) is not None
    again = await api_client.post(
        f"{QUEUE}/{legacy_spots['ambiguous']}", json={"action": "keep_as_camping"}, headers=mod_headers
    )
    assert again.status_code == 409


async def test_move_to_service_keeps_id_reviews_and_original_rows(api_client, db_session, legacy_spots, make_user):
    moderator = await make_user()
    moderator.role = UserRole.MODERATOR
    await db_session.commit()
    mod_headers = auth_headers(moderator)  # expire_all sonrası moderator.id okunamaz
    spot_id = legacy_spots["ambiguous"]
    await _flag_pending(db_session, spot_id)

    moved = await api_client.post(f"{QUEUE}/{spot_id}", json={"action": "move_to_service"}, headers=mod_headers)
    assert moved.status_code == 200, moved.text
    assert moved.json()["service_point_id"] == str(spot_id)

    point = (await api_client.get(f"/api/v1/service-points/{spot_id}")).json()["properties"]
    assert point["category"] == "MEAT_RESTAURANT" and point["name"] == "Eski Gecelemeli Kebapçı"
    assert point["review_count"] == 1 and point["average_rating"] == 4.0
    db_session.expire_all()
    spot = await db_session.get(Spot, spot_id)
    assert spot.deleted_at is not None and spot.extra_amenities["moved_to_service_points"] is True
    # Orijinal satırlar silinmez.
    assert await db_session.scalar(select(Review.id).where(Review.spot_id == spot_id)) is not None
    assert await db_session.scalar(select(CheckIn.id).where(CheckIn.spot_id == spot_id)) is not None
    copied = (await db_session.scalars(select(ServicePointReview).where(ServicePointReview.service_point_id == spot_id))).all()
    assert [(r.rating, r.comment) for r in copied] == [(4, "karavanla kaldık")]
