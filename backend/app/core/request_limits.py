"""Database-backed fixed windows shared by all API workers."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert

from app.models.account_token import RequestQuota


async def allow_request(db, identity: str, maximum: int, seconds: int = 60):
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=seconds)
    key = hashlib.sha256(identity.encode()).hexdigest()
    fresh = RequestQuota.window_start <= cutoff
    stmt = insert(RequestQuota).values(key=key, window_start=now, count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[RequestQuota.key],
        set_={
            "window_start": case((fresh, now), else_=RequestQuota.window_start),
            "count": case((fresh, 1), else_=RequestQuota.count + 1),
        },
    ).returning(RequestQuota.count, RequestQuota.window_start)
    count, start = (await db.execute(stmt)).one()
    # Bounded storage: periodically remove inactive windows.
    if now.second == 0:
        await db.execute(
            delete(RequestQuota).where(RequestQuota.window_start < now - timedelta(days=1))
        )
    await db.commit()
    return count <= maximum, max(1, seconds - int((now - start).total_seconds()))
