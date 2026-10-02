"""
Saha bilgisi güncellik motoru - `evaluate_field` DB'siz, saf ve deterministik.

## Ne yapar / ne YAPMAZ

Her doğrulanabilir alan (yol, geceleme, su, elektrik, gri/siyah su) için,
kullanıcıların "yerinde doğrulama" cevaplarından (kullanıcı başına YALNIZCA
güncel cevap) bir güncellik durumu üretir. Noktanın KALICI teknik verisini
(`spot_amenities`/`spot_passability`) DEĞİŞTİRMEZ ve süreli canlı durumların
(`dynamic_status`) yerine GEÇMEZ: canlı durumla çelişki ayrı bir `live_signal`
olarak taşınır ve yeşil "güven" izlenimini bastırır (bkz. `tone`).

## Kurallar (hepsi burada, tek yerde)

**Süre eşikleri (`fresh_days`)** - alanın ne kadar hızlı değiştiğine göre:
    su 14 gün, elektrik 14 gün   (kesinti/arıza sık, hızlı eskir)
    gri su 30, siyah su 30       (tesis genelde kalıcı ama tıkanma/kapanma olur)
    geceleme 45                  (yerel yasaklar/uygulamalar mevsimlik değişir)
    yol erişimi 60               (yol yüzeyi/durumu en yavaş değişen bilgi)
Eşik aşıldığında kayıt SİLİNMEZ; sadece (a) durum `stale` olur, (b) ağırlığı
azalır: `weight = 0.5 ** (yaş_gün / fresh_days)` (yarı ömür = fresh_days).

**Çelişki (`conflicting_reports`)**: en az 2 bağımsız katılımcı VE en yüksek
ağırlıklı cevabın ardından gelen cevabın ağırlığı >= 0.5 (yaklaşık "bir taze
oy") VE toplam ağırlıktaki payı >= %30. Eski bir cevap zamanla ağırlığını
kaybettiği için taze bir cevaba karşı çelişki üretmez (son yazanı otomatik
"gerçek" kabul etmeyiz ama eskimiş oyu da eşit saymayız).

**Durum sırası**: katılımcı yok -> `unverified`; çelişki -> `conflicting_reports`;
en son destekleyen cevap fresh_days'ten eski -> `stale`; baskın cevap olumsuz
(çalışmıyor/yasak/geçilemez) -> `service_issue_reported`; aksi -> `recently_confirmed`.

**Güven (`confidence`)**: taze (<= fresh_days) destekleyen bağımsız kişi sayısı
0-1 -> `low` (tek doğrulama "kesin güvenilir" gibi sunulmaz), 2 -> `medium`,
>=3 -> `high`.

**Canlı (süreli) bildirimler**: AKTİF `live_status` türleri ilgili satıra bağlanır
(`live_status.REPORT_CONFIG[...].field`): yol kapalı / erişim zor / çamur / yangın-sel -> yol
erişimi; geceleme kısıtlaması / resmî uyarı / ceza -> geceleme; su / elektrik / gri / siyah
su kullanılamıyor -> ilgili hizmet. Bildirimin süresi dolunca (veya geri çekilince/reddedilince)
sinyal kendiliğinden kalkar. Kalıcı saha verisi ve doğrulama kayıtları DEĞİŞMEZ.
Baskın doğrulama OLUMLU (çalışıyor/mümkün/geçilebilir; yolda "zor" + ciddi sinyal) iken
aktif bir sinyal varsa `conflicts_with_verification=true`, `live_overrides=true` olur ve
`tone` ASLA yeşil kalmaz: ciddi (blocking) sinyalde `negative`, diğerinde `caution`.
Doğrulamanın kendi `status`u (ör. `recently_confirmed`) değişmez; istemci canlı sinyali önce,
eski doğrulamayı ikincil ("son doğrulama") gösterir.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.models.enums import LiveReportType
from app.models.field_verification import VerifiableField, VerificationAnswer
from app.services.live_status import (
    REPORT_CONFIG,
    SignalSeverity,
    TrustLevel,
    TypeAggregate,
    aggregates_for_field,
    signal_severity,
)

FreshnessStatus = Literal[
    "recently_confirmed", "stale", "conflicting_reports", "unverified", "service_issue_reported"
]
Confidence = Literal["low", "medium", "high"]
Tone = Literal["positive", "caution", "negative", "neutral"]

CONFLICT_MIN_RUNNER_UP_WEIGHT = 0.5
CONFLICT_MIN_RUNNER_UP_SHARE = 0.30
HIGH_CONFIDENCE_MIN_FRESH_SUPPORTERS = 3
MEDIUM_CONFIDENCE_MIN_FRESH_SUPPORTERS = 2

_NEGATIVE_ANSWERS = {
    VerificationAnswer.NOT_WORKING,
    VerificationAnswer.NOT_ALLOWED,
    VerificationAnswer.IMPASSABLE,
}


@dataclass(frozen=True)
class FieldConfig:
    label: str  # "Su"
    subject: str  # "Su durumuna" - "...ilişkin güncel doğrulama yok" cümlesi için
    fresh_days: int
    phrases: dict[VerificationAnswer, str]  # olumlu/olumsuz cümle kalıbı


FIELD_CONFIG: dict[VerifiableField, FieldConfig] = {
    VerifiableField.ROAD_ACCESS: FieldConfig(
        "Yol erişimi",
        "Yol durumuna",
        60,
        {
            VerificationAnswer.PASSABLE: "Yol geçilebilir",
            VerificationAnswer.DIFFICULT: "Yol zor geçiliyor",
            VerificationAnswer.IMPASSABLE: "Yol geçilemiyor",
        },
    ),
    VerifiableField.OVERNIGHT: FieldConfig(
        "Geceleme",
        "Geceleme durumuna",
        45,
        {
            VerificationAnswer.ALLOWED: "Geceleme mümkün",
            VerificationAnswer.NOT_ALLOWED: "Geceleme mümkün değil",
        },
    ),
    VerifiableField.FRESH_WATER: FieldConfig(
        "Tatlı su",
        "Su durumuna",
        14,
        {VerificationAnswer.WORKING: "Su çalışıyor", VerificationAnswer.NOT_WORKING: "Su çalışmıyor"},
    ),
    VerifiableField.ELECTRICITY: FieldConfig(
        "Elektrik",
        "Elektrik durumuna",
        14,
        {
            VerificationAnswer.WORKING: "Elektrik çalışıyor",
            VerificationAnswer.NOT_WORKING: "Elektrik çalışmıyor",
        },
    ),
    VerifiableField.GREY_WATER: FieldConfig(
        "Gri su boşaltma",
        "Gri su boşaltma durumuna",
        30,
        {
            VerificationAnswer.WORKING: "Gri su boşaltma kullanılabiliyor",
            VerificationAnswer.NOT_WORKING: "Gri su boşaltma kullanılamıyor",
        },
    ),
    VerifiableField.BLACK_WATER: FieldConfig(
        "Siyah su boşaltma",
        "Siyah su boşaltma durumuna",
        30,
        {
            VerificationAnswer.WORKING: "Siyah su boşaltma kullanılabiliyor",
            VerificationAnswer.NOT_WORKING: "Siyah su boşaltma kullanılamıyor",
        },
    ),
}

FIELD_CONFIG.update({
    VerifiableField.TOILET: FieldConfig("Tuvalet", "Tuvalet durumuna", 14, {VerificationAnswer.WORKING: "Tuvalet kullanılabiliyor", VerificationAnswer.NOT_WORKING: "Tuvalet kullanılamıyor"}),
    VerifiableField.TRASH_BINS: FieldConfig("Çöp kutusu", "Atık alanına", 30, {VerificationAnswer.WORKING: "Çöp kutusu kullanılabiliyor", VerificationAnswer.NOT_WORKING: "Çöp kutusu kullanılamıyor"}),
    VerifiableField.PRICE: FieldConfig("Ücret", "Ücret bilgisine", 30, {VerificationAnswer.FREE: "Ücretsiz olarak bildirildi", VerificationAnswer.PAID: "Ücretli olarak bildirildi"}),
    VerifiableField.CAMPING_BEHAVIOR: FieldConfig("Kamp davranışı", "Kamp davranışı iznine", 45, {VerificationAnswer.ALLOWED: "Kamp davranışı serbest olarak bildirildi", VerificationAnswer.NOT_ALLOWED: "Kamp davranışına izin verilmiyor"}),
})

# Arayüzde ilk bakışta görünen alanlar (geri kalanı açılır bölümde) - tek yerde.
PRIMARY_FIELDS: tuple[VerifiableField, ...] = (
    VerifiableField.ROAD_ACCESS,
    VerifiableField.OVERNIGHT,
    VerifiableField.FRESH_WATER,
    VerifiableField.ELECTRICITY,
)


@dataclass(frozen=True)
class CurrentAnswer:
    """Bir kullanıcının bir alandaki GÜNCEL cevabı - kimlik alanı yok, sadece sayım için."""

    user_key: str
    answer: VerificationAnswer
    verified_at: datetime


@dataclass(frozen=True)
class LiveSignal:
    code: str  # ör. "LIVE_ROAD_CLOSED" (kararlı)
    severity: SignalSeverity
    message: str
    conflicts_with_verification: bool
    report_type: LiveReportType
    reporter_count: int
    trust_level: TrustLevel
    expires_at: datetime


@dataclass(frozen=True)
class FieldFreshnessResult:
    field: VerifiableField
    status: FreshnessStatus
    tone: Tone
    consensus_answer: VerificationAnswer | None
    conflicting_answers: tuple[VerificationAnswer, ...]
    participant_count: int
    supporting_count: int
    last_verified_at: datetime | None
    age_days: int | None
    confidence: Confidence
    fresh_days: int
    status_text: str
    live_signal: LiveSignal | None  # en ciddi aktif sinyal (geriye dönük uyum)
    live_signals: tuple[LiveSignal, ...] = ()
    live_overrides: bool = False  # olumlu doğrulama aktif bir sinyalle çelişiyor


def _signal_fields(signals: tuple[LiveSignal, ...]) -> dict:
    return {
        "live_signal": signals[0] if signals else None,
        "live_signals": signals,
        "live_overrides": any(sig.conflicts_with_verification for sig in signals),
    }


def _age_days(now: datetime, then: datetime) -> float:
    return max(0.0, (now - then).total_seconds() / 86400)


def _weight(age_days: float, fresh_days: int) -> float:
    return 0.5 ** (age_days / fresh_days)


def relative_tr(age_days: int) -> str:
    """0 -> 'bugün', 1 -> 'dün', 3 -> '3 gün önce', 14 -> '2 hafta önce', 200 -> '6 ay önce'."""
    if age_days <= 0:
        return "bugün"
    if age_days == 1:
        return "dün"
    if age_days < 7:
        return f"{age_days} gün önce"
    if age_days < 30:
        return f"{age_days // 7} hafta önce"
    if age_days < 365:
        return f"{age_days // 30} ay önce"
    return f"{age_days // 365} yıl önce"


def duration_tr(age_days: int) -> str:
    """'7 aydır' biçimi - 'X bilgisi 7 aydır doğrulanmadı' cümlesi için."""
    if age_days < 7:
        return f"{max(age_days, 1)} gündür"
    if age_days < 30:
        return f"{age_days // 7} haftadır"
    if age_days < 365:
        return f"{age_days // 30} aydır"
    return f"{age_days // 365} yıldır"


_POSITIVE_ANSWERS = {
    VerificationAnswer.WORKING,
    VerificationAnswer.ALLOWED,
    VerificationAnswer.PASSABLE,
}


def _conflicts(consensus: VerificationAnswer | None, severity: SignalSeverity) -> bool:
    """Baskın doğrulama olumluysa her aktif sinyal çelişir; yolda 'zor geçiliyor' ise ciddi sinyal çelişir."""
    if consensus in _POSITIVE_ANSWERS:
        return True
    return consensus is VerificationAnswer.DIFFICULT and severity == "blocking"


def _live_signals(
    field: VerifiableField,
    aggregates: list[TypeAggregate] | None,
    consensus: VerificationAnswer | None,
) -> tuple[LiveSignal, ...]:
    signals = []
    for agg in aggregates_for_field(aggregates or [], field):  # zaten şiddet sıralı
        severity = signal_severity(agg.severity)
        signals.append(
            LiveSignal(
                code=f"LIVE_{agg.report_type.value.upper()}",
                severity=severity,
                message=f"{REPORT_CONFIG[agg.report_type].label}.",
                conflicts_with_verification=_conflicts(consensus, severity),
                report_type=agg.report_type,
                reporter_count=agg.reporter_count,
                trust_level=agg.trust_level,
                expires_at=agg.expires_at,
            )
        )
    return tuple(signals)


def evaluate_field(
    field: VerifiableField,
    answers: list[CurrentAnswer],
    *,
    now: datetime | None = None,
    live_aggregates: list[TypeAggregate] | None = None,
) -> FieldFreshnessResult:
    """
    `answers`: kullanıcı başına EN FAZLA bir GÜNCEL cevap (servis bunu garanti eder).
    `live_aggregates`: noktanın AKTİF canlı bildirim birleşimleri (`live_status.aggregate_active`).
    """
    now = now or datetime.now(UTC)
    cfg = FIELD_CONFIG[field]
    fresh_days = cfg.fresh_days

    if not answers:
        return FieldFreshnessResult(
            field=field,
            status="unverified",
            tone="neutral",
            consensus_answer=None,
            conflicting_answers=(),
            participant_count=0,
            supporting_count=0,
            last_verified_at=None,
            age_days=None,
            confidence="low",
            fresh_days=fresh_days,
            status_text=f"{cfg.subject} ilişkin güncel doğrulama yok",
            **_signal_fields(_live_signals(field, live_aggregates, None)),
        )

    weights: dict[VerificationAnswer, float] = defaultdict(float)
    latest_by_answer: dict[VerificationAnswer, datetime] = {}
    for item in answers:
        weights[item.answer] += _weight(_age_days(now, item.verified_at), fresh_days)
        if item.answer not in latest_by_answer or item.verified_at > latest_by_answer[item.answer]:
            latest_by_answer[item.answer] = item.verified_at

    # Deterministik sıralama: ağırlık, sonra en yeni zaman, sonra cevap adı.
    ranked = sorted(
        weights, key=lambda a: (weights[a], latest_by_answer[a], a.value), reverse=True
    )
    leading = ranked[0]
    total = sum(weights.values())
    participants = len({a.user_key for a in answers})

    conflicting = False
    if len(ranked) > 1 and participants >= 2:
        runner_up = weights[ranked[1]]
        conflicting = (
            runner_up >= CONFLICT_MIN_RUNNER_UP_WEIGHT
            and runner_up / total >= CONFLICT_MIN_RUNNER_UP_SHARE
        )

    last_verified = max(a.verified_at for a in answers)
    last_age = int(_age_days(now, last_verified))

    if conflicting:
        contested = tuple(a for a in ranked if weights[a] >= CONFLICT_MIN_RUNNER_UP_WEIGHT)
        return FieldFreshnessResult(
            field=field,
            status="conflicting_reports",
            tone="caution",
            consensus_answer=None,
            conflicting_answers=contested,
            participant_count=participants,
            supporting_count=0,
            last_verified_at=last_verified,
            age_days=last_age,
            confidence="low",
            fresh_days=fresh_days,
            status_text=f"{cfg.label}: çelişkili bildirimler var",
            **_signal_fields(_live_signals(field, live_aggregates, None)),
        )

    supporters = [a for a in answers if a.answer is leading]
    latest_support = max(a.verified_at for a in supporters)
    support_age = int(_age_days(now, latest_support))
    fresh_supporters = sum(
        1 for a in supporters if _age_days(now, a.verified_at) <= fresh_days
    )
    if fresh_supporters >= HIGH_CONFIDENCE_MIN_FRESH_SUPPORTERS:
        confidence: Confidence = "high"
    elif fresh_supporters >= MEDIUM_CONFIDENCE_MIN_FRESH_SUPPORTERS:
        confidence = "medium"
    else:
        confidence = "low"

    signals = _live_signals(field, live_aggregates, leading)
    negative = leading in _NEGATIVE_ANSWERS
    is_stale = support_age > fresh_days

    if is_stale:
        status: FreshnessStatus = "stale"
        tone: Tone = "neutral"
        text = f"{cfg.label} bilgisi {duration_tr(support_age)} doğrulanmadı"
    elif negative:
        status = "service_issue_reported"
        tone = "negative"
        text = f"{cfg.phrases[leading]} · {relative_tr(support_age)} bildirildi"
    else:
        status = "recently_confirmed"
        tone = "positive"
        text = f"{cfg.phrases[leading]} · {relative_tr(support_age)} doğrulandı"

    # Canlı çelişki: olumlu tonu ASLA yeşil bırakma (bkz. modül docstring'i).
    overriding = [sig for sig in signals if sig.conflicts_with_verification]
    if overriding and tone == "positive":
        tone = "negative" if any(sig.severity == "blocking" for sig in overriding) else "caution"

    return FieldFreshnessResult(
        field=field,
        status=status,
        tone=tone,
        consensus_answer=leading,
        conflicting_answers=(),
        participant_count=participants,
        supporting_count=len(supporters),
        last_verified_at=latest_support,
        age_days=support_age,
        confidence=confidence,
        fresh_days=fresh_days,
        status_text=text,
        **_signal_fields(signals),
    )

