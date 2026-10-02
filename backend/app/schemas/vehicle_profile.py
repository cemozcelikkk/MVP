"""
`vehicle_profiles` Pydantic şemaları.

Sınır değerleri `app.models.vehicle_profile`'daki CheckConstraint'lerle
BİREBİR aynı tutulur (istek katmanında erken/net 422 hatası + DB'de ikinci
savunma hattı - bkz. o modülün docstring'i).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Drivetrain, VehicleType


class VehicleProfileBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description='Ör. "Ducato"')
    vehicle_type: VehicleType
    length_m: float = Field(..., gt=0, le=30, description="Metre cinsinden toplam araç uzunluğu")
    width_m: float | None = Field(default=None, gt=0, le=6, description="Metre cinsinden araç genişliği")
    height_m: float | None = Field(default=None, gt=0, le=5, description="Metre cinsinden araç yüksekliği")
    weight_kg: int | None = Field(default=None, gt=0, le=10000, description="Kilogram cinsinden azami ağırlık")
    drivetrain: Drivetrain = Drivetrain.TWO_WHEEL_DRIVE
    has_grey_water_tank: bool = False
    has_black_water_cassette: bool = False
    has_solar_power: bool = False
    travels_with_pet: bool = False


class VehicleProfileCreate(VehicleProfileBase):
    # True ise (veya kullanıcının bu ilk profiliyse) oluşturulduğu anda
    # aktif profil yapılır; kullanıcının varsa önceki aktif profili aynı
    # transaction içinde deaktive edilir (bkz. vehicle_profile_service).
    is_active: bool = Field(
        default=False,
        description="Aktif profil yapılsın mı? Kullanıcının ilk profiliyse zaten otomatik aktif olur.",
    )


class VehicleProfileUpdate(BaseModel):
    """PATCH gövdesi - tüm alanlar opsiyonel, gönderilmeyenler değişmez."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    vehicle_type: VehicleType | None = None
    length_m: float | None = Field(default=None, gt=0, le=30)
    width_m: float | None = Field(default=None, gt=0, le=6)
    height_m: float | None = Field(default=None, gt=0, le=5)
    weight_kg: int | None = Field(default=None, gt=0, le=10000)
    drivetrain: Drivetrain | None = None
    has_grey_water_tank: bool | None = None
    has_black_water_cassette: bool | None = None
    has_solar_power: bool | None = None
    travels_with_pet: bool | None = None
    is_active: bool | None = Field(
        default=None,
        description="True gönderilirse bu profil aktif olur, kullanıcının önceki aktif profili deaktive edilir.",
    )


class VehicleProfileRead(VehicleProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
