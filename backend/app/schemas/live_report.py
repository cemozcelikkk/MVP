"""
Süreli canlı saha bildirimi şemaları.

Yanıtlarda KARARLI makine kodları (`report_type`, `severity`, `trust_level`, `access`,
`moderation_state`, `outcome`) ile Türkçe kullanıcı metinleri (`label`, `trust_text`,
`evidence_text`, `remaining_text`, `headline`) AYRI alanlardadır - istemci karar mantığını
kodlara dayandırmalı, metne DEĞİL.

Herkese açık yanıtlarda kullanıcı kimliği, konum, tam check-in zamanı YOKTUR: bildirenin
kimliği hiç dönmez; yalnızca kendi bildirimini tanıması için `my_report_id` verilir.
Kimlik (`reporter_id`) yalnızca moderatör/admin uçlarındaki `Moderation*` şemalarındadır.
"""
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import LiveReportType, ReportModerationState, UserRole
from app.services.live_status import (
    ALLOWED_DURATION_HOURS,
    Access,
    OverallSeverity,
    Severity,
    TrustLevel,
    aggregates_from_statuses,
    summarize,
)

NOTE_MAX_LENGTH = 280

ReportOutcome = Literal["active", "expired", "withdrawn", "rejected"]
ModerationAction = Literal["confirm", "reject", "withdraw"]
ModerationView = Literal["pending", "active", "closed", "expired"]


def _clean_note(value: str | None) -> str | None:
    """Kontrol karakterlerini atar, boşlukları sadeleştirir; boşsa None. (HTML burada değil
    istemcide metin olarak render edilir; yine de görünmez/kontrol karakterleri temizlenir.)"""
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable() or ch in "\n\t")
    cleaned = " ".join(cleaned.split())
    return cleaned or None


class LiveReportCreate(BaseModel):
    report_type: LiveReportType
    duration_hours: int = Field(..., description="6, 12, 24 veya 48 saat")
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)

    @field_validator("duration_hours")
    @classmethod
    def _allowed_duration(cls, value: int) -> int:
        if value not in ALLOWED_DURATION_HOURS:
            raise ValueError(f"Süre şunlardan biri olmalı: {', '.join(map(str, ALLOWED_DURATION_HOURS))} saat.")
        return value

    @field_validator("note")
    @classmethod
    def _sanitize_note(cls, value: str | None) -> str | None:
        return _clean_note(value)


class ModerationActionRequest(BaseModel):
    action: ModerationAction
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)

    @field_validator("note")
    @classmethod
    def _sanitize_note(cls, value: str | None) -> str | None:
        return _clean_note(value)


class SpotLiveSummary(BaseModel):
    """HAFİF özet - bbox/detay/sync yanıtlarına eklenir (sınırsız geçmiş DEĞİL)."""

    access: Access
    severity: OverallSeverity
    active_count: int
    top_type: LiveReportType | None = None
    types: list[LiveReportType] = Field(default_factory=list)
    # En üstteki türün bitişi: istemci süresi dolunca kendi başına da düşürebilsin.
    expires_at: datetime | None = None
    # Haritada pin rozeti gösterilsin mi (karar backend'de: bkz. live_status.BADGE_*).
    badge: bool = False

    @classmethod
    def from_statuses(cls, statuses: list, *, now: datetime | None = None) -> "SpotLiveSummary":
        """Zaten yüklü `dynamic_statuses`'tan (EK SORGU YOK - bbox N+1 oluşturmaz) hafif özet."""
        now = now or datetime.now(UTC)
        summary = summarize(aggregates_from_statuses(statuses, now=now))
        return cls(
            access=summary.access,
            severity=summary.severity,
            active_count=summary.active_count,
            top_type=summary.top_type,
            types=list(summary.types),
            expires_at=summary.expires_at,
            badge=summary.badge,
        )


class LiveReportGroup(BaseModel):
    """Bir noktadaki AKTİF bildirimlerin tür bazlı birleşimi."""

    report_type: LiveReportType
    label: str
    severity: Severity
    reporter_count: int
    on_site_count: int
    trust_level: TrustLevel
    trust_text: str
    evidence_text: str
    moderator_confirmed: bool
    # Doğrulama/moderasyon durumunun açık kodu: 'confirmed' (moderatör onayladı) | 'pending'.
    moderation_state: Literal["confirmed", "pending"]
    latest_reported_at: datetime
    expires_at: datetime
    remaining_minutes: int
    remaining_text: str
    notes: list[str] = Field(default_factory=list)
    # Çağıranın bu türde AKTİF bildirimi varsa kimliği (geri çekme eylemi için).
    my_report_id: uuid.UUID | None = None


class SpotLiveReports(BaseModel):
    spot_id: uuid.UUID
    generated_at: datetime
    summary: SpotLiveSummary
    headline: str | None = Field(
        default=None, description="Erişim kararı metni (ör. 'Şu anda erişim önerilmiyor'); erişim sorunu yoksa null"
    )
    groups: list[LiveReportGroup]


class LiveReportRead(BaseModel):
    """Çağıranın KENDİ bildiriminin özeti (kimlik alanı yok)."""

    id: uuid.UUID
    spot_id: uuid.UUID
    report_type: LiveReportType
    label: str
    moderation_state: ReportModerationState
    outcome: ReportOutcome
    duration_hours: int | None
    starts_at: datetime
    expires_at: datetime
    note: str | None = None
    reporter_on_site: bool


class LiveReportActionResponse(BaseModel):
    report: LiveReportRead
    live: SpotLiveReports


class LiveReportHistoryItem(BaseModel):
    id: uuid.UUID
    report_type: LiveReportType
    label: str
    outcome: ReportOutcome
    moderation_state: ReportModerationState
    starts_at: datetime
    expires_at: datetime
    reporter_on_site: bool
    is_mine: bool = False


class LiveReportHistoryPage(BaseModel):
    items: list[LiveReportHistoryItem]
    total: int
    limit: int
    offset: int


class SpotLiveAccess(BaseModel):
    """Uyumluluk yanıtına eklenen "şu an kullanılabilirlik" - fiziksel uygunluktan AYRI."""

    status: Access
    headline: str | None = None
    physical_text: str
    live_text: str | None = None
    reasons: list[LiveReportGroup] = Field(default_factory=list)


# --- Moderasyon (yalnızca moderatör/admin) ------------------------------------------------------


class ModerationEventRead(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_name: str | None
    actor_role: UserRole
    from_state: ReportModerationState
    to_state: ReportModerationState
    note: str | None
    created_at: datetime


class ModerationReportRow(BaseModel):
    id: uuid.UUID
    spot_id: uuid.UUID
    spot_title: str
    report_type: LiveReportType
    label: str
    severity: Severity
    moderation_state: ReportModerationState
    outcome: ReportOutcome
    duration_hours: int | None
    starts_at: datetime
    expires_at: datetime
    note: str | None
    reporter_id: uuid.UUID | None
    reporter_name: str | None
    reporter_on_site: bool
    is_legacy: bool
    last_event: ModerationEventRead | None = None


class ModerationReportPage(BaseModel):
    items: list[ModerationReportRow]
    total: int
    limit: int
    offset: int
