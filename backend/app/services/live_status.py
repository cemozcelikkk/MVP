"""
Canlı saha durumu kuralları - DB'siz, saf ve deterministik. TÜM eşik/eşleme/metin
kararları tek yerde (bkz. `field_freshness`, `live_report_service`, şemalar buradan okur).

## Ne yapar / ne YAPMAZ

Süreli bildirimleri (yol kapalı, su kullanılamıyor, ...) TÜR bazında birleştirir:
kaç BAĞIMSIZ kişi bildirdi, kaçı yakın zamanda yerinde bulunmuştu, moderatör onayı var
mı -> bir `trust_level` kodu. Noktanın KALICI teknik verisini (`spot_amenities`/
`spot_passability`) ve araç uyumluluk kayıtlarını ASLA değiştirmez; yalnızca üstüne
"şu an" bilgisi ekler.

## Kurallar

**Aktiflik** (`aggregate_active`): moderasyon durumu `pending`/`confirmed` VE süresi
dolmamış. Süresi dolan/geri çekilen/reddedilen satır silinmez, sadece dışarıda kalır.
DB tarafındaki eşdeğeri `dynamic_status.ACTIVE_REPORT_CONDITION` (aynı kural).

**Bağımsızlık**: aynı kullanıcının tekrarları tek kişi sayılır (`reporter_key`). DB de
aynı (nokta, kullanıcı, tür) için aktif pencerelerin çakışmasını yasaklar; buradaki
tekilleştirme eski (migration öncesi) satırlar için ek güvencedir. Kimliği silinmiş
(NULL) bildirenler toplamda TEK kişi sayılır - sayı şişmesin.

**Güven düzeyi** (`trust_level`, en güçlüden zayıfa):
    moderator_confirmed  aktif bildirimlerden biri moderatörce onaylandı
    well_supported       >= 3 bağımsız kişi, YA DA >= 2 kişi ve en az biri yakın zamanda yerinde
    supported            2 bağımsız kişi, YA DA yakın zamanda yerinde bulunan 1 kişi
    single_report        tek kişi, yerinde olduğu doğrulanmamış (en düşük)
"Yerinde": bildirim anında son 72 saatte o noktada check-in. Check-in kesin GPS kanıtı
değildir; bu yüzden hiçbir düzey "kesin doğrulandı" demez.

**Şiddet** (`severity`): critical > serious > caution > info. Sıralama: şiddet, sonra
bağımsız kişi sayısı, sonra en yeni bildirim, sonra tür kodu (deterministik).

**Erişim kararı** (`access`): `road_closed` veya `fire_or_flood_access_issue` aktifse
`not_recommended`; `access_difficult` veya `mud_risk` aktifse `caution`; aksi `ok`.
Bu karar fiziksel araç uygunluğundan (compatibility) AYRIDIR; ikisi yan yana gösterilir.

**Tek kişinin bildirimi**: şartname gereği aktif `road_closed` tek kişiden gelse de
"erişim önerilmiyor" üretir; ancak `trust_level=single_report` ile açıkça düşük güvenli
işaretlenir. Kötüye kullanım riski süre sınırı + moderasyon (reddet/geri çek) ile dengelenir.
"""
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from app.models.dynamic_status import LEGACY_OPEN_ENDED_HOURS
from app.models.enums import (
    CrowdLevel,
    LiveReportType,
    PoliceInterventionStatus,
    ReportModerationState,
)
from app.models.field_verification import VerifiableField

Severity = Literal["critical", "serious", "caution", "info"]
OverallSeverity = Literal["none", "critical", "serious", "caution", "info"]
TrustLevel = Literal["moderator_confirmed", "well_supported", "supported", "single_report"]
Access = Literal["ok", "caution", "not_recommended"]
SignalSeverity = Literal["blocking", "warning"]

ALLOWED_DURATION_HOURS: tuple[int, ...] = (6, 12, 24, 48)

SEVERITY_RANK: dict[str, int] = {"none": 0, "info": 1, "caution": 2, "serious": 3, "critical": 4}

WELL_SUPPORTED_MIN_REPORTERS = 3
WELL_SUPPORTED_MIN_REPORTERS_WITH_ON_SITE = 2
SUPPORTED_MIN_REPORTERS = 2
MAX_PUBLIC_NOTES = 3

ACTIVE_STATES = (ReportModerationState.PENDING, ReportModerationState.CONFIRMED)

ACCESS_BLOCKING_TYPES = frozenset(
    {LiveReportType.ROAD_CLOSED, LiveReportType.FIRE_OR_FLOOD_ACCESS_ISSUE}
)
ACCESS_CAUTION_TYPES = frozenset({LiveReportType.ACCESS_DIFFICULT, LiveReportType.MUD_RISK})

# Harita pininde uyarı rozeti: şiddeti serious/critical olan aktif durum VEYA resmî uyarı (eski
# davranış: zabıta uyarısı/cezası rozet gösterirdi; `official_warning` şiddeti caution olsa da korunur).
BADGE_MIN_SEVERITY_RANK = 3  # serious
BADGE_TYPES = frozenset({LiveReportType.OFFICIAL_WARNING})


@dataclass(frozen=True)
class ReportConfig:
    label: str  # Kullanıcıya dönük, "bildirildi" niteliğinde (resmî karar iddiası YOK)
    severity: Severity
    field: VerifiableField | None  # Hangi saha güncelliği satırına bağlanır (None = bağlanmaz)
    default_hours: int  # Formda önerilen süre (kullanıcı değiştirebilir)


REPORT_CONFIG: dict[LiveReportType, ReportConfig] = {
    LiveReportType.ROAD_CLOSED: ReportConfig(
        "Yol kapalı bildirildi", "critical", VerifiableField.ROAD_ACCESS, 24
    ),
    LiveReportType.FIRE_OR_FLOOD_ACCESS_ISSUE: ReportConfig(
        "Yangın/sel nedeniyle erişim sorunu bildirildi", "critical", VerifiableField.ROAD_ACCESS, 24
    ),
    LiveReportType.OVERNIGHT_RESTRICTION: ReportConfig(
        "Geceleme kısıtlaması bildirildi", "serious", VerifiableField.OVERNIGHT, 24
    ),
    LiveReportType.FINE_REPORTED: ReportConfig(
        "Ceza bildirildi", "serious", VerifiableField.OVERNIGHT, 24
    ),
    LiveReportType.OFFICIAL_WARNING: ReportConfig(
        "Resmî uyarı bildirildi", "caution", VerifiableField.OVERNIGHT, 24
    ),
    LiveReportType.ACCESS_DIFFICULT: ReportConfig(
        "Erişimin zorlaştığı bildirildi", "caution", VerifiableField.ROAD_ACCESS, 12
    ),
    LiveReportType.MUD_RISK: ReportConfig(
        "Çamur veya batma riski bildirildi", "caution", VerifiableField.ROAD_ACCESS, 12
    ),
    LiveReportType.FULL: ReportConfig("Alanın dolu olduğu bildirildi", "caution", None, 6),
    LiveReportType.FRESH_WATER_UNAVAILABLE: ReportConfig(
        "Tatlı suyun kullanılamadığı bildirildi", "caution", VerifiableField.FRESH_WATER, 12
    ),
    LiveReportType.ELECTRICITY_UNAVAILABLE: ReportConfig(
        "Elektriğin kullanılamadığı bildirildi", "caution", VerifiableField.ELECTRICITY, 12
    ),
    LiveReportType.GREY_WATER_UNAVAILABLE: ReportConfig(
        "Gri su boşaltmanın kullanılamadığı bildirildi", "caution", VerifiableField.GREY_WATER, 12
    ),
    LiveReportType.BLACK_WATER_UNAVAILABLE: ReportConfig(
        "Siyah su boşaltmanın kullanılamadığı bildirildi", "caution", VerifiableField.BLACK_WATER, 12
    ),
}

assert set(REPORT_CONFIG) == set(LiveReportType), "Her canlı bildirim türünün yapılandırması olmalı."
assert all(cfg.default_hours in ALLOWED_DURATION_HOURS for cfg in REPORT_CONFIG.values())


# --- Eski (police_intervention / crowd_level) sütunlarıyla köprü --------------------------------

_LEGACY_POLICE_TO_TYPE: dict[PoliceInterventionStatus, LiveReportType] = {
    PoliceInterventionStatus.WARNING: LiveReportType.OFFICIAL_WARNING,
    PoliceInterventionStatus.FINE: LiveReportType.FINE_REPORTED,
    PoliceInterventionStatus.BANNED: LiveReportType.OVERNIGHT_RESTRICTION,
}
_TYPE_TO_LEGACY_POLICE: dict[LiveReportType, PoliceInterventionStatus] = {
    v: k for k, v in _LEGACY_POLICE_TO_TYPE.items()
}


def derive_report_type(
    police: PoliceInterventionStatus | None, crowd: CrowdLevel | None
) -> LiveReportType | None:
    """Eski sütunlardan tür: zabıta müdahalesi önceliklidir, yoksa `full` kalabalık. Aksi None."""
    if police in _LEGACY_POLICE_TO_TYPE:
        return _LEGACY_POLICE_TO_TYPE[police]
    if crowd is CrowdLevel.FULL:
        return LiveReportType.FULL
    return None


def legacy_columns_for(
    report_type: LiveReportType | None,
) -> tuple[PoliceInterventionStatus, CrowdLevel | None]:
    """Yeni tür için eski API'nin okuyabileceği en yakın (police, crowd) karşılığı."""
    police = _TYPE_TO_LEGACY_POLICE.get(report_type, PoliceInterventionStatus.NONE)  # type: ignore[arg-type]
    crowd = CrowdLevel.FULL if report_type is LiveReportType.FULL else None
    return police, crowd


def effective_report_type(row: Any) -> LiveReportType | None:
    """Satırın türü; NULL ise (eski yazıcı/seed) police/crowd'dan türetilir."""
    return row.report_type or derive_report_type(row.police_intervention, row.crowd_level)


def effective_expiry(reported_at: datetime, valid_until: datetime | None) -> datetime:
    """`valid_until` NULL (eski 'süresiz') = `reported_at + 24 saat` (DB koşuluyla aynı kural)."""
    return valid_until if valid_until is not None else reported_at + timedelta(hours=LEGACY_OPEN_ENDED_HOURS)


# --- Birleştirme -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportRow:
    """Bir bildirimin DB'siz görünümü - toplama için gereken alanlar."""

    id: Any
    report_type: LiveReportType
    state: ReportModerationState
    reporter_key: str | None  # anonim: sadece "kaç bağımsız kişi" için, dışarı ÇIKMAZ
    on_site: bool
    reported_at: datetime
    expires_at: datetime
    note: str | None


def to_report_row(obj: Any) -> ReportRow | None:
    """ORM `DynamicStatus` -> `ReportRow`; tür belirlenemeyen (salt bilgi) satırlar için None."""
    report_type = effective_report_type(obj)
    if report_type is None:
        return None
    return ReportRow(
        id=obj.id,
        report_type=report_type,
        state=obj.moderation_state,
        reporter_key=str(obj.reported_by) if obj.reported_by is not None else None,
        on_site=bool(obj.reporter_on_site),
        reported_at=obj.reported_at,
        expires_at=effective_expiry(obj.reported_at, obj.valid_until),
        note=obj.note,
    )


@dataclass(frozen=True)
class TypeAggregate:
    report_type: LiveReportType
    severity: Severity
    reporter_count: int
    on_site_count: int
    moderator_confirmed: bool
    trust_level: TrustLevel
    latest_reported_at: datetime
    expires_at: datetime  # bu türdeki aktif bildirimlerin EN GEÇ bitişi (tür en geç bu zamana dek aktif)
    notes: tuple[str, ...]  # en yeni MAX_PUBLIC_NOTES not (kimliksiz)


@dataclass(frozen=True)
class LiveSummary:
    access: Access
    severity: OverallSeverity
    active_count: int
    top_type: LiveReportType | None
    types: tuple[LiveReportType, ...]
    expires_at: datetime | None  # en üstteki türün bitişi
    badge: bool = False  # haritada pin rozeti gösterilsin mi


def _trust_level(reporters: int, on_site: int, confirmed: bool) -> TrustLevel:
    if confirmed:
        return "moderator_confirmed"
    if reporters >= WELL_SUPPORTED_MIN_REPORTERS or (
        reporters >= WELL_SUPPORTED_MIN_REPORTERS_WITH_ON_SITE and on_site >= 1
    ):
        return "well_supported"
    if reporters >= SUPPORTED_MIN_REPORTERS or on_site >= 1:
        return "supported"
    return "single_report"


def _distinct_reporters(rows: list[ReportRow], *, only_on_site: bool = False) -> int:
    keys = {r.reporter_key for r in rows if (r.on_site or not only_on_site)}
    # Kimliği silinmiş (None) bildirenler toplamda TEK kişi: sayı şişmesin.
    return len(keys)


def aggregate_active(rows: list[ReportRow], *, now: datetime) -> list[TypeAggregate]:
    """Aktif bildirimleri türe göre birleştirir; şiddet/güven sıralı (en ciddi ilk)."""
    by_type: dict[LiveReportType, list[ReportRow]] = defaultdict(list)
    for row in rows:
        if row.state in ACTIVE_STATES and row.expires_at > now:
            by_type[row.report_type].append(row)

    result: list[TypeAggregate] = []
    for report_type, group in by_type.items():
        reporters = _distinct_reporters(group)
        on_site = _distinct_reporters(group, only_on_site=True)
        confirmed = any(r.state is ReportModerationState.CONFIRMED for r in group)
        newest_first = sorted(group, key=lambda r: (r.reported_at, str(r.id)), reverse=True)
        notes = tuple(r.note.strip() for r in newest_first if r.note and r.note.strip())[:MAX_PUBLIC_NOTES]
        result.append(
            TypeAggregate(
                report_type=report_type,
                severity=REPORT_CONFIG[report_type].severity,
                reporter_count=reporters,
                on_site_count=on_site,
                moderator_confirmed=confirmed,
                trust_level=_trust_level(reporters, on_site, confirmed),
                latest_reported_at=max(r.reported_at for r in group),
                expires_at=max(r.expires_at for r in group),
                notes=notes,
            )
        )

    result.sort(
        key=lambda a: (
            SEVERITY_RANK[a.severity],
            a.reporter_count,
            a.latest_reported_at,
            a.report_type.value,
        ),
        reverse=True,
    )
    return result


def aggregates_from_statuses(statuses: list[Any], *, now: datetime) -> list[TypeAggregate]:
    """ORM `DynamicStatus` listesinden (bbox/detayda zaten yüklü) aktif tür birleşimleri."""
    rows = [row for row in (to_report_row(s) for s in statuses) if row is not None]
    return aggregate_active(rows, now=now)


def compute_access(aggregates: list[TypeAggregate]) -> Access:
    types = {a.report_type for a in aggregates}
    if types & ACCESS_BLOCKING_TYPES:
        return "not_recommended"
    if types & ACCESS_CAUTION_TYPES:
        return "caution"
    return "ok"


def summarize(aggregates: list[TypeAggregate]) -> LiveSummary:
    top = aggregates[0] if aggregates else None
    return LiveSummary(
        access=compute_access(aggregates),
        severity=top.severity if top else "none",
        active_count=len(aggregates),
        top_type=top.report_type if top else None,
        types=tuple(a.report_type for a in aggregates),
        expires_at=top.expires_at if top else None,
        badge=any(
            SEVERITY_RANK[a.severity] >= BADGE_MIN_SEVERITY_RANK or a.report_type in BADGE_TYPES
            for a in aggregates
        ),
    )


def aggregates_for_field(aggregates: list[TypeAggregate], field: VerifiableField) -> list[TypeAggregate]:
    """Belirli saha güncelliği satırını etkileyen aktif türler (şiddet sıralı)."""
    return [a for a in aggregates if REPORT_CONFIG[a.report_type].field is field]


def signal_severity(severity: Severity) -> SignalSeverity:
    """Güncellik satırındaki canlı sinyal şiddeti: critical/serious -> blocking, diğer -> warning."""
    return "blocking" if severity in ("critical", "serious") else "warning"


# --- Kullanıcı metinleri (kodlardan ayrı; istemci karar mantığını KODLARA dayandırmalı) ----------


def remaining_minutes(expires_at: datetime, now: datetime) -> int:
    return max(0, math.ceil((expires_at - now).total_seconds() / 60))


def remaining_text(minutes: int) -> str:
    if minutes <= 0:
        return "Süresi doldu"
    hours, mins = divmod(minutes, 60)
    if hours == 0:
        return f"{mins} dk kaldı"
    if mins == 0:
        return f"{hours} saat kaldı"
    return f"{hours} sa {mins} dk kaldı"


def trust_text(level: TrustLevel) -> str:
    return {
        "moderator_confirmed": "Moderatör onayladı",
        "well_supported": "Birden fazla bağımsız bildirim",
        "supported": "Destekleniyor",
        "single_report": "Tek kişi bildirdi · yerinde olduğu doğrulanmadı",
    }[level]


def evidence_text(agg: TypeAggregate) -> str:
    parts = [
        "1 kişi bildirdi" if agg.reporter_count == 1 else f"{agg.reporter_count} bağımsız kişi bildirdi"
    ]
    if agg.on_site_count:
        parts.append(f"{agg.on_site_count} kişi son 72 saatte noktada check-in yapmıştı")
    return " · ".join(parts)


def access_headline(access: Access) -> str | None:
    return {
        "not_recommended": "Şu anda erişim önerilmiyor",
        "caution": "Dikkatli erişim",
        "ok": None,
    }[access]


def access_live_text(aggregates: list[TypeAggregate]) -> str | None:
    """Uyumluluk kartındaki 'Ancak ...' cümlesi. Erişimi etkileyen EN CİDDİ türden üretilir."""
    for agg in aggregates:
        if agg.report_type is LiveReportType.ROAD_CLOSED:
            return "Ancak yolun şu anda kapalı olduğu bildirildi"
        if agg.report_type is LiveReportType.FIRE_OR_FLOOD_ACCESS_ISSUE:
            return "Ancak yangın veya sel nedeniyle erişim sorunu bildirildi"
        if agg.report_type is LiveReportType.ACCESS_DIFFICULT:
            return "Ancak erişimin şu anda zorlaştığı bildirildi"
        if agg.report_type is LiveReportType.MUD_RISK:
            return "Ancak şu anda çamur veya batma riski bildirildi"
    return None
