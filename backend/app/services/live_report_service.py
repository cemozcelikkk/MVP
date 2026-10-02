"""
Süreli canlı saha bildirimi iş mantığı (oluşturma, listeleme, geri çekme, moderasyon).

Kurallar tek yerde `live_status.py`; bu modül DB'ye dokunan kısımdır.

## Garantiler

- **Aktiflik sorgu anında** (`ACTIVE_REPORT_CONDITION`): cron yok. Süresi dolan / geri
  çekilen / reddedilen satır SİLİNMEZ, yalnızca aktif sonuçlardan düşer.
- **Süre/zaman backend'de, UTC:** `reported_at` (başlangıç) ve `valid_until` (bitiş)
  burada hesaplanır; istemci saati kullanılmaz.
- **Tekrar engeli:** aynı (nokta, kullanıcı, tür) için aktif bildirim varken yenisi
  reddedilir (`DuplicateActiveReportError`). Önce `pg_advisory_xact_lock` ile sıraya
  sokulur; asıl güvence DB'deki exclusion constraint'tir (yarışan istekler dahil).
- **Check-in ZORUNLU DEĞİL** (mevcut ürün davranışı: giriş yapmış herkes bildirebilir).
  Son 72 saatte o noktada check-in'i olan bildirenin bildirimi `reporter_on_site=true`
  işaretlenir; olmayan açıkça daha düşük güven düzeyinde (`single_report`) gösterilir.
  Tam check-in zamanı/konumu saklanmaz ve HİÇBİR yanıtta dönmez.
- **Kalıcı veri dokunulmaz:** `spot_amenities`/`spot_passability` bu modülde hiç yazılmaz.
- **Moderasyon geçmişi:** her durum değişikliği `live_report_events`'e yazılır
  (kullanıcının kendi geri çekmesi dahil).
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check_in import CheckIn
from app.models.dynamic_status import (
    ACTIVE_REPORT_CONDITION,
    REPORT_NOT_EXPIRED,
    REPORT_STATE_OPEN,
    DynamicStatus,
)
from app.models.enums import (
    CrowdLevel,
    LiveReportType,
    PoliceInterventionStatus,
    ReportModerationState,
    UserRole,
)
from app.models.live_report_event import LiveReportEvent
from app.models.spot import Spot
from app.models.user import User
from app.schemas.dynamic_status import DynamicStatusCreate
from app.schemas.live_report import (
    LiveReportCreate,
    LiveReportGroup,
    LiveReportHistoryItem,
    LiveReportHistoryPage,
    LiveReportRead,
    ModerationEventRead,
    ModerationReportPage,
    ModerationReportRow,
    ModerationView,
    ReportOutcome,
    SpotLiveAccess,
    SpotLiveReports,
    SpotLiveSummary,
)
from app.services.live_status import (
    ACCESS_BLOCKING_TYPES,
    ACCESS_CAUTION_TYPES,
    ALLOWED_DURATION_HOURS,
    REPORT_CONFIG,
    TypeAggregate,
    access_headline,
    access_live_text,
    aggregate_active,
    aggregates_from_statuses,
    derive_report_type,
    effective_expiry,
    evidence_text,
    legacy_columns_for,
    remaining_minutes,
    remaining_text,
    summarize,
    to_report_row,
    trust_text,
)
from app.services.spot_service import SpotNotFoundError
from app.services.verification_service import CHECKIN_WINDOW_HOURS

_PRIVILEGED_ROLES = (UserRole.MODERATOR, UserRole.ADMIN)

# eylem -> (hangi durumlardan yapılabilir, hedef durum)
_TRANSITIONS: dict[str, tuple[tuple[ReportModerationState, ...], ReportModerationState]] = {
    "confirm": ((ReportModerationState.PENDING,), ReportModerationState.CONFIRMED),
    "reject": (
        (ReportModerationState.PENDING, ReportModerationState.CONFIRMED),
        ReportModerationState.REJECTED,
    ),
    "withdraw": (
        (ReportModerationState.PENDING, ReportModerationState.CONFIRMED),
        ReportModerationState.WITHDRAWN,
    ),
}


class DuplicateActiveReportError(Exception):
    """Kullanıcının bu noktada aynı türde zaten AKTİF bir bildirimi var."""

    def __init__(self, existing_id: uuid.UUID | None = None):
        super().__init__(existing_id)
        self.existing_id = existing_id


class InvalidExpiryError(Exception):
    """Eski uçtaki `valid_until` geçmişte / geçersiz."""


class ReportNotFoundError(Exception):
    """Bildirim yok."""


class ReportPermissionError(Exception):
    """Ne bildirimin sahibi ne de moderatör/admin."""


class InvalidTransitionError(Exception):
    """Bu bildirim mevcut durumunda bu işleme uygun değil (zaten kapalı / süresi dolmuş)."""

    def __init__(self, state: ReportModerationState, expired: bool = False):
        super().__init__(state, expired)
        self.state = state
        self.expired = expired


# --- Yardımcılar -------------------------------------------------------------------------------


def report_outcome(row: DynamicStatus, now: datetime) -> ReportOutcome:
    if row.moderation_state is ReportModerationState.WITHDRAWN:
        return "withdrawn"
    if row.moderation_state is ReportModerationState.REJECTED:
        return "rejected"
    if effective_expiry(row.reported_at, row.valid_until) <= now:
        return "expired"
    return "active"


def _label(report_type: LiveReportType | None) -> str:
    return REPORT_CONFIG[report_type].label if report_type is not None else "Saha notu"


def to_report_read(row: DynamicStatus, now: datetime) -> LiveReportRead:
    report_type = row.report_type or derive_report_type(row.police_intervention, row.crowd_level)
    return LiveReportRead(
        id=row.id,
        spot_id=row.spot_id,
        report_type=report_type,  # type: ignore[arg-type]  # bu uçlardan hep türlü satır döner
        label=_label(report_type),
        moderation_state=row.moderation_state,
        outcome=report_outcome(row, now),
        duration_hours=row.duration_hours,
        starts_at=row.reported_at,
        expires_at=effective_expiry(row.reported_at, row.valid_until),
        note=row.note,
        reporter_on_site=row.reporter_on_site,
    )


def group_from_aggregate(
    agg: TypeAggregate, *, now: datetime, my_report_id: uuid.UUID | None = None
) -> LiveReportGroup:
    minutes = remaining_minutes(agg.expires_at, now)
    return LiveReportGroup(
        report_type=agg.report_type,
        label=REPORT_CONFIG[agg.report_type].label,
        severity=agg.severity,
        reporter_count=agg.reporter_count,
        on_site_count=agg.on_site_count,
        trust_level=agg.trust_level,
        trust_text=trust_text(agg.trust_level),
        evidence_text=evidence_text(agg),
        moderator_confirmed=agg.moderator_confirmed,
        moderation_state="confirmed" if agg.moderator_confirmed else "pending",
        latest_reported_at=agg.latest_reported_at,
        expires_at=agg.expires_at,
        remaining_minutes=minutes,
        remaining_text=remaining_text(minutes),
        notes=list(agg.notes),
        my_report_id=my_report_id,
    )


async def _has_recent_check_in(
    db: AsyncSession, *, spot_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> bool:
    since = now - timedelta(hours=CHECKIN_WINDOW_HOURS)
    found = await db.scalar(
        select(CheckIn.id)
        .where(CheckIn.spot_id == spot_id, CheckIn.user_id == user_id, CheckIn.checked_in_at >= since)
        .limit(1)
    )
    return found is not None


async def _active_rows(db: AsyncSession, spot_id: uuid.UUID) -> list[DynamicStatus]:
    return list(
        (
            await db.execute(
                select(DynamicStatus)
                .where(DynamicStatus.spot_id == spot_id, ACTIVE_REPORT_CONDITION)
                .order_by(DynamicStatus.reported_at.desc())
            )
        ).scalars()
    )


async def _bump_spot(db: AsyncSession, spot_id: uuid.UUID) -> None:
    # Delta sync bu değişikliği "spot değişti" olarak yakalasın (bkz. spot_service.add_dynamic_status).
    await db.execute(sa_update(Spot).where(Spot.id == spot_id).values(updated_at=func.now()))


_PHYSICAL_TEXT = {
    "compatible": "Aracınız bu noktaya fiziksel olarak uygun",
    "caution": "Aracınız için bu noktada fiziksel uygunluk dikkat gerektiriyor",
    "not_compatible": "Aracınız bu noktaya fiziksel olarak uygun değil",
    "insufficient_data": "Aracınız için fiziksel uygunluk verisi yetersiz",
}


def build_live_access(spot_statuses: list, *, compatibility_status: str, now: datetime) -> SpotLiveAccess:
    """
    Fiziksel uygunluk (`compatibility_status`, DEĞİŞTİRİLMEZ) ile noktanın ŞU ANKİ erişim
    durumunu ayrı ama tutarlı cümlelerle birleştirir; ör. "Aracınız bu noktaya fiziksel olarak
    uygun" + "Ancak yolun şu anda kapalı olduğu bildirildi". Yalnızca erişimi etkileyen aktif
    türler (`road_closed`, `fire_or_flood_access_issue`, `access_difficult`, `mud_risk`) dikkate alınır.
    """
    aggregates = aggregates_from_statuses(spot_statuses, now=now)
    access_aggs = [a for a in aggregates if a.report_type in ACCESS_BLOCKING_TYPES | ACCESS_CAUTION_TYPES]
    summary = summarize(access_aggs)
    return SpotLiveAccess(
        status=summary.access,
        headline=access_headline(summary.access),
        physical_text=_PHYSICAL_TEXT.get(compatibility_status, _PHYSICAL_TEXT["insufficient_data"]),
        live_text=access_live_text(access_aggs),
        reasons=[group_from_aggregate(a, now=now) for a in access_aggs],
    )


# --- Okuma -------------------------------------------------------------------------------------


async def get_spot_live_reports(
    db: AsyncSession, *, spot_id: uuid.UUID, viewer_id: uuid.UUID | None = None
) -> SpotLiveReports | None:
    """Noktanın AKTİF bildirimleri (tür bazlı birleşik, en ciddi ilk). Spot yoksa None."""
    exists = await db.scalar(select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None)))
    if exists is None:
        return None
    now = datetime.now(UTC)
    rows = await _active_rows(db, spot_id)
    report_rows = [r for r in (to_report_row(row) for row in rows) if r is not None]
    aggregates = aggregate_active(report_rows, now=now)

    my_ids: dict[LiveReportType, uuid.UUID] = {}
    if viewer_id is not None:
        for row in rows:
            row_type = row.report_type or derive_report_type(row.police_intervention, row.crowd_level)
            if row.reported_by == viewer_id and row_type is not None and row_type not in my_ids:
                my_ids[row_type] = row.id

    summary = summarize(aggregates)
    return SpotLiveReports(
        spot_id=spot_id,
        generated_at=now,
        summary=SpotLiveSummary(
            access=summary.access,
            severity=summary.severity,
            active_count=summary.active_count,
            top_type=summary.top_type,
            types=list(summary.types),
            expires_at=summary.expires_at,
            badge=summary.badge,
        ),
        headline=access_headline(summary.access),
        groups=[group_from_aggregate(a, now=now, my_report_id=my_ids.get(a.report_type)) for a in aggregates],
    )


async def list_history(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    viewer_id: uuid.UUID | None,
    limit: int = 20,
    offset: int = 0,
) -> LiveReportHistoryPage:
    """Süresi geçmiş / geri çekilmiş / reddedilmiş bildirimler (sayfalı, en yeni ilk)."""
    now = datetime.now(UTC)
    inactive = ~ACTIVE_REPORT_CONDITION
    base = (DynamicStatus.spot_id == spot_id, DynamicStatus.report_type.is_not(None), inactive)
    total = await db.scalar(select(func.count()).select_from(DynamicStatus).where(*base)) or 0
    rows = (
        await db.execute(
            select(DynamicStatus)
            .where(*base)
            .order_by(DynamicStatus.reported_at.desc(), DynamicStatus.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    items = [
        LiveReportHistoryItem(
            id=row.id,
            report_type=row.report_type,  # type: ignore[arg-type]
            label=_label(row.report_type),
            outcome=report_outcome(row, now),
            moderation_state=row.moderation_state,
            starts_at=row.reported_at,
            expires_at=effective_expiry(row.reported_at, row.valid_until),
            reporter_on_site=row.reporter_on_site,
            is_mine=viewer_id is not None and row.reported_by == viewer_id,
        )
        for row in rows
    ]
    return LiveReportHistoryPage(items=items, total=total, limit=limit, offset=offset)


# --- Oluşturma ---------------------------------------------------------------------------------


async def _create_rows(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    user_id: uuid.UUID | None,
    specs: list[tuple[LiveReportType | None, PoliceInterventionStatus, CrowdLevel | None]],
    note: str | None,
    duration_hours: int | None,
    reported_at: datetime,
    valid_until: datetime,
) -> list[DynamicStatus]:
    spot_exists = await db.scalar(select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None)))
    if spot_exists is None:
        raise SpotNotFoundError(spot_id)

    on_site = False
    if user_id is not None:
        # Aynı kullanıcı+nokta için eşzamanlı gönderimleri sıraya sok; asıl güvence DB constraint'i.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"livereport:{user_id}:{spot_id}"}
        )
        for report_type, _police, _crowd in specs:
            if report_type is None:
                continue
            existing = await db.scalar(
                select(DynamicStatus.id).where(
                    DynamicStatus.spot_id == spot_id,
                    DynamicStatus.reported_by == user_id,
                    DynamicStatus.report_type == report_type,
                    ACTIVE_REPORT_CONDITION,
                )
            )
            if existing is not None:
                raise DuplicateActiveReportError(existing)
        on_site = await _has_recent_check_in(db, spot_id=spot_id, user_id=user_id, now=reported_at)

    rows = [
        DynamicStatus(
            spot_id=spot_id,
            reported_by=user_id,
            report_type=report_type,
            police_intervention=police,
            crowd_level=crowd,
            note=note,
            reported_at=reported_at,
            valid_until=valid_until,
            duration_hours=duration_hours,
            moderation_state=ReportModerationState.PENDING,
            reporter_on_site=on_site,
        )
        for report_type, police, crowd in specs
    ]
    db.add_all(rows)
    try:
        await db.flush()
    except IntegrityError:
        # Yarışan eşzamanlı istek aynı anda aynı türü ekledi (exclusion constraint).
        await db.rollback()
        raise DuplicateActiveReportError() from None
    await _bump_spot(db, spot_id)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


async def create_live_report(
    db: AsyncSession, *, spot_id: uuid.UUID, user: User, data: LiveReportCreate
) -> DynamicStatus:
    """
    Yeni süreli bildirim. Başlangıç/bitiş backend'de UTC olarak hesaplanır.

    Raises: SpotNotFoundError, DuplicateActiveReportError.
    """
    reported_at = datetime.now(UTC)
    police, crowd = legacy_columns_for(data.report_type)
    rows = await _create_rows(
        db,
        spot_id=spot_id,
        user_id=user.id,
        specs=[(data.report_type, police, crowd)],
        note=data.note,
        duration_hours=data.duration_hours,
        reported_at=reported_at,
        valid_until=reported_at + timedelta(hours=data.duration_hours),
    )
    return rows[0]


async def create_legacy_status(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    data: DynamicStatusCreate,
    reported_by: uuid.UUID | None,
) -> DynamicStatus:
    """
    Eski `POST /spots/{id}/status` (zabıta + kalabalık) uyumluluğu: aynı yeni modele yazar.

    Zabıta müdahalesi (warning/fine/banned) bir tür, `crowd_level=full` ayrı bir tür (`full`)
    üretir - ikisi birlikte gelirse iki satır; yanıt zabıta satırıdır. Bunlardan hiçbiri yoksa
    tür atanmamış bir bilgi satırı (`report_type` NULL) yazılır. Eski uç serbest süre
    (`expires_in_hours` 1-168 / `valid_until`) kabul etmeye devam eder.

    Raises: SpotNotFoundError, DuplicateActiveReportError, InvalidExpiryError.
    """
    reported_at = datetime.now(UTC)
    if data.valid_until is not None:
        valid_until = data.valid_until if data.valid_until.tzinfo else data.valid_until.replace(tzinfo=UTC)
        if valid_until <= reported_at:
            raise InvalidExpiryError()
    else:
        valid_until = reported_at + timedelta(hours=data.expires_in_hours)

    police_type = derive_report_type(data.police_intervention, None)
    specs: list[tuple[LiveReportType | None, PoliceInterventionStatus, CrowdLevel | None]] = []
    if police_type is not None:
        specs.append((police_type, data.police_intervention, data.crowd_level))
        if data.crowd_level is CrowdLevel.FULL:
            specs.append((LiveReportType.FULL, PoliceInterventionStatus.NONE, CrowdLevel.FULL))
    elif data.crowd_level is CrowdLevel.FULL:
        specs.append((LiveReportType.FULL, data.police_intervention, CrowdLevel.FULL))
    else:
        specs.append((None, data.police_intervention, data.crowd_level))

    rows = await _create_rows(
        db,
        spot_id=spot_id,
        user_id=reported_by,
        specs=specs,
        note=data.note,
        duration_hours=data.expires_in_hours if data.expires_in_hours in ALLOWED_DURATION_HOURS and data.valid_until is None else None,
        reported_at=reported_at,
        valid_until=valid_until,
    )
    return rows[0]


# --- Geri çekme / moderasyon -------------------------------------------------------------------


async def transition_report(
    db: AsyncSession,
    *,
    report_id: uuid.UUID,
    actor: User,
    action: str,
    note: str | None = None,
) -> DynamicStatus:
    """
    Durum geçişi: `confirm`/`reject` yalnızca moderatör/admin; `withdraw` bildirimin sahibi
    (yalnızca AKTİFken) veya moderatör/admin. Satır silinmez; işlem `live_report_events`'e yazılır.

    Raises: ReportNotFoundError, ReportPermissionError, InvalidTransitionError.
    """
    allowed_from, to_state = _TRANSITIONS[action]
    row = await db.scalar(select(DynamicStatus).where(DynamicStatus.id == report_id).with_for_update())
    if row is None:
        raise ReportNotFoundError(report_id)

    is_privileged = actor.role in _PRIVILEGED_ROLES
    is_owner = row.reported_by is not None and row.reported_by == actor.id
    if action == "withdraw":
        if not (is_owner or is_privileged):
            raise ReportPermissionError(report_id)
    elif not is_privileged:
        raise ReportPermissionError(report_id)

    now = datetime.now(UTC)
    expired = effective_expiry(row.reported_at, row.valid_until) <= now
    if row.moderation_state not in allowed_from:
        raise InvalidTransitionError(row.moderation_state)
    # Süresi dolmuş bildirimi kullanıcı geri çekemez (geri çekilecek aktif bir şey yok);
    # moderatör kayıt düzeltmek için işlem yapabilir.
    if expired and not is_privileged:
        raise InvalidTransitionError(row.moderation_state, expired=True)

    from_state = row.moderation_state
    row.moderation_state = to_state
    db.add(
        LiveReportEvent(
            report_id=row.id,
            actor_id=actor.id,
            actor_role=actor.role,
            from_state=from_state,
            to_state=to_state,
            note=note,
        )
    )
    await db.flush()
    await _bump_spot(db, row.spot_id)
    await db.commit()
    await db.refresh(row)
    return row


# --- Moderasyon listeleri ----------------------------------------------------------------------


def _event_read(event: LiveReportEvent, actor_name: str | None) -> ModerationEventRead:
    return ModerationEventRead(
        id=event.id,
        report_id=event.report_id,
        actor_id=event.actor_id,
        actor_name=actor_name,
        actor_role=event.actor_role,
        from_state=event.from_state,
        to_state=event.to_state,
        note=event.note,
        created_at=event.created_at,
    )


def _view_condition(view: ModerationView):
    if view == "pending":
        return (DynamicStatus.moderation_state == ReportModerationState.PENDING, REPORT_NOT_EXPIRED)
    if view == "active":
        return (ACTIVE_REPORT_CONDITION,)
    if view == "closed":
        return (
            DynamicStatus.moderation_state.in_(
                [ReportModerationState.REJECTED, ReportModerationState.WITHDRAWN]
            ),
        )
    return (REPORT_STATE_OPEN, ~REPORT_NOT_EXPIRED)  # expired


async def _moderation_page(
    db: AsyncSession, conditions: list, *, limit: int, offset: int
) -> ModerationReportPage:
    total = await db.scalar(select(func.count()).select_from(DynamicStatus).where(*conditions)) or 0
    result = await db.execute(
        select(DynamicStatus, Spot.title, User.display_name)
        .join(Spot, Spot.id == DynamicStatus.spot_id)
        .outerjoin(User, User.id == DynamicStatus.reported_by)
        .where(*conditions)
        .order_by(DynamicStatus.reported_at.desc(), DynamicStatus.id)
        .limit(limit)
        .offset(offset)
    )
    page = result.all()

    # Son moderasyon olayı: sayfa için TEK ek sorgu (N+1 değil).
    last_events: dict[uuid.UUID, ModerationEventRead] = {}
    ids = [row.id for row, _, _ in page]
    if ids:
        events = (
            await db.execute(
                select(LiveReportEvent, User.display_name)
                .outerjoin(User, User.id == LiveReportEvent.actor_id)
                .where(LiveReportEvent.report_id.in_(ids))
                .order_by(LiveReportEvent.created_at.asc())
            )
        ).all()
        for event, actor_name in events:  # asc sırayla ezilir -> sonuncu kalır
            last_events[event.report_id] = _event_read(event, actor_name)

    now = datetime.now(UTC)
    items = [
        ModerationReportRow(
            id=row.id,
            spot_id=row.spot_id,
            spot_title=spot_title,
            report_type=row.report_type,  # type: ignore[arg-type]
            label=_label(row.report_type),
            severity=REPORT_CONFIG[row.report_type].severity,  # type: ignore[index]
            moderation_state=row.moderation_state,
            outcome=report_outcome(row, now),
            duration_hours=row.duration_hours,
            starts_at=row.reported_at,
            expires_at=effective_expiry(row.reported_at, row.valid_until),
            note=row.note,
            reporter_id=row.reported_by,
            reporter_name=reporter_name,
            reporter_on_site=row.reporter_on_site,
            is_legacy=row.is_legacy,
            last_event=last_events.get(row.id),
        )
        for row, spot_title, reporter_name in page
    ]
    return ModerationReportPage(items=items, total=total, limit=limit, offset=offset)


async def list_for_moderation(
    db: AsyncSession,
    *,
    view: ModerationView,
    spot_id: uuid.UUID | None = None,
    limit: int = 30,
    offset: int = 0,
) -> ModerationReportPage:
    """Moderatör listesi (kimlikli). Tür atanmamış bilgi satırları hariç."""
    conditions = [DynamicStatus.report_type.is_not(None), *_view_condition(view)]
    if spot_id is not None:
        conditions.append(DynamicStatus.spot_id == spot_id)
    return await _moderation_page(db, conditions, limit=limit, offset=offset)


async def get_moderation_row(db: AsyncSession, *, report_id: uuid.UUID) -> ModerationReportRow | None:
    page = await _moderation_page(
        db, [DynamicStatus.id == report_id, DynamicStatus.report_type.is_not(None)], limit=1, offset=0
    )
    return page.items[0] if page.items else None


async def list_events(db: AsyncSession, *, report_id: uuid.UUID) -> list[ModerationEventRead] | None:
    """Bir bildirimin tüm moderasyon/geri çekme geçmişi (eski -> yeni). Bildirim yoksa None."""
    exists = await db.scalar(select(DynamicStatus.id).where(DynamicStatus.id == report_id))
    if exists is None:
        return None
    rows = (
        await db.execute(
            select(LiveReportEvent, User.display_name)
            .outerjoin(User, User.id == LiveReportEvent.actor_id)
            .where(LiveReportEvent.report_id == report_id)
            .order_by(LiveReportEvent.created_at.asc())
        )
    ).all()
    return [_event_read(event, name) for event, name in rows]
