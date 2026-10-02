"""
`review_service` için entegrasyon testleri (gerçek Postgres - bkz.
`conftest.py`). Kapsam, görev tanımındaki kabul ölçütleriyle birebir eşlenir:

- Eski yorumların yeni alanlar olmadan okunması
- Kısmi boyut puanı gönderimi
- 1-5 dışındaki değerlerin reddi
- Boş boyutların ortalamaya katılmaması
- Her boyut için doğru ortalama ve değerlendirme sayısı
- Araç profilinin sonradan değiştirilmesi/silinmesinin geçmiş yorumu etkilememesi
- Check-in olan/olmayan yorumlarda doğrulama ibaresinin doğru hesaplanması
- Başka kullanıcıya ait yorumu değiştirme girişiminin engellenmesi
"""
import pytest
from pydantic import ValidationError

from app.models.check_in import CheckIn
from app.models.enums import Drivetrain, VehicleType
from app.schemas.review import DimensionRatings, ReviewCreate, ReviewUpdate
from app.schemas.vehicle_profile import VehicleProfileCreate, VehicleProfileUpdate
from app.services.review_service import (
    ReviewPermissionError,
    add_review,
    get_reviews_for_spot,
    get_spot_dimension_ratings,
    update_review,
)
from app.services.vehicle_profile_service import (
    create_vehicle_profile,
    delete_vehicle_profile,
    update_vehicle_profile,
)

# --- Eski yorumların yeni alanlar olmadan okunması --------------------------


async def test_review_without_new_fields_reads_with_safe_defaults(db_session, make_user, make_spot):
    """Araç profili YOK, dimension_ratings YOK - eski bir yorumun (bu davranışla
    oluşturulmuş) yeni alanlar olmadan da sorunsuz okunabildiğini doğrular."""
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)

    created = await add_review(
        db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=4, comment="Fena değil")
    )
    assert created is not None
    assert created.rating == 4
    assert created.comment == "Fena değil"
    assert created.vehicle_snapshot is None  # kullanıcının aktif aracı yok
    assert created.is_verified_checkin is False
    assert all(getattr(created.dimension_ratings, key) is None for key in DimensionRatings.model_fields)

    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None and len(reviews) == 1
    assert reviews[0].rating == 4
    assert reviews[0].vehicle_snapshot is None


# --- Kısmi boyut puanı gönderimi --------------------------------------------


async def test_partial_dimension_rating_submission(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)

    created = await add_review(
        db_session,
        spot_id=spot_id,
        current_user=user,
        data=ReviewCreate(rating=5, dimension_ratings=DimensionRatings(safety=5)),
    )
    assert created is not None
    assert created.dimension_ratings.safety == 5
    assert created.dimension_ratings.quietness is None
    assert created.dimension_ratings.road_access is None
    assert created.dimension_ratings.signal is None


# --- 1-5 dışındaki değerlerin reddi ------------------------------------------


def test_overall_rating_outside_1_5_is_rejected():
    with pytest.raises(ValidationError):
        ReviewCreate(rating=0)
    with pytest.raises(ValidationError):
        ReviewCreate(rating=6)


def test_dimension_rating_outside_1_5_is_rejected():
    with pytest.raises(ValidationError):
        DimensionRatings(safety=0)
    with pytest.raises(ValidationError):
        DimensionRatings(quietness=6)


# --- Boş boyutların ortalamaya katılmaması + doğru ortalama/adet ------------


async def test_empty_dimensions_do_not_count_toward_average_and_counts_are_correct(
    db_session, make_user, make_spot
):
    owner = await make_user("Sahip")
    spot_id = await make_spot(created_by=owner.id)

    raters = [await make_user(f"Puanlayan{i}") for i in range(3)]
    # safety: 3, 4, 5 (üç kişi) -> ortalama 4.0, adet 3.
    for rater, safety_value in zip(raters, (3, 4, 5), strict=True):
        await add_review(
            db_session,
            spot_id=spot_id,
            current_user=rater,
            data=ReviewCreate(rating=4, dimension_ratings=DimensionRatings(safety=safety_value)),
        )
    # Dördüncü kişi safety'yi BOŞ bırakıyor (sadece quietness veriyor).
    fourth = await make_user("Puanlamayan")
    await add_review(
        db_session,
        spot_id=spot_id,
        current_user=fourth,
        data=ReviewCreate(rating=3, dimension_ratings=DimensionRatings(quietness=2)),
    )

    stats = await get_spot_dimension_ratings(db_session, spot_id=spot_id)
    # Boş bırakan 4. kişi safety ortalamasını 0 gibi ÇEKMEMELİ - hâlâ 4.0/3.
    assert stats.safety.average == 4.0
    assert stats.safety.count == 3
    assert stats.quietness.average == 2.0
    assert stats.quietness.count == 1
    assert stats.road_access.average is None
    assert stats.road_access.count == 0


async def test_single_rater_dimension_has_count_one_not_conflated_with_many(db_session, make_user, make_spot):
    """'Bir kişinin puanladığı ölçüt, çok kişinin puanladığıyla aynı kesinlikte sunulmasın' -
    API bunu `count` alanıyla ayırt edilebilir kılıyor; bu test o alanın DOĞRU geldiğini doğrular."""
    owner = await make_user()
    spot_id = await make_spot(created_by=owner.id)
    await add_review(
        db_session,
        spot_id=spot_id,
        current_user=owner,
        data=ReviewCreate(rating=5, dimension_ratings=DimensionRatings(view=5)),
    )
    stats = await get_spot_dimension_ratings(db_session, spot_id=spot_id)
    assert stats.view.count == 1
    assert stats.view.average == 5.0


# --- Araç profili sonradan değişse/silinse de geçmiş yorum etkilenmez ------


async def test_vehicle_snapshot_survives_profile_edit_and_delete(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)

    profile = await create_vehicle_profile(
        db_session,
        user_id=user.id,
        data=VehicleProfileCreate(
            name="Ducato", vehicle_type=VehicleType.CAMPERVAN, length_m=6.4, drivetrain=Drivetrain.TWO_WHEEL_DRIVE
        ),
    )

    review = await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=5))
    assert review is not None
    assert review.vehicle_snapshot is not None
    assert review.vehicle_snapshot.vehicle_type == VehicleType.CAMPERVAN
    assert review.vehicle_snapshot.length_m == 6.4

    # Profili DEĞİŞTİR (tür + uzunluk).
    await update_vehicle_profile(
        db_session,
        profile_id=profile.id,
        user_id=user.id,
        data=VehicleProfileUpdate(vehicle_type=VehicleType.MOTORHOME, length_m=8.0),
    )
    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None
    assert reviews[0].vehicle_snapshot.vehicle_type == VehicleType.CAMPERVAN  # DEĞİŞMEDİ
    assert reviews[0].vehicle_snapshot.length_m == 6.4  # DEĞİŞMEDİ

    # Profili SİL.
    await delete_vehicle_profile(db_session, profile_id=profile.id, user_id=user.id)
    reviews_after_delete = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews_after_delete is not None
    assert reviews_after_delete[0].vehicle_snapshot.vehicle_type == VehicleType.CAMPERVAN
    assert reviews_after_delete[0].vehicle_snapshot.length_m == 6.4


async def test_review_created_without_active_vehicle_has_no_snapshot(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    review = await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=3))
    assert review is not None
    assert review.vehicle_snapshot is None


# --- Check-in doğrulama ibaresi ---------------------------------------------


async def test_verified_checkin_badge_true_when_reviewer_has_checkin(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=5))

    db_session.add(CheckIn(spot_id=spot_id, user_id=user.id))
    await db_session.commit()

    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None
    assert reviews[0].is_verified_checkin is True


async def test_verified_checkin_badge_false_without_checkin(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await add_review(db_session, spot_id=spot_id, current_user=user, data=ReviewCreate(rating=5))

    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None
    assert reviews[0].is_verified_checkin is False


async def test_verified_checkin_badge_not_leaked_from_another_users_checkin(db_session, make_user, make_spot):
    """Başka bir kullanıcının check-in'i, BU yorumun yazarını yanlışlıkla doğrulamamalı."""
    reviewer = await make_user("Yorumcu")
    other = await make_user("Başkası")
    spot_id = await make_spot(created_by=reviewer.id)
    await add_review(db_session, spot_id=spot_id, current_user=reviewer, data=ReviewCreate(rating=5))

    db_session.add(CheckIn(spot_id=spot_id, user_id=other.id))
    await db_session.commit()

    reviews = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert reviews is not None
    assert reviews[0].is_verified_checkin is False


# --- Sahiplik / yetki --------------------------------------------------------


async def test_cannot_update_another_users_review(db_session, make_user, make_spot):
    owner = await make_user("Sahip")
    other = await make_user("Başkası")
    spot_id = await make_spot(created_by=owner.id)
    review = await add_review(
        db_session, spot_id=spot_id, current_user=owner, data=ReviewCreate(rating=3, comment="Orijinal")
    )
    assert review is not None

    with pytest.raises(ReviewPermissionError):
        await update_review(
            db_session, review_id=review.id, current_user=other, data=ReviewUpdate(comment="Ele geçirildi")
        )

    unchanged = await get_reviews_for_spot(db_session, spot_id=spot_id)
    assert unchanged is not None
    assert unchanged[0].comment == "Orijinal"


async def test_owner_can_update_own_review_and_clear_a_dimension(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    review = await add_review(
        db_session,
        spot_id=spot_id,
        current_user=user,
        data=ReviewCreate(rating=3, dimension_ratings=DimensionRatings(safety=2, quietness=3)),
    )
    assert review is not None

    updated = await update_review(
        db_session,
        review_id=review.id,
        current_user=user,
        data=ReviewUpdate(dimension_ratings=DimensionRatings(safety=None)),
    )
    assert updated.dimension_ratings.safety is None  # "Değerlendirmedim"e döndü
    assert updated.dimension_ratings.quietness == 3  # dokunulmadı
