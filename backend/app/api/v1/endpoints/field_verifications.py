"""`/api/v1/spots/{spot_id}/field-freshness` ve `/verifications` endpoint'leri.

Ayrı dosya: `spots.py` (çekirdek CRUD/bbox) büyümesin; aynı `/spots` prefix'ini paylaşır.
Güncellik özeti SADECE tekil detay isteğinde hesaplanır - bbox'a HİÇ eklenmez.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_moderator
from app.core.database import get_db
from app.models.user import User
from app.schemas.field_verification import (
    ModerationVerificationRow,
    MyVerifications,
    SpotFieldFreshness,
    VerificationSubmit,
    VerificationSubmitResponse,
)
from app.services.spot_service import SpotNotFoundError, get_spot_by_id
from app.services.verification_service import (
    CHECKIN_WINDOW_HOURS,
    NoValidCheckInError,
    build_spot_field_freshness,
    get_my_verifications,
    list_verifications_for_moderation,
    submit_verifications,
)

router = APIRouter(prefix="/spots", tags=["field-verifications"])


async def _require_spot(db: AsyncSession, spot_id: uuid.UUID):
    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return spot


@router.get("/{spot_id}/field-freshness", response_model=SpotFieldFreshness)
async def read_field_freshness(
    spot_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> SpotFieldFreshness:
    """Alan bazlı güncellik özeti (herkese açık; kullanıcı kimliği/tam saat içermez)."""
    spot = await _require_spot(db, spot_id)
    return await build_spot_field_freshness(db, spot)


@router.get("/{spot_id}/verifications/me", response_model=MyVerifications)
async def read_my_verifications(
    spot_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyVerifications:
    """Kullanıcının kendi doğrulama geçmişi + bu nokta için doğrulama yetkisi (check-in şartı)."""
    await _require_spot(db, spot_id)
    return await get_my_verifications(db, spot_id=spot_id, user_id=current_user.id)


@router.post(
    "/{spot_id}/verifications",
    response_model=VerificationSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_field_verifications(
    spot_id: uuid.UUID,
    payload: VerificationSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VerificationSubmitResponse:
    """
    Yerinde doğrulama gönderir/günceller. Son 72 saat (`CHECKIN_WINDOW_HOURS`) içinde
    bu noktada check-in yapmamış kullanıcıya 403 döner (genel düzeltme/bildirim
    yolları etkilenmez). Noktanın kalıcı teknik verisi DEĞİŞMEZ.
    """
    try:
        results = await submit_verifications(db, spot_id=spot_id, user_id=current_user.id, data=payload)
    except SpotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    except NoValidCheckInError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Yerinde doğrulama için son {CHECKIN_WINDOW_HOURS} saat içinde bu noktada "
                "check-in yapmış olmalısınız."
            ),
        )
    spot = await _require_spot(db, spot_id)
    return VerificationSubmitResponse(results=results, freshness=await build_spot_field_freshness(db, spot))


@router.get("/{spot_id}/verifications/audit", response_model=list[ModerationVerificationRow])
async def audit_verifications(
    spot_id: uuid.UUID,
    _moderator: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> list[ModerationVerificationRow]:
    """Sadece moderatör/admin: tüm doğrulama geçmişi (kullanıcı kimlikleriyle) - kötüye kullanım incelemesi."""
    await _require_spot(db, spot_id)
    return await list_verifications_for_moderation(db, spot_id=spot_id)
