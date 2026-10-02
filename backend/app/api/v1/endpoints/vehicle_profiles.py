"""`/api/v1/vehicle-profiles` altındaki karavan/araç profili CRUD uçları.

Tüm uçlar kimlik doğrulaması gerektirir (bkz. `get_current_user`); bir
kullanıcı yalnızca KENDİ profillerini okuyabilir/düzenleyebilir/silebilir/
aktifleştirebilir - sahiplik kontrolü `vehicle_profile_service` içinde
(`VehicleProfilePermissionError`) yapılır, router sadece 403'e çevirir.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.vehicle_profile import (
    VehicleProfileCreate,
    VehicleProfileRead,
    VehicleProfileUpdate,
)
from app.services.vehicle_profile_service import (
    VehicleProfileNotFoundError,
    VehicleProfilePermissionError,
    create_vehicle_profile,
    delete_vehicle_profile,
    get_vehicle_profile,
    list_vehicle_profiles,
    set_active_vehicle_profile,
    update_vehicle_profile,
)

router = APIRouter(prefix="/vehicle-profiles", tags=["vehicle-profiles"])


@router.get("", response_model=list[VehicleProfileRead])
async def list_vehicle_profiles_endpoint(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VehicleProfileRead]:
    """Kullanıcının tüm araç profillerini döner (aktif olan en üstte)."""
    profiles = await list_vehicle_profiles(db, user_id=current_user.id)
    return [VehicleProfileRead.model_validate(p) for p in profiles]


@router.post("", response_model=VehicleProfileRead, status_code=status.HTTP_201_CREATED)
async def create_vehicle_profile_endpoint(
    payload: VehicleProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VehicleProfileRead:
    """
    Yeni bir araç profili oluşturur. Kullanıcının bu ilk profiliyse VEYA
    `is_active: true` gönderildiyse otomatik aktif olur - varsa önceki aktif
    profil aynı transaction içinde deaktive edilir (bkz.
    `vehicle_profile_service.create_vehicle_profile`).
    """
    profile = await create_vehicle_profile(db, user_id=current_user.id, data=payload)
    return VehicleProfileRead.model_validate(profile)


@router.get("/{profile_id}", response_model=VehicleProfileRead)
async def read_vehicle_profile_endpoint(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VehicleProfileRead:
    try:
        profile = await get_vehicle_profile(db, profile_id=profile_id, user_id=current_user.id)
    except VehicleProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç profili bulunamadı.")
    except VehicleProfilePermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu araç profilini görüntüleme yetkiniz yok."
        )
    return VehicleProfileRead.model_validate(profile)


@router.patch("/{profile_id}", response_model=VehicleProfileRead)
async def update_vehicle_profile_endpoint(
    profile_id: uuid.UUID,
    payload: VehicleProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VehicleProfileRead:
    """
    Profili kısmen günceller (PATCH semantiği - gönderilmeyen alanlar
    değişmez). `is_active: true` gönderilirse bu profil aktif olur, varsa
    önceki aktif profil aynı transaction içinde deaktive edilir.
    """
    try:
        profile = await update_vehicle_profile(
            db, profile_id=profile_id, user_id=current_user.id, data=payload
        )
    except VehicleProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç profili bulunamadı.")
    except VehicleProfilePermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu araç profilini düzenleme yetkiniz yok."
        )
    return VehicleProfileRead.model_validate(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle_profile_endpoint(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_vehicle_profile(db, profile_id=profile_id, user_id=current_user.id)
    except VehicleProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç profili bulunamadı.")
    except VehicleProfilePermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu araç profilini silme yetkiniz yok."
        )


@router.post("/{profile_id}/activate", response_model=VehicleProfileRead)
async def activate_vehicle_profile_endpoint(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VehicleProfileRead:
    """Bu profili aktif yapar; kullanıcının varsa önceki aktif profili deaktive edilir."""
    try:
        profile = await set_active_vehicle_profile(db, profile_id=profile_id, user_id=current_user.id)
    except VehicleProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç profili bulunamadı.")
    except VehicleProfilePermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu araç profilini aktifleştirme yetkiniz yok."
        )
    return VehicleProfileRead.model_validate(profile)
