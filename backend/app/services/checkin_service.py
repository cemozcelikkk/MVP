"""
Check-in ("buradayım") oluşturma iş mantığı.

İki katmanlı bir istismar (abuse) engeli içerir:
1. Konum doğrulaması (anti-spoofing): kullanıcı, spot'a PostGIS
   `ST_DWithin` ile ölçülen gerçek mesafesi CHECK_IN_MAX_DISTANCE_METERS'ı
   aşıyorsa check-in reddedilir - oturduğu yerden trust_score kasamaz.
2. Günlük mükerrer engeli: aynı kullanıcı aynı spota aynı (UTC) gün
   içinde ikinci kez check-in yapamaz.
"""
import uuid
from datetime import datetime, time, timezone

from geoalchemy2.types import Geography
from sqlalchemy import cast, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check_in import CheckIn
from app.models.spot import Spot
from app.models.user import User
from app.schemas.check_in import CheckInCreate, CheckInRead

# Kullanıcı, check-in yapacağı spot'a en fazla bu kadar (metre) uzaklıkta olabilir.
CHECK_IN_MAX_DISTANCE_METERS = 500


class CheckInTooFarError(Exception):
    """Kullanıcının bildirdiği konum, spot'a CHECK_IN_MAX_DISTANCE_METERS'tan uzak."""


class DuplicateCheckInError(Exception):
    """Kullanıcı bugün (UTC) bu spota zaten check-in yapmış."""


async def add_check_in(
    db: AsyncSession,
    *,
    spot_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CheckInCreate,
) -> CheckInRead | None:
    """
    Spot bulunamazsa (veya soft-delete edilmişse) `None` döner -> endpoint
    404 çevirir. Mesafe/mükerrer ihlallerinde ilgili exception fırlatılır.
    """
    # --- 1) Varlık + mesafe kontrolü tek sorguda ---
    # ST_DWithin, metre cinsinden doğru mesafe ölçebilmek için `geography`
    # tipine cast gerektirir; `geometry` üzerinde doğrudan çalıştırılırsa
    # derece cinsinden (yanlış) bir eşik yorumlanır.
    user_point = cast(
        func.ST_SetSRID(func.ST_MakePoint(data.longitude, data.latitude), 4326),
        Geography,
    )
    row = (
        await db.execute(
            select(func.ST_DWithin(cast(Spot.coordinates, Geography), user_point, CHECK_IN_MAX_DISTANCE_METERS))
            .where(Spot.id == spot_id, Spot.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        return None  # spot yok / soft-delete edilmiş
    is_within_range: bool = row[0]
    if not is_within_range:
        raise CheckInTooFarError(spot_id)

    # --- 2) Günlük mükerrer kontrolü (aynı kullanıcı + aynı spot + bugün UTC) ---
    today_start_utc = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    already_checked_in_today = await db.scalar(
        select(CheckIn.id).where(
            CheckIn.spot_id == spot_id,
            CheckIn.user_id == user_id,
            CheckIn.checked_in_at >= today_start_utc,
        )
    )
    if already_checked_in_today is not None:
        raise DuplicateCheckInError(spot_id)

    check_in_obj = CheckIn(spot_id=spot_id, user_id=user_id, planned_nights=data.planned_nights)
    db.add(check_in_obj)
    await db.flush()
    await db.refresh(check_in_obj, attribute_names=["checked_in_at"])
    check_in_read = CheckInRead.model_validate(check_in_obj)

    # Basit bir güven puanı temeli: her (konumu doğrulanmış) check-in +1
    # trust_score. `User.trust_score + 1` ifadesi DB tarafında atomik SET
    # olarak çalışır, race condition oluşturmaz.
    await db.execute(
        sa_update(User).where(User.id == user_id).values(trust_score=User.trust_score + 1)
    )

    await db.commit()
    return check_in_read
