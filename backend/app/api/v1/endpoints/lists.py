"""`/api/v1/lists` altındaki özel seyahat listesi (bookmark) endpoint'leri."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.saved_list import (
    SavedListCreate,
    SavedListItemCreate,
    SavedListItemRead,
    SavedListRead,
)
from app.services.saved_list_service import (
    DuplicateListItemError,
    SavedListNotFoundError,
    SavedListPermissionError,
    add_item_to_list,
    create_list,
    get_list_detail,
    remove_item_from_list,
)
from app.services.spot_service import SpotNotFoundError

router = APIRouter(prefix="/lists", tags=["lists"])


@router.post("", response_model=SavedListRead, status_code=status.HTTP_201_CREATED)
async def create_list_endpoint(
    payload: SavedListCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SavedListRead:
    """Yeni bir özel seyahat listesi oluşturur (ör. "Ege Turu 2026", "Su Noktaları")."""
    return await create_list(db, user_id=current_user.id, data=payload)


@router.get("/{list_id}", response_model=SavedListRead)
async def read_list_endpoint(
    list_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SavedListRead:
    """
    Listenin içeriğini (öğeler + spot özetleri) döner. Sahibi olmayan bir
    kullanıcı, sadece liste `is_public=true` ise görebilir.
    """
    try:
        return await get_list_detail(db, list_id=list_id, requesting_user_id=current_user.id)
    except SavedListNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liste bulunamadı.")
    except SavedListPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu listeyi görüntüleme yetkiniz yok."
        )


@router.post(
    "/{list_id}/items",
    response_model=SavedListItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_list_item_endpoint(
    list_id: uuid.UUID,
    payload: SavedListItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SavedListItemRead:
    """Listeye bir spot ekler (opsiyonel kişisel not ile). Sadece liste sahibi ekleyebilir."""
    try:
        return await add_item_to_list(db, list_id=list_id, user_id=current_user.id, data=payload)
    except SavedListNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liste bulunamadı.")
    except SavedListPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu listeye ekleme yapma yetkiniz yok."
        )
    except SpotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    except DuplicateListItemError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bu spot zaten listede.")


@router.delete("/{list_id}/items/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_list_item_endpoint(
    list_id: uuid.UUID,
    spot_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Listeden bir spot'u çıkarır. Sadece liste sahibi çıkarabilir."""
    try:
        await remove_item_from_list(db, list_id=list_id, spot_id=spot_id, user_id=current_user.id)
    except SavedListNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Liste veya öğe bulunamadı."
        )
    except SavedListPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu listeden çıkarma yetkiniz yok."
        )


from sqlalchemy import delete, select

from app.models.saved_list import SavedList, SavedListItem
from app.models.spot import Spot
from app.schemas.saved_list import SavedListItemUpdate, SavedListReorder, SavedListSummary


@router.get("", response_model=list[SavedListSummary])
async def own_lists(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return list(
        (
            await db.scalars(
                select(SavedList)
                .where(
                    SavedList.user_id == current_user.id, SavedList.is_default_favorites.is_(False)
                )
                .order_by(SavedList.created_at.desc())
                .limit(100)
            )
        ).all()
    )


async def owned_list(db, list_id, user_id):
    saved = await db.scalar(select(SavedList).where(SavedList.id == list_id).with_for_update())
    if not saved:
        raise HTTPException(404, "Liste bulunamadı.")
    if saved.user_id != user_id:
        raise HTTPException(403, "Bu listeyi düzenleme yetkiniz yok.")
    return saved


@router.patch("/{list_id}/items/{spot_id}", response_model=SavedListRead)
async def edit_list_item(
    list_id: uuid.UUID,
    spot_id: uuid.UUID,
    payload: SavedListItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await owned_list(db, list_id, current_user.id)
    item = await db.scalar(
        select(SavedListItem).where(
            SavedListItem.list_id == list_id, SavedListItem.spot_id == spot_id
        )
    )
    if not item:
        raise HTTPException(404, "Durak bulunamadı.")
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, name, value)
    await db.commit()
    return await get_list_detail(db, list_id=list_id, requesting_user_id=current_user.id)


@router.put("/{list_id}/order", response_model=SavedListRead)
async def reorder_list(
    list_id: uuid.UUID,
    payload: SavedListReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await owned_list(db, list_id, current_user.id)
    items = list(
        (
            await db.scalars(
                select(SavedListItem)
                .join(Spot)
                .where(SavedListItem.list_id == list_id, Spot.deleted_at.is_(None))
            )
        ).all()
    )
    if len(payload.spot_ids) != len(set(payload.spot_ids)) or set(payload.spot_ids) != {
        item.spot_id for item in items
    }:
        raise HTTPException(422, "Listedeki tüm duraklar tam bir kez gönderilmeli.")
    positions = {spot_id: index for index, spot_id in enumerate(payload.spot_ids)}
    for item in items:
        item.position = positions[item.spot_id]
    await db.commit()
    return await get_list_detail(db, list_id=list_id, requesting_user_id=current_user.id)


@router.delete("/{list_id}", status_code=204)
async def delete_list(
    list_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    saved = await owned_list(db, list_id, current_user.id)
    if saved.is_default_favorites:
        raise HTTPException(400, "Varsayılan favori listesi silinemez.")
    await db.execute(delete(SavedList).where(SavedList.id == list_id))
    await db.commit()


@router.get("/{list_id}/route")
async def trip_route(
    list_id: uuid.UUID,
    corridor_km: float = Query(5, gt=0, le=30),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        detail = await get_list_detail(db, list_id=list_id, requesting_user_id=current_user.id)
    except SavedListNotFoundError:
        raise HTTPException(404, "Liste bulunamadı.")
    except SavedListPermissionError:
        raise HTTPException(403, "Bu listeyi görüntüleme yetkiniz yok.")
    from app.services.trip_service import build_trip_route

    return await build_trip_route(db, detail, corridor_km)
