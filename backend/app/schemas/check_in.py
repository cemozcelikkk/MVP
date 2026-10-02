"""`check_ins` Pydantic şemaları."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CheckInBase(BaseModel):
    planned_nights: int | None = Field(default=None, ge=1, le=365)


class CheckInCreate(CheckInBase):
    # Anti-spoofing: kullanıcının check-in anındaki GERÇEK GPS konumu.
    # `checkin_service.add_check_in` bunu spot'un koordinatıyla PostGIS
    # ST_DWithin üzerinden karşılaştırır; oturduğu yerden check-in atıp
    # trust_score kasmayı engellemenin temeli budur. Bilerek DB'ye
    # kalıcı olarak yazılmıyor (check_ins tablosunda kolon yok) - sadece
    # doğrulama anında kullanılıp atılıyor.
    latitude: float = Field(..., ge=-90, le=90, description="Check-in anındaki GPS enlemi (WGS84)")
    longitude: float = Field(..., ge=-180, le=180, description="Check-in anındaki GPS boylamı (WGS84)")


class CheckInRead(CheckInBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    spot_id: uuid.UUID
    user_id: uuid.UUID
    checked_in_at: datetime
