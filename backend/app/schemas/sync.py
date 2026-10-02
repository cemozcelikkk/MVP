"""`GET /spots/sync` delta senkronizasyon yanıt şeması."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.spot import SpotRead


class SpotSyncResponse(BaseModel):
    # İstemci bir sonraki senkron çağrısında bu değeri `since` parametresi
    # olarak geri gönderir. Sunucunun kendi saatinden (clock_timestamp())
    # ve sorgu BAŞLAMADAN ÖNCE alınır - ayrıntı için spot_service.get_spots_sync
    # docstring'ine bakınız.
    server_time: datetime

    # Eklenmiş veya güncellenmiş spot'lar; mobil istemci bunları yerel
    # SQLite'a upsert eder (INSERT OR REPLACE).
    upserts: list[SpotRead] = Field(default_factory=list)

    # Soft-delete edilmiş spot id'leri; mobil istemci bunları yerel
    # SQLite'tan siler.
    deleted_ids: list[uuid.UUID] = Field(default_factory=list)
