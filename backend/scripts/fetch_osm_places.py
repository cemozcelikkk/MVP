"""
Bir bölgenin OpenStreetMap hizmet noktası ÖNBELLEĞİNİ önceden ısıtır (osm_pois / osm_tiles).

Normalde gerek yoktur: kullanıcı haritada bir bölgeye baktığında hücreler istek
anında çekilir (bkz. app/services/osm_source.py). Bu betik, ör. yoğun bir tatil
bölgesini yayından önce hazırlamak için aynı mekanizmayı (aynı hücre/TTL/hız
sınırı kurallarıyla) kullanır. `service_points`'e HİÇBİR ŞEY yazmaz - harici
veri yalnızca bir kullanıcı ona katkı yaptığında KaravanTR kaydına dönüşür.
Sağlık noktaları `basemap_pois`'ten gelir (scripts/import_basemap_pois.py).

Kullanım (api container'ı içinden):

    python -m scripts.fetch_osm_places --lat 36.62 --lng 29.11 --radius 8000

Overpass ortak bir kamu servisidir: betik her istek arasında bekler ve
sunucu genelindeki dakikalık sınıra uyar; geniş yarıçaplarla art arda çalıştırmayın.
"""
from __future__ import annotations

import argparse
import asyncio
import math

import app.models  # noqa: F401  -- tüm modelleri mapper'a kaydeder
from app.core.database import AsyncSessionLocal
from app.services.osm_source import ExternalStatus, ensure_tiles, tiles_for_bbox

MIN_RADIUS_M = 500
MAX_RADIUS_M = 15_000
PAUSE_SECONDS = 15


def radius_bbox(lat: float, lng: float, radius_m: int) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat)"""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    return lng - dlon, lat - dlat, lng + dlon, lat + dlat


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bir bölgenin OSM hizmet noktası önbelleğini ısıtır.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--radius", type=int, default=5000, help=f"metre ({MIN_RADIUS_M}-{MAX_RADIUS_M})")
    args = parser.parse_args(argv)
    if not -90 <= args.lat <= 90 or not -180 <= args.lng <= 180:
        parser.error("Geçersiz koordinat.")
    if not MIN_RADIUS_M <= args.radius <= MAX_RADIUS_M:
        parser.error(f"--radius {MIN_RADIUS_M} ile {MAX_RADIUS_M} metre arasında olmalı.")
    return args


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    min_lon, min_lat, max_lon, max_lat = radius_bbox(args.lat, args.lng, args.radius)
    print(f"{len(tiles_for_bbox(min_lon, min_lat, max_lon, max_lat))} hücre hazırlanıyor ...")
    # Görünüm sınırına takılmamak için alanı satır satır (hücre şeritleri) işle.
    step = 0.05
    lat = min_lat
    while lat < max_lat:
        while True:
            async with AsyncSessionLocal() as db:
                status = await ensure_tiles(
                    db, min_lon=min_lon, min_lat=lat, max_lon=max_lon, max_lat=min(lat + step, max_lat)
                )
            print(f"  şerit {lat:.3f}: {status.value}")
            if status in (ExternalStatus.OK, ExternalStatus.DISABLED, ExternalStatus.TOO_WIDE):
                break
            await asyncio.sleep(PAUSE_SECONDS)
            if status is ExternalStatus.UNAVAILABLE:
                print("  Overpass erişilemedi; daha sonra tekrar deneyin.")
                return
        lat += step
    print("Tamam.")


if __name__ == "__main__":
    asyncio.run(main())
