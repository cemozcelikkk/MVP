"""Genel amaçlı, birden çok şema tarafından paylaşılan yardımcı tipler."""
from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    """
    İstemciden gelen konum girdisi (POST /spots gibi) için insan-okunur
    lat/lon çifti. Türkiye sınırlarını gevşek bir şekilde doğrular; sıkı
    sınır kontrolü gerekmiyor, sadece kaba bir sanity-check.
    """

    latitude: float = Field(..., ge=-90, le=90, description="Enlem (WGS84)")
    longitude: float = Field(..., ge=-180, le=180, description="Boylam (WGS84)")


class PaginationParams(BaseModel):
    limit: int = Field(default=200, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
