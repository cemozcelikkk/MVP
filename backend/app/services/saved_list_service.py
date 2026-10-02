"""
Favoriler ve özel seyahat listeleri (bookmarks) iş mantığı.

Favoriler, `is_default_favorites=True` olan tek bir SavedList olarak
modellenir (kullanıcı başına en fazla bir tane - bkz. `SavedList`'teki
kısmi unique index); `toggle_favorite` bu listedeki öğeleri ekler/çıkarır.
Özel listeler (`create_list`, `add_item_to_list`, ...) aynı iki tabloyu
kullanır, sadece `is_default_favorites=False`'tur - paralel bir favoriler
sistemi yoktur.
"""
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.saved_list import SavedList, SavedListItem
from app.models.spot import Spot
from app.schemas.saved_list import (
    SavedListCreate,
    SavedListItemCreate,
    SavedListItemRead,
    SavedListRead,
)
from app.schemas.spot import SpotSummary
from app.services.spot_service import SpotNotFoundError


class SavedListNotFoundError(Exception):
    """Liste (veya listeden çıkarılmak istenen öğe) yok."""


class SavedListPermissionError(Exception):
    """İstek sahibi ne liste sahibi ne de liste public."""


class DuplicateListItemError(Exception):
    """Spot zaten bu listede."""


async def _get_or_create_favorites_list(db: AsyncSession, *, user_id: uuid.UUID) -> SavedList:
    favorites = await db.scalar(
        select(SavedList).where(SavedList.user_id == user_id, SavedList.is_default_favorites.is_(True))
    )
    if favorites is not None:
        return favorites

    favorites = SavedList(
        user_id=user_id, title="Favoriler", is_public=False, is_default_favorites=True
    )
    db.add(favorites)
    await db.flush()
    return favorites


async def toggle_favorite(db: AsyncSession, *, user_id: uuid.UUID, spot_id: uuid.UUID) -> bool | None:
    """
    Spot favorilerde yoksa ekler (`True` döner), varsa çıkarır (`False`
    döner). Spot bulunamazsa (veya soft-delete edilmişse) `None` döner ->
    endpoint 404 çevirir. Kullanıcının varsayılan Favoriler listesi yoksa
    ilk çağrıda örtük olarak oluşturulur.
    """
    spot_exists = await db.scalar(select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None)))
    if spot_exists is None:
        return None

    favorites = await _get_or_create_favorites_list(db, user_id=user_id)

    existing_item = await db.scalar(
        select(SavedListItem).where(
            SavedListItem.list_id == favorites.id, SavedListItem.spot_id == spot_id
        )
    )
    if existing_item is not None:
        await db.delete(existing_item)
        await db.commit()
        return False

    item = SavedListItem(list_id=favorites.id, spot_id=spot_id)
    db.add(item)
    await db.commit()
    return True


async def get_user_favorites(db: AsyncSession, *, user_id: uuid.UUID) -> list[Spot]:
    """
    Kullanıcının varsayılan Favoriler listesindeki spot'ları (en son
    eklenen en üstte) döner. Hiç favori eklenmemişse boş liste döner -
    henüz oluşturulmamış bir listeyi burada örtük olarak YARATMIYORUZ
    (salt-okunur bir endpoint side-effect üretmemeli).
    """
    favorites = await db.scalar(
        select(SavedList).where(SavedList.user_id == user_id, SavedList.is_default_favorites.is_(True))
    )
    if favorites is None:
        return []

    stmt = (
        select(Spot)
        .join(SavedListItem, SavedListItem.spot_id == Spot.id)
        .where(SavedListItem.list_id == favorites.id, Spot.deleted_at.is_(None))
        .order_by(SavedListItem.position, SavedListItem.created_at, SavedListItem.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_list(db: AsyncSession, *, user_id: uuid.UUID, data: SavedListCreate) -> SavedListRead:
    """Yeni bir özel seyahat listesi oluşturur (flush -> yanıtı kur -> commit deseni)."""
    saved_list = SavedList(user_id=user_id, title=data.title, is_public=data.is_public)
    db.add(saved_list)
    await db.flush()
    await db.refresh(saved_list, attribute_names=["created_at"])

    list_read = SavedListRead(
        id=saved_list.id,
        user_id=saved_list.user_id,
        title=saved_list.title,
        is_public=saved_list.is_public,
        is_default_favorites=saved_list.is_default_favorites,
        created_at=saved_list.created_at,
        items=[],
    )

    await db.commit()
    return list_read


async def get_list_detail(
    db: AsyncSession, *, list_id: uuid.UUID, requesting_user_id: uuid.UUID
) -> SavedListRead:
    """
    Raises:
        SavedListNotFoundError: liste yok.
        SavedListPermissionError: liste sahibi istek sahibi değil VE liste public değil.
    """
    saved_list = await db.scalar(select(SavedList).where(SavedList.id == list_id).with_for_update())
    if saved_list is None:
        raise SavedListNotFoundError(list_id)
    if saved_list.user_id != requesting_user_id and not saved_list.is_public:
        raise SavedListPermissionError(list_id)

    items_stmt = (
        select(SavedListItem)
        # Spot'u soft-delete edilmiş öğeleri listeden gizlemek için JOIN;
        # selectinload ise gerçek veri çekimini N+1 olmadan yapar.
        .join(Spot, Spot.id == SavedListItem.spot_id)
        .where(SavedListItem.list_id == list_id, Spot.deleted_at.is_(None))
        .options(selectinload(SavedListItem.spot))
        .order_by(SavedListItem.position, SavedListItem.created_at, SavedListItem.id)
    )
    items = list((await db.execute(items_stmt)).scalars().unique().all())

    return SavedListRead(
        id=saved_list.id,
        user_id=saved_list.user_id,
        title=saved_list.title,
        is_public=saved_list.is_public,
        is_default_favorites=saved_list.is_default_favorites,
        created_at=saved_list.created_at,
        items=[
            SavedListItemRead(
                id=item.id,
                spot_id=item.spot_id,
                notes=item.notes,
                position=item.position,
                planned_on=item.planned_on,
                created_at=item.created_at,
                spot=SpotSummary.model_validate(item.spot),
            )
            for item in items
        ],
    )


async def add_item_to_list(
    db: AsyncSession, *, list_id: uuid.UUID, user_id: uuid.UUID, data: SavedListItemCreate
) -> SavedListItemRead:
    """
    Raises:
        SavedListNotFoundError: liste yok.
        SavedListPermissionError: liste istek sahibine ait değil.
        SpotNotFoundError: eklenmek istenen spot yok/soft-delete edilmiş.
        DuplicateListItemError: spot zaten bu listede.
    """
    saved_list = await db.scalar(select(SavedList).where(SavedList.id == list_id).with_for_update())
    if saved_list is None:
        raise SavedListNotFoundError(list_id)
    if saved_list.user_id != user_id:
        raise SavedListPermissionError(list_id)

    spot = await db.scalar(select(Spot).where(Spot.id == data.spot_id, Spot.deleted_at.is_(None)))
    if spot is None:
        raise SpotNotFoundError(data.spot_id)

    existing = await db.scalar(
        select(SavedListItem).where(
            SavedListItem.list_id == list_id, SavedListItem.spot_id == data.spot_id
        )
    )
    if existing is not None:
        raise DuplicateListItemError(data.spot_id)

    next_position = (await db.scalar(select(func.max(SavedListItem.position)).where(SavedListItem.list_id == list_id)))
    item = SavedListItem(list_id=list_id, spot_id=data.spot_id, notes=data.notes, planned_on=data.planned_on, position=0 if next_position is None else next_position + 1)
    db.add(item)
    await db.flush()
    await db.refresh(item, attribute_names=["created_at"])

    item_read = SavedListItemRead(
        id=item.id,
        spot_id=item.spot_id,
        notes=item.notes,
        position=item.position,
        planned_on=item.planned_on,
        created_at=item.created_at,
        spot=SpotSummary.model_validate(spot),
    )

    await db.commit()
    return item_read


async def remove_item_from_list(
    db: AsyncSession, *, list_id: uuid.UUID, spot_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """
    Raises:
        SavedListNotFoundError: liste ya da (listedeki) öğe yok.
        SavedListPermissionError: liste istek sahibine ait değil.
    """
    saved_list = await db.get(SavedList, list_id)
    if saved_list is None:
        raise SavedListNotFoundError(list_id)
    if saved_list.user_id != user_id:
        raise SavedListPermissionError(list_id)

    result = await db.execute(
        sa_delete(SavedListItem).where(
            SavedListItem.list_id == list_id, SavedListItem.spot_id == spot_id
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise SavedListNotFoundError(spot_id)
