"""
`GET /spots/{spot_id}/compatibility` yanıt şemaları.

`status`/`reasons[].code`/`reasons[].severity` STABİL, makine-okunur
değerlerdir - frontend (web veya gelecekteki React Native istemcisi) karar
mantığını bunlara dayandırmalı, `message`/`summary` metinlerine ASLA
(bkz. app.services.compatibility_service docstring'i).
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.live_report import SpotLiveAccess

CompatibilityStatus = Literal["compatible", "caution", "not_compatible", "insufficient_data"]
ReasonSeverity = Literal["blocking", "warning", "unknown", "info"]


class CompatibilityReason(BaseModel):
    """Sonucu oluşturan tek bir kural değerlendirmesi."""

    code: str = Field(..., description="Makine-okunur, stabil kural kimliği, ör. LENGTH_EXCEEDS_LIMIT")
    severity: ReasonSeverity
    message: str = Field(..., description="Kullanıcıya gösterilecek Türkçe açıklama")


class SpotCompatibilityResult(BaseModel):
    spot_id: uuid.UUID
    vehicle_profile_id: uuid.UUID
    status: CompatibilityStatus
    summary: str = Field(..., description="Tüm 'reasons' değerlendirildikten sonraki genel özet")
    reasons: list[CompatibilityReason] = Field(default_factory=list)
    checked_at: datetime
    # Noktanın ŞU ANKİ erişilebilirliği (aktif süreli bildirimler) - fiziksel uygunluk `status`undan
    # AYRIDIR: araç ölçülere göre uygun olsa da yol şu an kapalı olabilir. `status`/`reasons` bundan
    # ETKİLENMEZ. Yalnızca `GET /spots/{id}/compatibility` doldurur.
    live_access: SpotLiveAccess | None = None


class SpotCompatibilitySummary(BaseModel):
    """
    `GET /spots/bbox?with_compatibility=true` yanıtındaki HAFİF özet -
    haritanın "Aracıma Uygun" filtresi sadece `status`u kullanır, tam
    `reasons` listesini TAŞIMAZ (yüzlerce pin için gereksiz payload
    büyümesi olurdu). Detaylı gerekçeler için kullanıcı bir noktayı seçip
    `GET /spots/{spot_id}/compatibility`i çağırır (bkz. `spots.py` router).
    """

    status: CompatibilityStatus
