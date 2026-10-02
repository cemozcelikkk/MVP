"""
Süreli canlı saha bildirimi uçları.

- `/spots/{id}/live-reports`         : aktif bildirimler (herkese açık; giriş opsiyonel), geçmiş, oluşturma
- `/live-reports/{id}/withdraw`      : kendi bildirimini geri çekme (moderatör de çekebilir)
- `/moderation/live-reports...`      : YALNIZCA moderatör/admin (liste, onay/red/geri çekme, işlem geçmişi)

Herkese açık yanıtlarda bildiren kimliği/konumu/tam check-in zamanı YOKTUR (bkz. şema docstring'i).
"""
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_moderator, resolve_user_from_authorization_header
from app.core.database import get_db
from app.models.user import User
from app.schemas.live_report import (
    LiveReportActionResponse,
    LiveReportCreate,
    LiveReportHistoryPage,
    ModerationActionRequest,
    ModerationEventRead,
    ModerationReportPage,
    ModerationReportRow,
    ModerationView,
    SpotLiveReports,
)
from app.services.live_report_service import (
    DuplicateActiveReportError,
    InvalidTransitionError,
    ReportNotFoundError,
    ReportPermissionError,
    create_live_report,
    get_moderation_row,
    get_spot_live_reports,
    list_events,
    list_for_moderation,
    list_history,
    to_report_read,
    transition_report,
)
from app.services.spot_service import SpotNotFoundError

spot_router = APIRouter(prefix="/spots", tags=["live-reports"])
report_router = APIRouter(prefix="/live-reports", tags=["live-reports"])
moderation_router = APIRouter(prefix="/moderation", tags=["moderation"])

_NOT_FOUND = "Bildirim bulunamadı."


def _not_found_spot() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")


@spot_router.get("/{spot_id}/live-reports", response_model=SpotLiveReports)
async def read_live_reports(
    spot_id: uuid.UUID,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> SpotLiveReports:
    """
    Noktanın AKTİF süreli bildirimleri, tür bazlı birleşik ve en ciddi ilk. Süresi dolan,
    geri çekilen ve reddedilenler burada yer almaz (bkz. `/history`). Giriş opsiyoneldir:
    token varsa kendi aktif bildirimin `my_report_id` ile işaretlenir.
    """
    viewer = await resolve_user_from_authorization_header(authorization, db)
    result = await get_spot_live_reports(db, spot_id=spot_id, viewer_id=viewer.id if viewer else None)
    if result is None:
        raise _not_found_spot()
    return result


@spot_router.get("/{spot_id}/live-reports/history", response_model=LiveReportHistoryPage)
async def read_live_report_history(
    spot_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> LiveReportHistoryPage:
    """Süresi geçmiş / geri çekilmiş / reddedilmiş bildirimler (sayfalı, en yeni ilk). Kimlik içermez."""
    viewer = await resolve_user_from_authorization_header(authorization, db)
    if await get_spot_live_reports(db, spot_id=spot_id) is None:
        raise _not_found_spot()
    return await list_history(
        db, spot_id=spot_id, viewer_id=viewer.id if viewer else None, limit=limit, offset=offset
    )


@spot_router.post(
    "/{spot_id}/live-reports",
    response_model=LiveReportActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_live_report_endpoint(
    spot_id: uuid.UUID,
    payload: LiveReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LiveReportActionResponse:
    """
    Süreli saha bildirimi oluşturur (giriş gerekir; check-in ZORUNLU DEĞİL - check-in'i olmayan
    bildirim daha düşük güven düzeyinde görünür). Süre 6/12/24/48 saattir; başlangıç ve bitiş
    sunucuda UTC olarak hesaplanır. Aynı türde aktif bildirimin varsa 409 döner (tekrar
    göndererek destek sayısı artırılamaz); önce geri çekebilirsin.
    """
    try:
        row = await create_live_report(db, spot_id=spot_id, user=current_user, data=payload)
    except SpotNotFoundError:
        raise _not_found_spot()
    except DuplicateActiveReportError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu noktada bu tür için zaten aktif bir bildiriminiz var. Değiştirmek için önce geri çekin.",
        )
    live = await get_spot_live_reports(db, spot_id=spot_id, viewer_id=current_user.id)
    assert live is not None
    return LiveReportActionResponse(report=to_report_read(row, datetime.now(UTC)), live=live)


def _transition_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReportNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    if isinstance(exc, ReportPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok.")
    assert isinstance(exc, InvalidTransitionError)
    detail = (
        "Bu bildirimin süresi dolmuş; geri çekilecek aktif bir bildirim yok."
        if exc.expired
        else f"Bu bildirim '{exc.state.value}' durumunda; bu işlem uygulanamaz."
    )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@report_router.post("/{report_id}/withdraw", response_model=LiveReportActionResponse)
async def withdraw_live_report(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LiveReportActionResponse:
    """
    Kendi bildirimini geri çeker (moderatör/admin başkasınınkini de çekebilir). Satır silinmez,
    `withdrawn` olur ve aktif sonuçlardan düşer; işlem moderasyon geçmişine yazılır.
    Başkasının bildirimi için 403.
    """
    try:
        row = await transition_report(db, report_id=report_id, actor=current_user, action="withdraw")
    except (ReportNotFoundError, ReportPermissionError, InvalidTransitionError) as exc:
        raise _transition_http_error(exc)
    live = await get_spot_live_reports(db, spot_id=row.spot_id, viewer_id=current_user.id)
    assert live is not None
    return LiveReportActionResponse(report=to_report_read(row, datetime.now(UTC)), live=live)


@moderation_router.get("/live-reports", response_model=ModerationReportPage)
async def moderation_list(
    view: Annotated[
        ModerationView, Query(description="pending | active | closed (reddedilen/geri çekilen) | expired")
    ] = "pending",
    spot_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
    _moderator: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationReportPage:
    """Yalnızca moderatör/admin. Bildirenin kimliğini içerir (kötüye kullanım incelemesi)."""
    return await list_for_moderation(db, view=view, spot_id=spot_id, limit=limit, offset=offset)


@moderation_router.post("/live-reports/{report_id}/action", response_model=ModerationReportRow)
async def moderation_action(
    report_id: uuid.UUID,
    payload: ModerationActionRequest,
    moderator: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationReportRow:
    """Bildirimi onayla (`confirm`), reddet (`reject`) veya geri çek (`withdraw`). Satır silinmez."""
    try:
        await transition_report(
            db, report_id=report_id, actor=moderator, action=payload.action, note=payload.note
        )
    except (ReportNotFoundError, ReportPermissionError, InvalidTransitionError) as exc:
        raise _transition_http_error(exc)
    row = await get_moderation_row(db, report_id=report_id)
    assert row is not None
    return row


@moderation_router.get("/live-reports/{report_id}/events", response_model=list[ModerationEventRead])
async def moderation_events(
    report_id: uuid.UUID,
    _moderator: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> list[ModerationEventRead]:
    """Bir bildirimin moderasyon/geri çekme işlem geçmişi (kim, ne zaman, hangi durumdan hangisine)."""
    events = await list_events(db, report_id=report_id)
    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return events
