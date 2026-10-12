"""
OSM önbelleği arka plan yenileyicisi.

Kamu Overpass sunucuları zaman zaman tamamen meşgul olur; o anda istenen hücreler
`failed`/`pending` kalır. Önceden bu hücreler ancak bir kullanıcı aynı bölgeye tekrar
baktığında yeniden deneniyordu - kimse bakmazsa bölge boş kalıyordu. Bu görev her
`OSM_REFRESH_INTERVAL_SECONDS`'ta, son `OSM_REFRESH_REQUEST_WINDOW_HOURS` saatte istenmiş
ve bekleme süresi (üstel: 1 dk → 30 dk) dolmuş hücrelerden EN SON isteneni ve komşularını
tek Overpass sorgusuyla çeker.

- Birden çok uvicorn worker'ı olsa da aynı anda TEK süreç çalışır (PostgreSQL advisory lock).
- Sunucu geneli dakikalık Overpass sınırına uyar (`_fetch_batch` içindeki `allow_request`).
- Her döngüde en fazla bir Overpass sorgusu; hiçbir şey yoksa sadece hafif bir SELECT.
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.config import settings
from app.models.osm_cache import OsmTile
from app.services import osm_source

logger = logging.getLogger(__name__)

# Tüm KaravanTR süreçleri için ortak kilit anahtarı (rastgele sabit).
ADVISORY_LOCK_KEY = 7_734_101


def _parse_key(key: str) -> tuple[int, int] | None:
    """"0.05:<ix>:<iy>" -> (ix, iy); farklı hücre boyuyla yazılmış eski anahtarlar atlanır."""
    try:
        degrees, ix, iy = key.split(":")
        if float(degrees) != settings.OSM_TILE_DEGREES:
            return None
        return int(ix), int(iy)
    except ValueError:
        return None


async def refresh_due_tiles(*, fetcher=None, allow_request=None) -> int:
    """Bir yenileme turu. Denenen hücre sayısını döndürür (0 = yapılacak iş yok / kilit başkasında).

    Kilit AYRI ve tur boyunca açık tutulan bir bağlantıda alınır: oturum (`db`) ara commit'lerde
    bağlantısını havuza geri verir; kilit oturumda alınsaydı başka bir bağlantıda bırakılmaya
    çalışılır ve takılı kalırdı.
    """
    from app.core.database import AsyncSessionLocal, engine

    if not settings.OSM_EXTERNAL_ENABLED:
        return 0
    async with engine.connect() as lock_conn:
        locked = (await lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})).scalar()
        await lock_conn.commit()
        if not locked:
            return 0
        try:
            async with AsyncSessionLocal() as db:
                return await _refresh_turn(db, fetcher=fetcher, allow_request=allow_request)
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
            await lock_conn.commit()


async def _refresh_turn(db, *, fetcher, allow_request) -> int:
    now = datetime.now(UTC)
    window = now - timedelta(hours=settings.OSM_REFRESH_REQUEST_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(OsmTile.key, OsmTile.attempts)
            .where(
                OsmTile.status.in_(("failed", "pending")),
                (OsmTile.retry_after.is_(None)) | (OsmTile.retry_after <= now),
                OsmTile.last_requested_at >= window,
            )
            .order_by(OsmTile.last_requested_at.desc())
            .limit(200)
        )
    ).all()
    attempts = {key: n for key, n in rows}
    cells = [c for c in (_parse_key(key) for key, _ in rows) if c is not None]
    cells = [c for c in cells if osm_source.tile_key(*c) not in osm_source._IN_FLIGHT]
    if not cells:
        return 0
    # En son istenen hücre ve ona en yakın olanlar - tek kapsayan dikdörtgen sorgusu.
    ax, ay = cells[0]
    cells.sort(key=lambda c: (c[0] - ax) ** 2 + (c[1] - ay) ** 2)
    # Tekrar tekrar başarısız olan hücreler daha küçük gruplarla denenir (6 → 3 → 1).
    size = osm_source.batch_size_for(attempts.get(osm_source.tile_key(ax, ay), 0))
    batch = [c for c in cells if abs(c[0] - ax) <= 2 and abs(c[1] - ay) <= 2][:size]
    keys = {osm_source.tile_key(*c) for c in batch}
    osm_source._IN_FLIGHT.update(keys)
    try:
        async with osm_source._FETCH_LOCK:
            ok = await osm_source._fetch_batch(db, batch, fetcher=fetcher, allow_request=allow_request)
    finally:
        osm_source._IN_FLIGHT.difference_update(keys)
    logger.info("OSM yenileyici: %d hücre %s", len(batch), "çekildi" if ok else "yine başarısız")
    return len(batch)


async def run_forever() -> None:
    """Uygulama ömrü boyunca çalışan döngü (app.main lifespan başlatır/durdurur)."""
    logger.info("OSM yenileyici başladı (her %ss)", settings.OSM_REFRESH_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(settings.OSM_REFRESH_INTERVAL_SECONDS)
        try:
            await refresh_due_tiles()
        except asyncio.CancelledError:
            raise
        except Exception:  # döngü asla ölmesin
            logger.exception("OSM yenileyici turu başarısız")
