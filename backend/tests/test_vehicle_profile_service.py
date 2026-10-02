"""
`vehicle_profile_service` için entegrasyon testleri (gerçek Postgres -
bkz. `conftest.py`). Kapsam:

- Sahiplik: başka bir kullanıcının profiline erişim/düzenleme/silme/
  aktifleştirme her zaman `VehicleProfilePermissionError` ile reddedilir.
- "Tek aktif profil" garantisi: bir profili aktif yapmak öncekini
  deaktive eder; kullanıcı ASLA birden fazla aktif profile sahip olamaz -
  hem servis akışları hem DB'nin kendi kısmi (partial) unique index'i
  üzerinden ayrı ayrı doğrulanır.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.enums import Drivetrain, VehicleType
from app.models.vehicle_profile import VehicleProfile
from app.schemas.vehicle_profile import VehicleProfileCreate, VehicleProfileUpdate
from app.services.vehicle_profile_service import (
    VehicleProfileNotFoundError,
    VehicleProfilePermissionError,
    create_vehicle_profile,
    delete_vehicle_profile,
    get_active_vehicle_profile,
    get_vehicle_profile,
    list_vehicle_profiles,
    set_active_vehicle_profile,
    update_vehicle_profile,
)


def _create_payload(**overrides) -> VehicleProfileCreate:
    defaults = {
        "name": "Test Aracı",
        "vehicle_type": VehicleType.MOTORHOME,
        "length_m": 6.0,
        "drivetrain": Drivetrain.TWO_WHEEL_DRIVE,
    }
    defaults.update(overrides)
    return VehicleProfileCreate(**defaults)


# --- Sahiplik / erişim kontrolü --------------------------------------------


async def test_get_nonexistent_profile_raises_not_found(db_session, make_user):
    user = await make_user()
    with pytest.raises(VehicleProfileNotFoundError):
        await get_vehicle_profile(db_session, profile_id=uuid.uuid4(), user_id=user.id)


async def test_cannot_read_another_users_profile(db_session, make_user):
    owner = await make_user("Sahip")
    other = await make_user("Başkası")
    profile = await create_vehicle_profile(db_session, user_id=owner.id, data=_create_payload())

    with pytest.raises(VehicleProfilePermissionError):
        await get_vehicle_profile(db_session, profile_id=profile.id, user_id=other.id)


async def test_cannot_edit_another_users_profile(db_session, make_user):
    owner = await make_user("Sahip")
    other = await make_user("Başkası")
    profile = await create_vehicle_profile(db_session, user_id=owner.id, data=_create_payload())

    with pytest.raises(VehicleProfilePermissionError):
        await update_vehicle_profile(
            db_session, profile_id=profile.id, user_id=other.id, data=VehicleProfileUpdate(name="Ele Geçirildi")
        )
    # Gerçekten değişmemiş olmalı.
    unchanged = await get_vehicle_profile(db_session, profile_id=profile.id, user_id=owner.id)
    assert unchanged.name == "Test Aracı"


async def test_cannot_delete_another_users_profile(db_session, make_user):
    owner = await make_user("Sahip")
    other = await make_user("Başkası")
    profile = await create_vehicle_profile(db_session, user_id=owner.id, data=_create_payload())

    with pytest.raises(VehicleProfilePermissionError):
        await delete_vehicle_profile(db_session, profile_id=profile.id, user_id=other.id)
    # Silinmemiş olmalı.
    still_there = await get_vehicle_profile(db_session, profile_id=profile.id, user_id=owner.id)
    assert still_there is not None


async def test_cannot_activate_another_users_profile(db_session, make_user):
    owner = await make_user("Sahip")
    other = await make_user("Başkası")
    profile = await create_vehicle_profile(db_session, user_id=owner.id, data=_create_payload(is_active=False))

    with pytest.raises(VehicleProfilePermissionError):
        await set_active_vehicle_profile(db_session, profile_id=profile.id, user_id=other.id)


# --- "Tek aktif profil" garantisi ------------------------------------------


async def test_first_profile_is_automatically_active(db_session, make_user):
    user = await make_user()
    profile = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload())
    assert profile.is_active is True


async def test_second_profile_created_inactive_by_default(db_session, make_user):
    user = await make_user()
    await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="Birinci"))
    second = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="İkinci"))
    assert second.is_active is False


async def test_creating_profile_with_is_active_true_deactivates_previous(db_session, make_user):
    user = await make_user()
    first = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="Birinci"))
    assert first.is_active is True

    second = await create_vehicle_profile(
        db_session, user_id=user.id, data=_create_payload(name="İkinci", is_active=True)
    )
    assert second.is_active is True

    refreshed_first = await get_vehicle_profile(db_session, profile_id=first.id, user_id=user.id)
    assert refreshed_first.is_active is False


async def test_activating_a_profile_deactivates_the_previous_active_one(db_session, make_user):
    """Görev tanımı: 'Aktif araç değiştirilince önceki aracın pasif olması'."""
    user = await make_user()
    p1 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="A"))
    p2 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="B"))
    assert p1.is_active is True
    assert p2.is_active is False

    activated = await set_active_vehicle_profile(db_session, profile_id=p2.id, user_id=user.id)
    assert activated.is_active is True

    refreshed_p1 = await get_vehicle_profile(db_session, profile_id=p1.id, user_id=user.id)
    assert refreshed_p1.is_active is False

    active_profile = await get_active_vehicle_profile(db_session, user_id=user.id)
    assert active_profile is not None and active_profile.id == p2.id


async def test_activating_already_active_profile_is_a_noop(db_session, make_user):
    user = await make_user()
    p1 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload())
    result = await set_active_vehicle_profile(db_session, profile_id=p1.id, user_id=user.id)
    assert result.is_active is True


async def test_update_with_is_active_true_switches_the_active_profile(db_session, make_user):
    user = await make_user()
    p1 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="A"))
    p2 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="B"))

    await update_vehicle_profile(
        db_session, profile_id=p2.id, user_id=user.id, data=VehicleProfileUpdate(is_active=True)
    )

    profiles = await list_vehicle_profiles(db_session, user_id=user.id)
    active_ones = [p for p in profiles if p.is_active]
    assert len(active_ones) == 1
    assert active_ones[0].id == p2.id
    assert p1.id != active_ones[0].id


async def test_user_never_has_more_than_one_active_profile_across_many_operations(db_session, make_user):
    """Görev tanımı: 'Kullanıcının yalnızca bir aktif aracı bulunması' - birden çok işlem sonrası da geçerli."""
    user = await make_user()
    p1 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="A"))
    p2 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="B", is_active=True))
    p3 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="C"))

    await set_active_vehicle_profile(db_session, profile_id=p3.id, user_id=user.id)
    await update_vehicle_profile(
        db_session, profile_id=p1.id, user_id=user.id, data=VehicleProfileUpdate(is_active=True)
    )
    await set_active_vehicle_profile(db_session, profile_id=p2.id, user_id=user.id)

    profiles = await list_vehicle_profiles(db_session, user_id=user.id)
    assert len(profiles) == 3
    active_ones = [p for p in profiles if p.is_active]
    assert len(active_ones) == 1
    assert active_ones[0].id == p2.id


async def test_deleting_active_profile_leaves_user_without_active_profile(db_session, make_user):
    """Servis BİLEREK başka bir profili otomatik aktif YAPMIYOR (bkz. delete_vehicle_profile docstring'i)."""
    user = await make_user()
    p1 = await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="A"))
    await create_vehicle_profile(db_session, user_id=user.id, data=_create_payload(name="B"))

    await delete_vehicle_profile(db_session, profile_id=p1.id, user_id=user.id)

    active_profile = await get_active_vehicle_profile(db_session, user_id=user.id)
    assert active_profile is None


async def test_db_partial_unique_index_rejects_two_active_rows_directly(make_user):
    """
    Servis katmanını BYPASS EDİP doğrudan iki aktif satır eklemeyi dener -
    DB'nin kendi `uq_vehicle_profiles_one_active_per_user` kısmi unique
    index'inin, servis mantığından BAĞIMSIZ olarak da son sözü söylediğini
    doğrular (bkz. app.models.vehicle_profile docstring'i).

    Bilerek AYRI bir session (`AsyncSessionLocal()`) açıyor - başarısız bir
    `commit()`den sonraki `rollback()`, SQLAlchemy'de session'daki TÜM
    nesneleri "expired" işaretler; bunu paylaşılan `db_session`/`make_user`
    fixture'ının session'ında yapmak, testin kendi teardown'ında (senkron
    attribute erişimiyle) bir `MissingGreenlet` hatasına yol açardı.
    """
    user = await make_user()
    async with AsyncSessionLocal() as raw_session:
        raw_session.add(
            VehicleProfile(user_id=user.id, name="A", vehicle_type=VehicleType.OTHER, length_m=5.0, is_active=True)
        )
        await raw_session.commit()

        raw_session.add(
            VehicleProfile(user_id=user.id, name="B", vehicle_type=VehicleType.OTHER, length_m=5.0, is_active=True)
        )
        with pytest.raises(IntegrityError):
            await raw_session.commit()
        await raw_session.rollback()
