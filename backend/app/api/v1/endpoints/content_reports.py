import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_moderator
from app.core.database import get_db
from app.models.content_report import ContentReport, SpotChange
from app.models.user import User
from app.schemas.content_report import (
    ContentReportCreate,
    ContentReportRead,
    ContentReportResolution,
    SpotChangeRead,
)
from app.services.content_service import create_report, resolve_report

router = APIRouter(tags=["content reports"])


@router.post("/spots/{spot_id}/content-reports", response_model=ContentReportRead, status_code=201)
async def report_content(
    spot_id: uuid.UUID,
    payload: ContentReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_report(db, spot_id, user.id, payload)


@router.get("/moderation/content-reports", response_model=list[ContentReportRead])
async def report_queue(
    state: str = Query("pending", pattern="^(pending|resolved|rejected)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
):
    return list(
        (
            await db.scalars(
                select(ContentReport)
                .where(ContentReport.state == state)
                .order_by(ContentReport.created_at.desc(), ContentReport.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )


@router.post("/moderation/content-reports/{report_id}/resolve", response_model=ContentReportRead)
async def resolve_content(
    report_id: uuid.UUID,
    payload: ContentReportResolution,
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
):
    return await resolve_report(db, report_id, user, payload)


@router.get("/spots/{spot_id}/changes", response_model=list[SpotChangeRead])
async def history(
    spot_id: uuid.UUID,
    user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(0, ge=0),
):
    return list(
        (
            await db.scalars(
                select(SpotChange)
                .where(SpotChange.spot_id == spot_id)
                .order_by(SpotChange.created_at.desc(), SpotChange.id)
                .offset(offset)
                .limit(30)
            )
        ).all()
    )
