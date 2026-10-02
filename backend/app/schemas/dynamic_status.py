"""`dynamic_status` Pydantic şemaları (Türkiye'ye özgü canlı durum)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    CrowdLevel,
    LiveReportType,
    PoliceInterventionStatus,
    ReportModerationState,
)


class DynamicStatusBase(BaseModel):
    police_intervention: PoliceInterventionStatus = PoliceInterventionStatus.NONE
    note: str | None = None
    crowd_level: CrowdLevel | None = None
    # Bildirimin geçerliliğinin sona ereceği zaman; None ise süresiz kabul edilir.
    valid_until: datetime | None = None


class DynamicStatusCreate(DynamicStatusBase):
    """POST /spots/{id}/status için istek gövdesi."""

    # `valid_until` doğrudan verilmezse geçerlilik süresi buradan hesaplanır
    # (spot_service.add_dynamic_status). Üst sınır 168 saat (1 hafta) -
    # zabıta/kalabalık bildirimlerinin süresiz kalmaması için makul bir üst sınır.
    expires_in_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Bildirim kaç saat sonra süresi dolmuş sayılsın (varsayılan 24). `valid_until` açıkça verilirse bu alan yok sayılır.",
    )


class DynamicStatusRead(DynamicStatusBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    spot_id: uuid.UUID
    # GİZLİLİK: bildiren kimliği herkese açık yanıtta ASLA dönmez (alan uyumluluk için duruyor, hep null).
    reported_by: uuid.UUID | None = None
    reported_at: datetime
    # Süreli canlı bildirim alanları (eski istemciler görmezden gelebilir).
    report_type: LiveReportType | None = None
    moderation_state: ReportModerationState = ReportModerationState.PENDING
    duration_hours: int | None = None

    @field_validator("reported_by", mode="before")
    @classmethod
    def _never_expose_reporter(cls, _value: object) -> None:
        return None
