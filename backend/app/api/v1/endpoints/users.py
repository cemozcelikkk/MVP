"""`/api/v1/users` altındaki kullanıcıya özel endpoint'ler."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.spot import SpotSummary
from app.services.saved_list_service import get_user_favorites

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/favorites", response_model=list[SpotSummary])
async def read_my_favorites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SpotSummary]:
    """
    Kullanıcının favorilediği spot'ları (en son eklenen en üstte), harita
    pinleri/kart görünümleri için yeterli özet bilgilerle döner. Hiç
    favori yoksa boş liste döner (404 değil).
    """
    favorites = await get_user_favorites(db, user_id=current_user.id)
    return [SpotSummary.model_validate(spot) for spot in favorites]


from app.schemas.user import AccountDeleteRequest
from app.services.account_service import delete_account


@router.delete("/me", status_code=204)
async def delete_my_account(payload: AccountDeleteRequest, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    await delete_account(db, user, payload.password, payload.confirmation)
