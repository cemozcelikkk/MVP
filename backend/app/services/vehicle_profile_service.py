"""
`vehicle_profiles` (Karavan Profili) veritabanı erişim / iş mantığı katmanı.

Bu modül bilerek router'dan bağımsız, saf bir "veri modeli + iş kuralı"
katmanıdır - gelecekteki uyumluluk motoru (`compatibility_service`, henüz
yok) `get_active_vehicle_profile`'ı doğrudan çağırıp bir `SpotPassability`
ile karşılaştıracak. Aynı şekilde React Native/Expo istemcisi de web
frontend'iyle birebir aynı `/vehicle-profiles` API'sini (henüz eklenmedi,
bkz. router katmanı) kullanacak - hesaplama/doğrulama mantığı burada,
istemciye gömülü değil.

## "Tek aktif profil" garantisi

`VehicleProfile.is_active` üzerinde kullanıcı başına en fazla bir `true`
satır olabilir. Bu iki katmanda uygulanır:

1. DB: kısmi (partial) unique index - `uq_vehicle_profiles_one_active_per_user`
   (bkz. `app.models.vehicle_profile`). Son söz, race'te bile ihlal
   edilemez.
2. Bu modül: bir profili aktif yapmadan ÖNCE `pg_advisory_xact_lock` ile
   o kullanıcı için bir "kritik bölge" açar, ardından varsa mevcut aktif
   profili deaktive edip yenisini aktif yapar - hepsi TEK transaction
   (commit/rollback ile kilit otomatik serbest kalır). Satır bazlı
   `SELECT ... FOR UPDATE` yerine advisory lock tercih edildi çünkü
   kullanıcının aktifleştirilecek İLK profilinde kilitlenecek satır henüz
   yok - advisory lock user_id üzerinden çalıştığı için bu durumda da
   eşzamanlı iki "ilk profil" isteğini doğru sıralar.
"""
import uuid

from sqlalchemy import select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_profile import VehicleProfile
from app.schemas.vehicle_profile import VehicleProfileCreate, VehicleProfileUpdate


class VehicleProfileNotFoundError(Exception):
    """Profil yok."""


class VehicleProfilePermissionError(Exception):
    """Profil, istek sahibi kullanıcıya ait değil."""


async def _lock_user_vehicle_profiles(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Bkz. modül docstring'i - bu kullanıcı için aktif-profil geçişlerini serileştirir."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:user_id))"), {"user_id": str(user_id)})


async def _deactivate_current_active(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    await db.execute(
        sa_update(VehicleProfile)
        .where(VehicleProfile.user_id == user_id, VehicleProfile.is_active.is_(True))
        .values(is_active=False)
    )


async def _get_owned_profile(
    db: AsyncSession, *, profile_id: uuid.UUID, user_id: uuid.UUID
) -> VehicleProfile:
    profile = await db.get(VehicleProfile, profile_id)
    if profile is None:
        raise VehicleProfileNotFoundError(profile_id)
    if profile.user_id != user_id:
        raise VehicleProfilePermissionError(profile_id)
    return profile


async def list_vehicle_profiles(db: AsyncSession, *, user_id: uuid.UUID) -> list[VehicleProfile]:
    """Aktif profil en üstte, sonra en yeni oluşturulan."""
    stmt = (
        select(VehicleProfile)
        .where(VehicleProfile.user_id == user_id)
        .order_by(VehicleProfile.is_active.desc(), VehicleProfile.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_vehicle_profile(
    db: AsyncSession, *, profile_id: uuid.UUID, user_id: uuid.UUID
) -> VehicleProfile:
    """Raises: VehicleProfileNotFoundError, VehicleProfilePermissionError."""
    return await _get_owned_profile(db, profile_id=profile_id, user_id=user_id)


async def get_active_vehicle_profile(db: AsyncSession, *, user_id: uuid.UUID) -> VehicleProfile | None:
    """Uyumluluk motorunun kullanacağı asıl sorgu - kullanıcının hiç aktif
    profili yoksa `None` döner (çağıran taraf bunu `insufficient_data`
    olarak yorumlamalı, hata değil)."""
    return await db.scalar(
        select(VehicleProfile).where(
            VehicleProfile.user_id == user_id, VehicleProfile.is_active.is_(True)
        )
    )


async def create_vehicle_profile(
    db: AsyncSession, *, user_id: uuid.UUID, data: VehicleProfileCreate
) -> VehicleProfile:
    """
    `data.is_active=True` ise VEYA kullanıcının bu ilk profiliyse aktif
    yapılır (bir kullanıcı en az bir profili varken "hiç aktif profilim
    yok" durumunda başlamamalı - UX olarak kafa karıştırır). Diğer
    durumlarda pasif oluşturulur.
    """
    await _lock_user_vehicle_profiles(db, user_id=user_id)

    has_existing = await db.scalar(
        select(VehicleProfile.id).where(VehicleProfile.user_id == user_id).limit(1)
    )
    should_be_active = data.is_active or has_existing is None
    if should_be_active:
        await _deactivate_current_active(db, user_id=user_id)

    profile = VehicleProfile(
        user_id=user_id,
        name=data.name,
        vehicle_type=data.vehicle_type,
        length_m=data.length_m,
        width_m=data.width_m,
        height_m=data.height_m,
        weight_kg=data.weight_kg,
        drivetrain=data.drivetrain,
        has_grey_water_tank=data.has_grey_water_tank,
        has_black_water_cassette=data.has_black_water_cassette,
        has_solar_power=data.has_solar_power,
        travels_with_pet=data.travels_with_pet,
        is_active=should_be_active,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile, attribute_names=["created_at", "updated_at"])
    await db.commit()
    return profile


async def update_vehicle_profile(
    db: AsyncSession, *, profile_id: uuid.UUID, user_id: uuid.UUID, data: VehicleProfileUpdate
) -> VehicleProfile:
    """Raises: VehicleProfileNotFoundError, VehicleProfilePermissionError."""
    # Kilit, olası bir aktifleştirmeden ÖNCE alınmalı - profili bulmak
    # kilit gerektirmez (henüz bu kullanıcının aktif-profil durumunu
    # değiştirmiyoruz), o yüzden önce sahiplik kontrolü yapılıyor.
    profile = await _get_owned_profile(db, profile_id=profile_id, user_id=user_id)

    activating = data.is_active is True and not profile.is_active
    if activating:
        await _lock_user_vehicle_profiles(db, user_id=user_id)
        await _deactivate_current_active(db, user_id=user_id)

    update_data = data.model_dump(exclude_unset=True, exclude={"is_active"})
    for field, value in update_data.items():
        setattr(profile, field, value)

    if activating:
        profile.is_active = True
    elif data.is_active is False:
        # Kullanıcı bilinçli olarak kendi tek aktif profilini pasifleştiriyor.
        profile.is_active = False

    await db.flush()
    await db.refresh(profile, attribute_names=["updated_at"])
    await db.commit()
    return profile


async def set_active_vehicle_profile(
    db: AsyncSession, *, profile_id: uuid.UUID, user_id: uuid.UUID
) -> VehicleProfile:
    """
    `POST /vehicle-profiles/{id}/activate` - bu profili aktif yapar, aynı
    kullanıcının varsa önceki aktif profilini aynı transaction içinde
    deaktive eder. Zaten aktifse no-op (yine de güncel nesneyi döner).

    Raises: VehicleProfileNotFoundError, VehicleProfilePermissionError.
    """
    profile = await _get_owned_profile(db, profile_id=profile_id, user_id=user_id)
    if profile.is_active:
        return profile

    await _lock_user_vehicle_profiles(db, user_id=user_id)
    await _deactivate_current_active(db, user_id=user_id)
    profile.is_active = True

    await db.flush()
    await db.refresh(profile, attribute_names=["updated_at"])
    await db.commit()
    return profile


async def delete_vehicle_profile(db: AsyncSession, *, profile_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """
    Raises: VehicleProfileNotFoundError, VehicleProfilePermissionError.

    Not: silinen profil aktifse, kullanıcı BİLEREK "hiç aktif profilim
    yok" durumuna düşer - otomatik olarak başka bir profili aktif YAPMAZ
    (hangi profilin seçileceği ürün kararı, sessizce tahmin etmiyoruz).
    """
    profile = await _get_owned_profile(db, profile_id=profile_id, user_id=user_id)
    await db.delete(profile)
    await db.commit()
