"""`spot_passability` Pydantic şemaları (iOverlander yetenekleri)."""
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CaravanType, ClearanceRequired, RoadType


class SpotPassabilityBase(BaseModel):
    road_type: RoadType
    max_vehicle_length: float | None = Field(
        default=None, gt=0, le=30, description="Metre cinsinden azami araç+çeki uzunluğu"
    )
    # Karavan Profili uyumluluk motoru için (bkz. compatibility_service).
    # Bilinmiyorsa None bırakılmalı - 0 veya tahmini bir değer GÖNDERME,
    # motor None'ı "insufficient_data" olarak yorumlar.
    max_vehicle_width: float | None = Field(
        default=None, gt=0, le=6, description="Metre cinsinden azami araç genişliği (biliniyorsa)"
    )
    max_vehicle_height: float | None = Field(
        default=None, gt=0, le=5, description="Metre cinsinden azami araç yüksekliği (biliniyorsa)"
    )
    max_vehicle_weight_kg: int | None = Field(
        default=None, gt=0, le=10000, description="Kilogram cinsinden azami araç ağırlığı (biliniyorsa)"
    )
    clearance_required: ClearanceRequired = ClearanceRequired.STANDARD
    caravan_types_allowed: list[CaravanType] = Field(default_factory=list)
    steep_incline: bool = False


class SpotPassabilityCreate(SpotPassabilityBase):
    pass


class SpotPassabilityRead(SpotPassabilityBase):
    model_config = ConfigDict(from_attributes=True)
