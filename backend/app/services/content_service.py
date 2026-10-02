from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.content_report import ContentReport, SpotChange
from app.models.review import Review
from app.models.spot import Spot
from app.models.spot_photo import SpotPhoto


def snapshot_spot(spot):
    import json

    from app.schemas.spot_amenities import SpotAmenitiesRead
    from app.schemas.spot_passability import SpotPassabilityRead
    from app.utils.geo import wkb_to_lonlat

    longitude, latitude = wkb_to_lonlat(spot.coordinates)
    # Audit snapshots contain editable fields, not live aggregates or SQL timestamp expressions.
    excluded = {
        "coordinates",
        "created_by",
        "created_at",
        "updated_at",
        "average_rating",
        "review_count",
    }
    values = {
        column.name: getattr(spot, column.name)
        for column in Spot.__table__.columns
        if column.name not in excluded
    }
    values["amenities"] = (
        SpotAmenitiesRead.model_validate(spot.amenities).model_dump(mode="json")
        if spot.amenities
        else None
    )
    values["passability"] = (
        SpotPassabilityRead.model_validate(spot.passability).model_dump(mode="json")
        if spot.passability
        else None
    )
    return json.loads(
        json.dumps(
            {"geometry": {"coordinates": [longitude, latitude]}, "properties": values},
            default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value),
        )
    )


def record_change(db, spot, actor_id, action, before=None):
    after = snapshot_spot(spot)
    if before is None or before != after:
        db.add(
            SpotChange(
                spot_id=spot.id, actor_id=actor_id, action=action, before=before, after=after
            )
        )


async def create_report(db, spot_id, user_id, data):
    spot = await db.get(Spot, spot_id)
    if not spot or spot.deleted_at:
        raise HTTPException(404, "Nokta bulunamadı.")
    model = {"spot": Spot, "photo": SpotPhoto, "review": Review}[data.target_kind]
    target = await db.get(model, data.target_id)
    if (
        not target
        or (data.target_kind == "spot" and target.id != spot_id)
        or (data.target_kind != "spot" and target.spot_id != spot_id)
    ):
        raise HTTPException(404, "Bildirilen içerik bu noktada bulunamadı.")
    row = ContentReport(spot_id=spot_id, reporter_id=user_id, **data.model_dump())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Aynı içerik için bekleyen bildiriminiz var.")
    await db.refresh(row)
    return row


async def resolve_report(db, report_id, actor, data):
    row = await db.scalar(
        select(ContentReport).where(ContentReport.id == report_id).with_for_update()
    )
    if not row:
        raise HTTPException(404, "Bildirim bulunamadı.")
    if row.state != "pending":
        raise HTTPException(409, "Bildirim daha önce sonuçlandırılmış.")
    if data.action == "hide":
        if row.target_kind == "spot":
            from app.services.spot_service import get_spot_by_id

            spot = await get_spot_by_id(db, spot_id=row.spot_id)
            if spot:
                before = snapshot_spot(spot)
                spot.deleted_at = datetime.now(UTC)
                record_change(db, spot, actor.id, "hidden", before)
        elif row.target_kind == "photo":
            photo = await db.get(SpotPhoto, row.target_id)
            if photo:
                photo.is_hidden = True
        else:
            review = await db.get(Review, row.target_id)
            if review:
                review.is_active = False
                from app.services.review_service import _refresh_spot_rating_summary

                await _refresh_spot_rating_summary(db, row.spot_id)
        await db.execute(
            Spot.__table__.update().where(Spot.id == row.spot_id).values(updated_at=func.now())
        )
    row.state = "rejected" if data.action == "reject" else "resolved"
    row.resolution_note = data.note
    row.resolved_by = actor.id
    row.resolved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return row
