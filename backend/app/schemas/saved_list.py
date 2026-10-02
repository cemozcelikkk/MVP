"""`saved_lists` / `saved_list_items` (favoriler + özel seyahat listeleri) Pydantic şemaları."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.spot import SpotSummary


class SavedListCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150, description='Ör. "Ege Turu 2026"')
    is_public: bool = Field(default=False, description="True ise link'i olan herkes görebilir.")


class SavedListItemCreate(BaseModel):
    spot_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=1000, description="Kişisel not (opsiyonel)")
    planned_on: date | None = None


class SavedListItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    spot_id: uuid.UUID
    notes: str | None = None
    position: int = 0
    planned_on: date | None = None
    created_at: datetime
    # Liste kartında spot'u tanımaya yetecek hafif özet (bkz. SpotSummary).
    spot: SpotSummary


class SavedListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    is_public: bool
    is_default_favorites: bool
    created_at: datetime
    items: list[SavedListItemRead] = Field(default_factory=list)


class FavoriteToggleResponse(BaseModel):
    is_favorited: bool


class SavedListItemUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)
    planned_on: date | None = None


class SavedListReorder(BaseModel):
    spot_ids: list[uuid.UUID] = Field(max_length=500)


class SavedListSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    is_public: bool
    created_at: datetime
