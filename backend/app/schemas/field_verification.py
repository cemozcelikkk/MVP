"""
Saha bilgisi güncelliği / yerinde doğrulama şemaları.

Yanıtlarda KARARLI makine kodları (`status`, `tone`, `confidence`, `code`) ile
Türkçe kullanıcı metinleri (`status_text`, `message`, `reported_text`) ayrı
alanlarda döner - istemci karar mantığını kodlara dayandırmalı, metne DEĞİL.
Herkese açık yanıtlarda kullanıcı kimliği, ham koordinat veya tam ziyaret saati
YOKTUR: son doğrulama sadece GÜN düzeyinde (`last_verified_on`) verilir.
"""
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import LiveReportType
from app.models.field_verification import (
    VERIFIABLE_ANSWERS,
    VerifiableField,
    VerificationAnswer,
)
from app.services.field_freshness import Confidence, FreshnessStatus, Tone
from app.services.live_status import TrustLevel


class VerificationSubmit(BaseModel):
    """
    `answers`: alan -> cevap. `unknown` ("bilmiyorum / kontrol etmedim") kabul edilir
    ama SAKLANMAZ ve hiçbir sayıma girmez. Her alanın geçerli cevap kümesi
    `VERIFIABLE_ANSWERS`'tadır (ör. su için `passable` reddedilir).
    """

    answers: dict[VerifiableField, VerificationAnswer] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_answers_per_field(self) -> "VerificationSubmit":
        for field, answer in self.answers.items():
            if answer is VerificationAnswer.UNKNOWN:
                continue
            if answer not in VERIFIABLE_ANSWERS[field]:
                allowed = ", ".join(a.value for a in VERIFIABLE_ANSWERS[field])
                raise ValueError(f"'{field.value}' alanı için geçersiz cevap '{answer.value}' (geçerli: {allowed}).")
        return self


class LiveSignalRead(BaseModel):
    """Aktif süreli bildirimden gelen sinyal - kalıcı doğrulamadan AYRIDIR (bkz. live_status)."""

    code: str  # kararlı, ör. LIVE_ROAD_CLOSED
    severity: Literal["warning", "blocking"]
    message: str
    conflicts_with_verification: bool
    report_type: LiveReportType | None = None
    reporter_count: int = 0
    trust_level: TrustLevel | None = None
    expires_at: datetime | None = None


class FieldFreshnessRead(BaseModel):
    field: VerifiableField
    label: str
    status: FreshnessStatus
    tone: Tone
    status_text: str
    consensus_answer: VerificationAnswer | None = None
    conflicting_answers: list[VerificationAnswer] = Field(default_factory=list)
    participant_count: int = 0
    supporting_count: int = 0
    # Sadece GÜN - tam saat herkese açık değil.
    last_verified_on: date | None = None
    age_days: int | None = None
    confidence: Confidence
    fresh_days: int
    # Noktanın KALICI (bildirilen) teknik bilgisi - doğrulama bunu DEĞİŞTİRMEZ.
    reported_text: str | None = None
    live_signal: LiveSignalRead | None = None  # en ciddi aktif sinyal (geriye dönük uyum)
    live_signals: list[LiveSignalRead] = Field(default_factory=list)
    # true: olumlu (eski) doğrulama aktif bir süreli sorunla çelişiyor - istemci yeşil/baskın göstermemeli.
    live_overrides: bool = False


class SpotFieldFreshness(BaseModel):
    spot_id: uuid.UUID
    primary: list[FieldFreshnessRead]
    secondary: list[FieldFreshnessRead]


EligibilityCode = Literal["ELIGIBLE", "NO_RECENT_CHECKIN"]


class MyVerificationRow(BaseModel):
    """Kullanıcının KENDİ gönderisi - kendi geçmişini görebilir (başkasınınkini değil)."""

    field: VerifiableField
    answer: VerificationAnswer
    created_at: datetime
    is_current: bool


class MyVerifications(BaseModel):
    eligible: bool
    eligibility_code: EligibilityCode
    eligibility_message: str
    # Uygun ise: doğrulamanın bağlanacağı ziyaretin tarihi (kullanıcının kendi verisi).
    check_in_at: datetime | None = None
    # Bu ziyaret için henüz hiç cevap verilmemiş mi? (arayüzde nazik bir hatırlatma için)
    has_pending_prompt: bool = False
    current_answers: dict[VerifiableField, VerificationAnswer] = Field(default_factory=dict)
    history: list[MyVerificationRow] = Field(default_factory=list)


class VerificationResultItem(BaseModel):
    field: VerifiableField
    action: Literal["created", "updated", "unchanged", "skipped"]


class VerificationSubmitResponse(BaseModel):
    results: list[VerificationResultItem]
    freshness: SpotFieldFreshness


class ModerationVerificationRow(BaseModel):
    """Yalnızca moderatör/admin - kötüye kullanımı incelemek için kullanıcı kimliği dahil."""

    id: uuid.UUID
    user_id: uuid.UUID
    check_in_id: uuid.UUID | None
    field: VerifiableField
    answer: VerificationAnswer
    created_at: datetime
    is_current: bool
