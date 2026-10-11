"""
Harici hizmet noktası kaynağı: OpenStreetMap.

İki OSM kaynağı birlikte kullanılır, ikisi de `service_points`'ten AYRI tutulur:

1. **Hücre önbelleği** (`osm_pois`): Yeme & İçme, WC, duş VE sağlık - istek anında,
   yalnızca bakılan bölge için Overpass'tan **hücre (tile)** bazında çekilip TTL'li tutulur.
2. **Sağlık için ek kaynak** (`basemap_pois`): haftalık, Türkiye geneli içe aktarılan
   tablo (scripts/import_basemap_pois.py). Doluysa hücre çekilmemiş bölgelerde de sağlık
   noktaları hemen görünür; BOŞ olsa da (ör. yeni kurulan production) sağlık noktaları
   hücre önbelleğinden gelir. İki kaynaktaki aynı OSM nesnesi osm_id ile tekilleştirilir.

Overpass kullanım politikasına uyum (https://dev.overpass-api.de/overpass-doc/en/preface/commons.html):
- Her hücre TTL boyunca (varsayılan 7 gün) bir kez çekilir; aynı bölge için
  tekrar istek atılmaz. Tek seferde en fazla `OSM_MAX_TILES_PER_FETCH` hücre,
  bunlar TEK bir Overpass sorgusunda (kapsayan dikdörtgen) istenir.
- Sunucu genelinde dakikada `OVERPASS_REQUESTS_PER_MINUTE` istek sınırı ve
  süreç içi tek eşzamanlı istek; 429/504/zaman aşımında hücre `OSM_FAILURE_BACKOFF_MINUTES`
  boyunca yeniden denenmez.
- İstekler `OVERPASS_USER_AGENT` ile kendini tanıtır.

Kaynak erişilemezse çağıran taraf yalnızca KaravanTR kayıtları + cache'te
kalanlarla devam eder (`ExternalStatus.UNAVAILABLE`); harita hiçbir zaman
Overpass yüzünden hata vermez.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import ServicePointCategory
from app.models.osm_cache import OsmPoi, OsmTile
from app.utils.geo import lonlat_to_wkb

logger = logging.getLogger(__name__)

FISH_CUISINES = {"seafood", "fish"}
MEAT_CUISINES = {"steak_house", "meat", "kebab", "barbecue"}
FOOD_CATEGORIES = frozenset(
    {ServicePointCategory.FISH_RESTAURANT, ServicePointCategory.MEAT_RESTAURANT, ServicePointCategory.OTHER_RESTAURANT}
)
BASIC_CATEGORIES = frozenset({ServicePointCategory.WC, ServicePointCategory.SHOWER})
HEALTH_CATEGORIES = frozenset({ServicePointCategory.HOSPITAL, ServicePointCategory.HEALTH_CENTER})
# Overpass hücrelerinden gelen kategoriler (sağlık ayrıca basemap_pois'ten de gelebilir).
TILE_CATEGORIES = FOOD_CATEGORIES | BASIC_CATEGORIES | HEALTH_CATEGORIES
PRIVATE_ACCESS = ("private", "no", "customers")
MAX_TAG_VALUE_LENGTH = 300

# `tags`'e kopyalanan OSM etiketleri (OSM anahtarı -> bizim anahtarımız).
KEPT_TAGS = {
    "phone": "phone",
    "contact:phone": "phone",
    "website": "website",
    "contact:website": "website",
    "opening_hours": "opening_hours",
    "cuisine": "cuisine",
    "wheelchair": "wheelchair",
    "fee": "fee",
    "charge": "charge",
    "hot_water": "hot_water",
}


class ExternalStatus(str, Enum):
    """Harici kaynağın bu yanıta katkısı - istemci kullanıcıya uygun ipucunu gösterir."""

    OK = "ok"                    # bölgenin tamamı güncel cache'ten
    PARTIAL = "partial"          # bazı hücreler henüz çekilmedi (sonraki istekte tamamlanır)
    UNAVAILABLE = "unavailable"  # Overpass'a ulaşılamadı / sınırda; cache'tekiler + KaravanTR kayıtları
    TOO_WIDE = "too_wide"        # alan çok geniş - yakınlaştırınca restoran/WC/duş verisi gelir
    DISABLED = "disabled"        # OSM_EXTERNAL_ENABLED=false
    NOT_NEEDED = "not_needed"    # istenen kategoriler yalnızca sağlık / hiç harici kategori yok


# --- OSM etiket eşlemesi ----------------------------------------------------------


def _cuisine_tokens(tags: dict[str, str]) -> set[str]:
    return {token.strip().lower() for token in re.split(r"[;,]", tags.get("cuisine", "")) if token.strip()}


def classify(tags: dict[str, str]) -> ServicePointCategory | None:
    """OSM etiketlerinden hizmet kategorisi; eşleşme yoksa None (nesne atlanır)."""
    amenity = tags.get("amenity")
    if amenity == "hospital":
        return ServicePointCategory.HOSPITAL
    if amenity in ("clinic", "doctors"):
        return ServicePointCategory.HEALTH_CENTER
    if amenity in ("restaurant", "fast_food"):
        cuisines = _cuisine_tokens(tags)
        if cuisines & FISH_CUISINES:
            return ServicePointCategory.FISH_RESTAURANT
        if cuisines & MEAT_CUISINES:
            return ServicePointCategory.MEAT_RESTAURANT
        return ServicePointCategory.OTHER_RESTAURANT
    if amenity == "cafe":
        return ServicePointCategory.OTHER_RESTAURANT
    if amenity in ("toilets", "shower") and tags.get("access") not in PRIVATE_ACCESS:
        return ServicePointCategory.WC if amenity == "toilets" else ServicePointCategory.SHOWER
    return None


def fee_status_from_tags(tags: dict[str, Any]) -> str:
    """OSM `fee`/`charge` -> free | paid | unknown (harita verisi; saha doğrulaması değil)."""
    fee = str(tags.get("fee") or "").strip().lower()
    if fee == "no":
        return "free"
    if fee == "yes" or tags.get("charge"):
        return "paid"
    return "unknown"


def _coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    """(lng, lat) - node'larda doğrudan, way/relation'larda `out center` ile gelen merkez."""
    if "lat" in element and "lon" in element:
        return float(element["lon"]), float(element["lat"])
    center = element.get("center")
    if center:
        return float(center["lon"]), float(center["lat"])
    return None


def _address(tags: dict[str, str]) -> str | None:
    street = " ".join(filter(None, (tags.get("addr:street"), tags.get("addr:housenumber"))))
    parts = [p for p in (street, tags.get("addr:district"), tags.get("addr:city")) if p]
    return ", ".join(parts) or None


def element_to_poi(element: dict[str, Any]) -> dict[str, Any] | None:
    """Overpass elemanı -> önbellek satırı sözlüğü (`category`, `name`, `lng`, `lat`, `tags`); uygun değilse None."""
    tags: dict[str, str] = element.get("tags") or {}
    category = classify(tags)
    coords = _coordinates(element)
    if category is None or coords is None:
        return None
    name = (tags.get("name:tr") or tags.get("name") or "").strip()[:200] or None
    if category in FOOD_CATEGORIES and name is None:
        return None  # adsız restoran/kafe gösterilmez - kullanıcı neyi aradığını bilemez

    osm_id = f"{element['type']}/{element['id']}"
    kept: dict[str, Any] = {}
    for osm_key, our_key in KEPT_TAGS.items():
        if osm_key in tags and our_key not in kept:
            kept[our_key] = tags[osm_key][:MAX_TAG_VALUE_LENGTH]
    if address := _address(tags):
        kept["address"] = address[:MAX_TAG_VALUE_LENGTH]
    lng, lat = coords
    return {"osm_id": osm_id, "category": category, "name": name, "lng": lng, "lat": lat, "tags": kept}


# --- Overpass HTTP -----------------------------------------------------------------


class OverpassError(Exception):
    """Overpass isteği başarısız. `retryable`: meşgul/zaman aşımı - sonra tekrar denenebilir."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def build_tile_query(bbox: tuple[float, float, float, float], timeout_s: int) -> str:
    """Yeme & içme + sağlık + WC/duş için bbox sorgusu. `bbox` = (güney, batı, kuzey, doğu)."""
    s, w, n, e = bbox
    area = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    private = "|".join(PRIVATE_ACCESS)
    return f"""
[out:json][timeout:{timeout_s}];
(
  nwr["amenity"~"^(restaurant|fast_food|cafe)$"]["name"]{area};
  nwr["amenity"~"^(hospital|clinic|doctors)$"]{area};
  nwr["amenity"~"^(toilets|shower)$"]["access"!~"^({private})$"]{area};
);
out center tags;
""".strip()


def fetch_overpass(query: str, url: str | None = None, timeout_s: int | None = None) -> list[dict[str, Any]]:
    """Senkron Overpass POST'u (çağıran `asyncio.to_thread` ile çalıştırır). Eksik sonuç (`remark`) hata sayılır."""
    timeout_s = timeout_s or settings.OVERPASS_TIMEOUT_SECONDS
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(
        url or settings.OVERPASS_URL, data=body, headers={"User-Agent": settings.OVERPASS_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s + 5) as response:
            payload = json.load(response)
    except (http.client.HTTPException, ConnectionError, json.JSONDecodeError) as exc:
        raise OverpassError(f"Overpass yanıtı eksik/bozuk: {type(exc).__name__}", retryable=True) from exc
    except urllib.error.HTTPError as exc:
        raise OverpassError(f"Overpass HTTP {exc.code}", retryable=exc.code in (429, 504)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OverpassError(f"Overpass'a bağlanılamadı: {getattr(exc, 'reason', exc)}", retryable=True) from exc
    if remark := payload.get("remark"):
        # Zaman aşımı/kota: kısmi sonucu cache'e yazmak, eksik bölgeyi "tam" sanmak olur.
        raise OverpassError(f"Overpass sonucu eksik: {remark}", retryable=True)
    return payload.get("elements", [])


def fetch_overpass_with_fallback(query: str) -> list[dict[str, Any]]:
    """Ana sunucu; meşgul/zaman aşımı ise sıradaki yedek sunucu (her biri bir kez)."""
    urls = [settings.OVERPASS_URL, *settings.OVERPASS_FALLBACK_URLS]
    last: OverpassError | None = None
    for url in urls:
        try:
            return fetch_overpass(query, url=url)
        except OverpassError as exc:
            logger.warning("Overpass isteği başarısız (%s): %s", url, exc)
            last = exc
            if not exc.retryable:
                break
    assert last is not None
    raise last


# --- Hücreler ----------------------------------------------------------------------


def tile_key(ix: int, iy: int) -> str:
    return f"{settings.OSM_TILE_DEGREES}:{ix}:{iy}"


def tiles_for_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> list[tuple[int, int]]:
    step = settings.OSM_TILE_DEGREES
    xs = range(math.floor(min_lon / step), math.floor(max_lon / step) + 1)
    ys = range(math.floor(min_lat / step), math.floor(max_lat / step) + 1)
    return [(ix, iy) for ix in xs for iy in ys]


def tile_bounds(ix: int, iy: int) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat)"""
    step = settings.OSM_TILE_DEGREES
    return ix * step, iy * step, (ix + 1) * step, (iy + 1) * step


def tile_of(lng: float, lat: float) -> tuple[int, int]:
    step = settings.OSM_TILE_DEGREES
    return math.floor(lng / step), math.floor(lat / step)


# Süreç içinde aynı anda tek Overpass isteği; sunucu geneli sınır `allow_request` ile DB'de.
_FETCH_LOCK = asyncio.Lock()

Fetcher = Callable[[str], list[dict[str, Any]]]


async def _allow_global_request() -> bool:
    from app.core.database import AsyncSessionLocal
    from app.core.request_limits import allow_request

    async with AsyncSessionLocal() as quota_db:
        allowed, _ = await allow_request(quota_db, "overpass-global", settings.OVERPASS_REQUESTS_PER_MINUTE, seconds=60)
    return allowed


async def ensure_tiles(
    db: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    max_view_tiles: int | None = None,
    wait: bool | None = None,
    fetcher: Fetcher | None = None,
    allow_request: Callable[[], Any] | None = None,
) -> ExternalStatus:
    """Alanı kaplayan hücrelerin cache'te güncel olmasını sağlar (gerekirse Overpass'a gider).

    `wait=False` (API varsayılanı, `OSM_FETCH_IN_BACKGROUND`): eksik hücreler arka planda
    çekilir, yanıt beklemez ve `PARTIAL` döner - Overpass yavaşken/çöktüğünde harita
    isteği bekletilmez; istemci kısa süre sonra yeniden sorar. `wait=True`: aynı istekte
    çeker (testler, önbellek ısıtma betiği). Hiçbir koşulda istisna fırlatmaz.
    `fetcher`/`allow_request` testlerde ağ yerine sahte bir kaynak vermek içindir.
    """
    if not settings.OSM_EXTERNAL_ENABLED:
        return ExternalStatus.DISABLED
    cells = tiles_for_bbox(min_lon, min_lat, max_lon, max_lat)
    if len(cells) > (max_view_tiles or settings.OSM_MAX_TILES_PER_VIEW):
        return ExternalStatus.TOO_WIDE
    if wait is None:
        wait = not settings.OSM_FETCH_IN_BACKGROUND

    now = datetime.now(UTC)
    keys = {tile_key(ix, iy): (ix, iy) for ix, iy in cells}
    todo, backing_off = await _tile_state(db, keys, now)
    todo = [c for c in todo if tile_key(*c) not in _IN_FLIGHT]
    if not todo:
        if any(k in _IN_FLIGHT for k in keys):
            return ExternalStatus.PARTIAL
        return ExternalStatus.UNAVAILABLE if backing_off else ExternalStatus.OK

    # Alanın merkezine en yakın hücreler önce.
    cx, cy = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2
    step = settings.OSM_TILE_DEGREES
    todo.sort(key=lambda c: ((c[0] + 0.5) * step - cx) ** 2 + ((c[1] + 0.5) * step - cy) ** 2)
    batch = todo[: settings.OSM_MAX_TILES_PER_FETCH]
    leftover = len(todo) > len(batch)
    batch_keys = {tile_key(*c) for c in batch}

    if not wait:
        _IN_FLIGHT.update(batch_keys)
        task = asyncio.create_task(_fetch_batch_in_background(batch, fetcher, allow_request))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return ExternalStatus.PARTIAL

    async with _FETCH_LOCK:
        todo_now, _ = await _tile_state(db, {k: keys[k] for k in batch_keys}, now)
        if not todo_now:  # kilidi beklerken başka istek doldurmuş
            return ExternalStatus.PARTIAL if leftover else ExternalStatus.OK
        ok = await _fetch_batch(db, batch, fetcher=fetcher, allow_request=allow_request)
    if not ok:
        return ExternalStatus.UNAVAILABLE
    return ExternalStatus.PARTIAL if leftover or backing_off else ExternalStatus.OK


# Arka planda çekilmekte olan hücreler (aynı hücre için ikinci istek atılmaz) ve
# görevlerin çöp toplayıcıya gitmemesi için referansları.
_IN_FLIGHT: set[str] = set()
_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _fetch_batch_in_background(
    batch: list[tuple[int, int]], fetcher: Fetcher | None, allow_request: Callable[[], Any] | None
) -> None:
    from app.core.database import AsyncSessionLocal

    keys = {tile_key(*c) for c in batch}
    try:
        async with _FETCH_LOCK, AsyncSessionLocal() as db:
            todo_now, _ = await _tile_state(db, {tile_key(*c): c for c in batch}, datetime.now(UTC))
            if todo_now:
                await _fetch_batch(db, todo_now, fetcher=fetcher, allow_request=allow_request)
    except Exception:  # arka plan görevi asla sessizce çökmesin
        logger.exception("OSM arka plan çekimi başarısız: %s", sorted(keys))
    finally:
        _IN_FLIGHT.difference_update(keys)


async def _fetch_batch(
    db: AsyncSession,
    batch: list[tuple[int, int]],
    *,
    fetcher: Fetcher | None,
    allow_request: Callable[[], Any] | None,
) -> bool:
    """Hücre grubunu TEK Overpass sorgusuyla (kapsayan dikdörtgen) çekip cache'e yazar."""
    now = datetime.now(UTC)
    batch_keys = {tile_key(*c) for c in batch}
    if not await (allow_request or _allow_global_request)():
        return False  # sunucu geneli dakikalık sınır - hücreler işaretlenmez, sonra tekrar denenir

    b_min_lon = min(tile_bounds(*c)[0] for c in batch)
    b_min_lat = min(tile_bounds(*c)[1] for c in batch)
    b_max_lon = max(tile_bounds(*c)[2] for c in batch)
    b_max_lat = max(tile_bounds(*c)[3] for c in batch)
    query = build_tile_query((b_min_lat, b_min_lon, b_max_lat, b_max_lon), settings.OVERPASS_TIMEOUT_SECONDS)
    try:
        elements = await asyncio.to_thread(fetcher or fetch_overpass_with_fallback, query)
    except Exception:
        logger.warning(
            "OSM hücreleri çekilemedi, %s dk geri çekiliyor: %s",
            settings.OSM_FAILURE_BACKOFF_MINUTES, sorted(batch_keys), exc_info=True,
        )
        retry_after = now + timedelta(minutes=settings.OSM_FAILURE_BACKOFF_MINUTES)
        await _upsert_tiles(db, batch_keys, status="failed", retry_after=retry_after, counts={})
        await db.commit()
        return False

    rows: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = dict.fromkeys(batch_keys, 0)
    for element in elements:
        poi = element_to_poi(element)
        if poi is None or poi["category"] not in TILE_CATEGORIES:
            continue
        key = tile_key(*tile_of(poi["lng"], poi["lat"]))
        if key not in batch_keys:
            continue  # kapsayan dikdörtgenin istenmeyen köşesi
        counts[key] += 1
        rows[poi["osm_id"]] = {
            "osm_id": poi["osm_id"],
            "category": poi["category"],
            "name": poi["name"],
            "coordinates": lonlat_to_wkb(poi["lng"], poi["lat"]),
            "tags": poi["tags"],
            "tile_key": key,
            "fetched_at": now,
        }
    await _replace_tile_pois(db, batch_keys, list(rows.values()), fetched_at=now)
    await _upsert_tiles(db, batch_keys, status="ok", retry_after=None, counts=counts)
    await db.commit()
    return True


async def _tile_state(
    db: AsyncSession, keys: dict[str, tuple[int, int]], now: datetime
) -> tuple[list[tuple[int, int]], bool]:
    """(çekilmesi gereken hücreler, geri çekilme süresinde hücre var mı)."""
    rows = (await db.execute(select(OsmTile).where(OsmTile.key.in_(keys)))).scalars().all()
    ttl = timedelta(hours=settings.OSM_TILE_TTL_HOURS)
    fresh = {row.key for row in rows if row.status == "ok" and row.fetched_at > now - ttl}
    backing_off = {
        row.key for row in rows if row.status == "failed" and row.retry_after is not None and row.retry_after > now
    }
    todo = [cell for key, cell in keys.items() if key not in fresh and key not in backing_off]
    return todo, bool(backing_off)


async def _replace_tile_pois(db: AsyncSession, keys: set[str], rows: list[dict[str, Any]], *, fetched_at: datetime) -> None:
    for start in range(0, len(rows), 500):
        stmt = pg_insert(OsmPoi).values(rows[start : start + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=[OsmPoi.osm_id],
            set_={
                "category": stmt.excluded.category,
                "name": stmt.excluded.name,
                "coordinates": stmt.excluded.coordinates,
                "tags": stmt.excluded.tags,
                "tile_key": stmt.excluded.tile_key,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await db.execute(stmt)
    # Bu hücrelerde artık OSM'de olmayanlar (bu çekimde görülmeyenler) cache'ten düşer.
    await db.execute(delete(OsmPoi).where(OsmPoi.tile_key.in_(keys), OsmPoi.fetched_at < fetched_at))


async def _upsert_tiles(
    db: AsyncSession, keys: set[str], *, status: str, retry_after: datetime | None, counts: dict[str, int]
) -> None:
    values = [
        {"key": key, "status": status, "fetched_at": func.now(), "retry_after": retry_after, "poi_count": counts.get(key, 0)}
        for key in keys
    ]
    stmt = pg_insert(OsmTile).values(values)
    set_ = {"status": stmt.excluded.status, "retry_after": stmt.excluded.retry_after}
    if status == "ok":
        set_ |= {"fetched_at": stmt.excluded.fetched_at, "poi_count": stmt.excluded.poi_count}
    await db.execute(stmt.on_conflict_do_update(index_elements=[OsmTile.key], set_=set_))
