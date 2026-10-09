"""
Türkiye genelindeki önemli OSM noktalarını (hastane, sağlık ocağı, eczane,
akaryakıt, polis) Overpass'tan çekip `basemap_pois` tablosuna yazar. Harita bu
tabloyu zoom 11-13'te gösterir (vektör tile'larda bu POI'ler yalnızca z14+'te var).

Periyodik çalıştırılmak içindir (ör. haftada bir, cron/zamanlanmış görev):

    python -m scripts.import_basemap_pois                 # tüm Türkiye
    python -m scripts.import_basemap_pois --bbox 36.5,29,37,29.5   # sadece bir bölge (test)
    python -m scripts.import_basemap_pois --dry-run

Nasıl çalışır:
- Türkiye'yi kapsayan kutu 2x2 derecelik hücrelere bölünür; her hücre için TEK,
  yalnızca kutu (bbox) filtreli Overpass sorgusu atılır. Ülke sınırıyla
  kesiştirme bilinçli olarak YOK: Overpass'ta çok yavaş (504 zaman aşımı) ve
  gereksiz - harita zaten bu kutuyla sınırlı, sınır bölgesinde komşu ülkenin
  hastanesini göstermek kartografik olarak da doğru.
- Hücreler arasında bekleme, meşgul/zaman aşımı yanıtlarında artan beklemeli
  tekrar deneme ve sonda başarısız hücreler için ikinci bir tur vardır -
  Overpass ortak bir kamu servisidir.
- Her hücrenin sonucu `osm_id` üzerinden upsert edilir (isim/konum güncellenir,
  `last_seen_at` tazelenir) ve hücre başına commit edilir; yarıda kesilen bir
  çalışma o ana kadarki ilerlemeyi korur.
- Yalnızca TÜM hücreler başarılıysa, bu çalışmada görülmeyen (OSM'den kalkmış)
  satırlar silinir. `--bbox` ile kısmi çalıştırmada silme yapılmaz.
"""
from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  -- tüm modelleri mapper'a kaydeder
from app.core.database import AsyncSessionLocal
from app.models.basemap_poi import BASEMAP_POI_CATEGORIES, BasemapPoi
from app.utils.geo import lonlat_to_wkb
from scripts.fetch_osm_places import (
    DEFAULT_OVERPASS_URL,
    MAX_TAG_VALUE_LENGTH,
    OverpassError,
    _coordinates,
    fetch_overpass,
)

# Türkiye'yi (adalar dahil) kapsayan kutu: (güney, batı, kuzey, doğu).
TURKEY_BBOX = (35.8, 25.6, 42.2, 44.9)
CELL_DEGREES = 2.0
PAUSE_BETWEEN_CELLS_S = 3.0
PAUSE_BEFORE_RETRY_ROUND_S = 90.0
MAX_ATTEMPTS = 4
INSERT_BATCH_SIZE = 1000

KEPT_TAGS = ("phone", "emergency", "opening_hours", "brand", "operator")


def build_query(cell: tuple[float, float, float, float], timeout_s: int = 180) -> str:
    """Bir hücre için Overpass QL: kutu içindeki önemli amenity'ler."""
    south, west, north, east = cell
    amenities = "|".join(BASEMAP_POI_CATEGORIES)
    return f"""
[out:json][timeout:{timeout_s}][bbox:{south},{west},{north},{east}];
nwr["amenity"~"^({amenities})$"];
out center tags;
""".strip()


def grid_cells(bbox: tuple[float, float, float, float], step: float = CELL_DEGREES) -> list[tuple[float, float, float, float]]:
    south, west, north, east = bbox
    cells = []
    lat = south
    while lat < north:
        lng = west
        while lng < east:
            cells.append((lat, lng, min(lat + step, north), min(lng + step, east)))
            lng += step
        lat += step
    return cells


def element_to_row(element: dict[str, Any]) -> dict[str, Any] | None:
    tags: dict[str, str] = element.get("tags") or {}
    category = tags.get("amenity")
    coords = _coordinates(element)
    if category not in BASEMAP_POI_CATEGORIES or coords is None:
        return None
    lng, lat = coords
    name = (tags.get("name") or tags.get("name:tr") or "").strip() or None
    return {
        "id": uuid.uuid4(),
        "osm_id": f"{element['type']}/{element['id']}",
        "category": category,
        "name": name[:200] if name else None,
        "coordinates": lonlat_to_wkb(lng, lat),
        "tags": {key: tags[key][:MAX_TAG_VALUE_LENGTH] for key in KEPT_TAGS if key in tags},
    }


def elements_to_rows(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for element in elements:
        row = element_to_row(element)
        if row is not None:
            rows.setdefault(row["osm_id"], row)
    return list(rows.values())


async def upsert_pois(db: AsyncSession, rows: list[dict[str, Any]], seen_at: datetime) -> None:
    """`osm_id` üzerinden upsert; `last_seen_at` her satırda `seen_at` olur."""
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = [{**row, "last_seen_at": seen_at} for row in rows[start : start + INSERT_BATCH_SIZE]]
        stmt = pg_insert(BasemapPoi).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[BasemapPoi.osm_id],
            set_={
                "category": stmt.excluded.category,
                "name": stmt.excluded.name,
                "coordinates": stmt.excluded.coordinates,
                "tags": stmt.excluded.tags,
                "last_seen_at": stmt.excluded.last_seen_at,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
    await db.commit()


async def prune_unseen(db: AsyncSession, run_started_at: datetime) -> int:
    """Bu tam çalışmada görülmeyen (OSM'den kalkmış) satırları siler."""
    result = await db.execute(delete(BasemapPoi).where(BasemapPoi.last_seen_at < run_started_at))
    await db.commit()
    return result.rowcount or 0


def fetch_cell(cell: tuple[float, float, float, float], url: str) -> list[dict[str, Any]]:
    """Bir hücreyi, meşgul/zaman aşımı yanıtlarında artan beklemeyle tekrar deneyerek çeker."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fetch_overpass(build_query(cell), url=url, timeout_s=240, allow_partial=False)
        except OverpassError as exc:
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                raise
            wait = 20 * attempt
            print(f"    {exc} {wait} sn sonra tekrar denenecek ({attempt}/{MAX_ATTEMPTS - 1})")
            time.sleep(wait)
    raise AssertionError("unreachable")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Türkiye geneli önemli OSM POI'lerini basemap_pois tablosuna aktarır.")
    parser.add_argument(
        "--bbox",
        help="Sadece bu bölge: 'güney,batı,kuzey,doğu' (ör. 36.5,29,37,29.5). Verilmezse tüm Türkiye; kısmi çalıştırmada silme yapılmaz.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Veritabanına yazmadan sadece say.")
    parser.add_argument("--overpass-url", default=DEFAULT_OVERPASS_URL)
    args = parser.parse_args(argv)
    if args.bbox:
        try:
            south, west, north, east = (float(v) for v in args.bbox.split(","))
        except ValueError:
            parser.error("--bbox biçimi: güney,batı,kuzey,doğu")
        if not (south < north and west < east):
            parser.error("--bbox: güney < kuzey ve batı < doğu olmalı.")
        args.bbox = (south, west, north, east)
    return args


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    is_full_run = args.bbox is None
    cells = grid_cells(args.bbox or TURKEY_BBOX)
    totals: Counter[str] = Counter()
    failed: list[tuple[float, float, float, float]] = []

    async with AsyncSessionLocal() as db:
        run_started_at = await db.scalar(select(func.now()))
        print(f"{len(cells)} hücre işlenecek ({'tüm Türkiye' if is_full_run else 'kısmi bölge'}).")
        pending = cells
        for round_no in (1, 2):
            if round_no == 2:
                if not failed:
                    break
                print(f"{len(failed)} başarısız hücre {PAUSE_BEFORE_RETRY_ROUND_S:.0f} sn sonra ikinci turda denenecek.")
                time.sleep(PAUSE_BEFORE_RETRY_ROUND_S)
                pending, failed = failed, []
            for index, cell in enumerate(pending, start=1):
                if index > 1:
                    time.sleep(PAUSE_BETWEEN_CELLS_S)
                label = f"[{index}/{len(pending)}]" + (" (2. tur)" if round_no == 2 else "")
                try:
                    rows = elements_to_rows(fetch_cell(cell, args.overpass_url))
                except OverpassError as exc:
                    print(f"{label} {cell}: BAŞARISIZ - {exc}")
                    failed.append(cell)
                    continue
                counts = Counter(row["category"] for row in rows)
                totals.update(counts)
                print(f"{label} {cell}: {len(rows)} nokta {dict(counts) if rows else ''}")
                if rows and not args.dry_run:
                    await upsert_pois(db, rows, run_started_at)

        print("Toplam:", dict(totals))
        if args.dry_run:
            print("--dry-run: veritabanına yazılmadı.")
        elif failed:
            print(f"{len(failed)} hücre başarısız; eski kayıtlar silinmedi. Daha sonra tekrar çalıştırın.")
        elif is_full_run:
            print(f"OSM'den kalkmış {await prune_unseen(db, run_started_at)} nokta silindi.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
