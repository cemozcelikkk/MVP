"""`spot_amenities` Pydantic şemaları (park4night yetenekleri)."""
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SignalStrength


class SpotAmenitiesBase(BaseModel):
    fresh_water_thread: bool = False
    black_water: bool = False
    grey_water: bool = False
    electricity_220v: bool = False

    has_toilet: bool = False
    has_trash_bins: bool = False
    is_free: bool = True
    price_description: str | None = Field(default=None, max_length=300)
    camping_behavior_allowed: bool = True
    rule_information_known: bool = False

    # Anahtarlar serbest bırakılır (turkcell, vodafone, turk_telekom, ...)
    # ki yeni bir MVNO/operatör çıktığında şema değişikliği gerekmesin;
    # değerler ise SignalStrength enum'una göre doğrulanır.
    gsm_signals: dict[str, SignalStrength] = Field(default_factory=dict)


class SpotAmenitiesCreate(SpotAmenitiesBase):
    pass


class SpotAmenitiesRead(SpotAmenitiesBase):
    model_config = ConfigDict(from_attributes=True)


class SpotAmenitiesUpdate(SpotAmenitiesBase):
    """Only explicitly supplied fields are applied by the update service."""

    pass
