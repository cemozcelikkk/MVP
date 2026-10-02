from typing import Literal

"""`spot_photos` Pydantic şemaları."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SpotPhotoBase(BaseModel):
    photo_kind: Literal["general", "entrance"] = "general"
    storage_url: str = Field(..., max_length=500)
    caption: str | None = Field(default=None, max_length=300)


class SpotPhotoCreate(SpotPhotoBase):
    pass


class SpotPhotoRead(SpotPhotoBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    spot_id: uuid.UUID
    uploaded_by: uuid.UUID | None = None
    # Sadece sunucu tarafında (photo_service._process_image) üretilir; bu
    # yüzden Base/Create'te değil, sadece Read'de yer alır. Eklenmeden önce
    # yüklenmiş eski fotoğraflarda NULL olabilir.
    thumbnail_url: str | None = None
    is_cover: bool = False
    created_at: datetime
