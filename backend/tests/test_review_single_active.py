"""
Kullanıcı+nokta başına TEK aktif değerlendirme kuralı testleri (gerçek Postgres).
Genel puan / boyut ortalamalarının düzenlemede doğru güncellenmesi, superseded
(geçmiş) yorumların sayıma girmemesi ve yarışan eşzamanlı isteklerin çift aktif
yorum oluşturamaması burada doğrulanır.
"""
import asyncio

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.review import Review
from app.models.spot import Spot
from app.schemas.review import DimensionRatings, ReviewCreate, ReviewUpdate
from app.services.review_service import (
    DuplicateReviewError,
    ReviewNotFoundError,
    add_review,
    get_reviews_for_spot,
    get_spot_dimension_ratings,
    update_review,
)
from tests.conftest import auth_headers


async def test_second_review_by_same_user_is_rejected(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=4))

    with pytest.raises(DuplicateReviewError):
        await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=1))
    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None and len(reviews) == 1 and reviews[0].rating == 4


async def test_duplicate_review_via_api_returns_409_and_edit_path_works(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    url = f"/api/v1/spots/{spot_id}/reviews"
    headers = auth_headers(user)

    assert (await api_client.get(f"{url}/me", headers=headers)).json() is None
    first = await api_client.post(url, json={"rating": 5, "comment": "ilk"}, headers=headers)
    assert first.status_code == 201
    second = await api_client.post(url, json={"rating": 2}, headers=headers)
    assert second.status_code == 409
    assert "düzenleyin" in second.json()["detail"]

    mine = (await api_client.get(f"{url}/me", headers=headers)).json()
    assert mine["id"] == first.json()["id"]
    patched = await api_client.patch(f"{url}/{mine['id']}", json={"rating": 3}, headers=headers)
    assert patched.status_code == 200 and patched.json()["rating"] == 3


async def test_concurrent_reviews_from_same_user_create_only_one_active(make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)

    async def attempt(rating: int) -> str:
        async with AsyncSessionLocal() as session:
            try:
                await add_review(session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=rating))
                return "ok"
            except DuplicateReviewError:
                return "duplicate"

    results = await asyncio.gather(*(attempt(r) for r in (1, 2, 3, 4, 5)))
    assert results.count("ok") == 1 and results.count("duplicate") == 4
    async with AsyncSessionLocal() as session:
        reviews = await get_reviews_for_spot(session, spot_id=spot_id)
    assert reviews is not None and len(reviews) == 1


async def _spot_summary(db_session, spot_id):
    await db_session.rollback()  # taze okuma
    row = (
        await db_session.execute(select(Spot.average_rating, Spot.review_count).where(Spot.id == spot_id))
    ).one()
    return row.average_rating, row.review_count


async def test_editing_review_updates_overall_and_dimension_averages(db_session, make_user, make_spot):
    a, b = await make_user("A"), await make_user("B")
    spot_id = await make_spot(created_by=a.id)
    await add_review(
        db_session, spot_id=spot_id, current_user=a,
        data=ReviewCreate(rating=5, dimension_ratings=DimensionRatings(safety=5)),
    )
    rb = await add_review(
        db_session, spot_id=spot_id, current_user=b,
        data=ReviewCreate(rating=1, dimension_ratings=DimensionRatings(safety=1)),
    )
    assert rb is not None

    assert await _spot_summary(db_session, spot_id) == (3.0, 2)
    safety = (await get_spot_dimension_ratings(db_session, spot_id=spot_id)).safety
    assert (safety.average, safety.count) == (3.0, 2)

    await update_review(
        db_session, review_id=rb.id, current_user=b,
        data=ReviewUpdate(rating=5, dimension_ratings=DimensionRatings(safety=5)),
    )
    assert await _spot_summary(db_session, spot_id) == (5.0, 2)
    safety = (await get_spot_dimension_ratings(db_session, spot_id=spot_id)).safety
    assert (safety.average, safety.count) == (5.0, 2)  # çift sayım yok


async def test_superseded_reviews_are_excluded_from_lists_counts_and_edits(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    old = Review(spot_id=spot_id, user_id=user.id, rating=1, comment="eski", is_active=False)
    db_session.add(old)
    await db_session.commit()
    old_id = old.id  # rollback sonrası expired olacağı için şimdi al

    active = await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=5))
    assert active is not None  # pasif eski yorum yeni aktif yorumu engellemez

    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None and [r.rating for r in reviews] == [5]
    assert await _spot_summary(db_session, spot_id) == (5.0, 1)
    with pytest.raises(ReviewNotFoundError):
        await update_review(db_session, review_id=old_id, current_user=user, data=ReviewUpdate(rating=3))
