"""
OpenStreetMap (Overpass API) üzerinden bir merkez noktanın çevresindeki hazır
mekanları çekip `spots` tablosuna `source=OVERPASS_OSM` olarak toplu ekler.

Kullanım (backend dizininden / api container'ı içinden):

    python -m scripts.fetch_osm_places --lat 37.0 --lng 35.32 --radius 5000
    python -m scripts.fetch_osm_places --lat 37.0 --lng 35.32 --radius 5000 --dry-run

Eşleme (OSM etiketi -> SpotCategory):
    amenity=hospital                                   -> HOSPITAL
    amenity=clinic                                     -> HEALTH_CENTER
    amenity=restaurant + cuisine=seafood|fish          -> FISH_RESTAURANT
    amenity=restaurant + cuisine=steak_house|meat      -> MEAT_RESTAURANT
    tourism=hotel, leisure=swimming_pool               -> HOTEL_POOL

Notlar:
- Tekrar çalıştırılabilir: her nesnenin OSM kimliği (`node/123`, `way/456`)
  `extra_amenities.osm_id`'de saklanır; `uq_spots_osm_id` index'i sayesinde
  aynı nesne ikinci kez eklenmez (INSERT ... ON CONFLICT DO NOTHING). Silinmiş
  (soft-delete) bir OSM spot'u da bu yüzden yeniden canlanmaz.
- Adı olmayan yüzme havuzları atlanır (çoğu site/apartman havuzu), özel
  erişimli (`access=private|no`) havuzlar sorguda elenir.
- İçe aktarılan spot'lara `spot_amenities`/`spot_passability` kaydı UYDURULMAZ
  (yol tipi, ücret, kamp izni OSM'de yok); kullanıcılar sonradan doldurabilir.
- Overpass ortak bir kamu servisidir: geniş yarıçaplarla art arda çalıştırmayın.
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  -- tüm ilişkili modelleri mapper'a kaydeder
from app.core.database import AsyncSessionLocal
from app.models.enums import SpotCategory, SpotSource
from app.models.spot import Spot
from app.utils.geo import lonlat_to_wkb

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "KaravanTR-osm-import/1.0"
MIN_RADIUS_M = 100
MAX_RADIUS_M = 50_000
INSERT_BATCH_SIZE = 500
MAX_TAG_VALUE_LENGTH = 300  # app.schemas.spot.ExtraAmenities ile aynı sınır

FISH_CUISINES = {"seafood", "fish"}
MEAT_CUISINES = {"steak_house", "meat"}

# Ad etiketi olmayan nesneler için başlık.
FALLBACK_TITLES: dict[SpotCategory, str] = {
    SpotCategory.HOSPITAL: "Hastane",
    SpotCategory.HEALTH_CENTER: "Sağlık Ocağı",
    SpotCategory.FISH_RESTAURANT: "Balık Restoranı",
    SpotCategory.MEAT_RESTAURANT: "Et Restoranı",
    SpotCategory.HOTEL_POOL: "Otel",
}

# `extra_amenities`'e kopyalanan OSM etiketleri (OSM anahtarı -> bizim anahtarımız).
KEPT_TAGS = {
    "phone": "phone",
    "contact:phone": "phone",
    "website": "website",
    "contact:website": "website",
    "opening_hours": "opening_hours",
    "cuisine": "cuisine",
    "stars": "stars",
    "emergency": "emergency",
    "healthcare:speciality": "healthcare_speciality",
    "swimming_pool": "swimming_pool",
    "wheelchair": "wheelchair",
}


def build_overpass_query(lat: float, lng: float, radius_m: int, timeout_s: int = 60) -> str:
    """Tek istekte tüm kategorileri çeken Overpass QL sorgusu (`out center` -> way/relation merkezi)."""
    around = f"(around:{radius_m},{lat},{lng})"
    cuisines = "|".join(sorted(FISH_CUISINES | MEAT_CUISINES))
    return f"""
[out:json][timeout:{timeout_s}];
(
  nwr["amenity"~"^(hospital|clinic)$"]{around};
  nwr["amenity"="restaurant"]["cuisine"~"(^|;) *({cuisines}) *(;|$)"]{around};
  nwr["tourism"="hotel"]{around};
  nwr["leisure"="swimming_pool"]["name"]["access"!~"^(private|no)$"]{around};
);
out center tags;
""".strip()


class OverpassError(Exception):
    """Overpass isteği başarısız. `retryable`: meşgul/zaman aşımı - bir süre sonra tekrar denenebilir."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def fetch_overpass(
    query: str, url: str = DEFAULT_OVERPASS_URL, timeout_s: int = 90, *, allow_partial: bool = True
) -> list[dict[str, Any]]:
    """Overpass'a POST atar, ham `elements` listesini döndürür.

    Overpass zaman aşımı/kota hatalarını 200 + `remark` ile bildirir (sonuç eksik
    olabilir). `allow_partial=False` ise bu durum da (tekrar denenebilir) hata sayılır.
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except (http.client.HTTPException, ConnectionError, json.JSONDecodeError) as exc:
        # Yanıt yarıda kesildi (IncompleteRead), bağlantı koptu veya gövde bozuk geldi.
        raise OverpassError(f"Overpass yanıtı eksik/bozuk: {type(exc).__name__}", retryable=True) from exc
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 504):
            raise OverpassError(f"Overpass meşgul (HTTP {exc.code}).", retryable=True) from exc
        raise OverpassError(f"Overpass isteği başarısız: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OverpassError(f"Overpass'a bağlanılamadı: {getattr(exc, 'reason', exc)}", retryable=True) from exc
    if remark := payload.get("remark"):
        if not allow_partial:
            raise OverpassError(f"Overpass sonucu eksik: {remark}", retryable=True)
        print(f"UYARI (Overpass): {remark}", file=sys.stderr)
    return payload.get("elements", [])


def _cuisine_tokens(tags: dict[str, str]) -> set[str]:
    return {token.strip().lower() for token in re.split(r"[;,]", tags.get("cuisine", "")) if token.strip()}


def classify(tags: dict[str, str]) -> SpotCategory | None:
    """OSM etiketlerinden kategori çıkarır; eşleşme yoksa None (nesne atlanır)."""
    amenity = tags.get("amenity")
    if amenity == "hospital":
        return SpotCategory.HOSPITAL
    if amenity == "clinic":
        return SpotCategory.HEALTH_CENTER
    if amenity == "restaurant":
        cuisines = _cuisine_tokens(tags)
        if cuisines & FISH_CUISINES:
            return SpotCategory.FISH_RESTAURANT
        if cuisines & MEAT_CUISINES:
            return SpotCategory.MEAT_RESTAURANT
        return None
    if tags.get("tourism") == "hotel":
        return SpotCategory.HOTEL_POOL
    if tags.get("leisure") == "swimming_pool" and tags.get("name") and tags.get("access") not in ("private", "no"):
        return SpotCategory.HOTEL_POOL
    return None


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


def element_to_row(element: dict[str, Any]) -> dict[str, Any] | None:
    """Bir Overpass elemanını `spots` satırına çevirir; uygun değilse None."""
    tags: dict[str, str] = element.get("tags") or {}
    category = classify(tags)
    coords = _coordinates(element)
    if category is None or coords is None:
        return None
    lng, lat = coords

    osm_id = f"{element['type']}/{element['id']}"
    extra: dict[str, Any] = {"osm_id": osm_id, "osm_url": f"https://www.openstreetmap.org/{osm_id}"}
    for osm_key, our_key in KEPT_TAGS.items():
        if osm_key in tags and our_key not in extra:
            extra[our_key] = tags[osm_key][:MAX_TAG_VALUE_LENGTH]
    if address := _address(tags):
        extra["address"] = address[:MAX_TAG_VALUE_LENGTH]

    name = (tags.get("name") or tags.get("name:tr") or "").strip()
    title = name if len(name) >= 3 else f"{FALLBACK_TITLES[category]} (OSM)"

    return {
        "id": uuid.uuid4(),
        "title": title[:200],
        "description": tags["description"][:5000] if tags.get("description") else None,
        "category": category,
        "source": SpotSource.OVERPASS_OSM,
        "coordinates": lonlat_to_wkb(lng, lat),
        "extra_amenities": extra,
        "is_verified": False,
        "review_count": 0,
        "overnight_status": "unknown",
        "private_property_permission": "unknown",
    }


def elements_to_rows(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Eşleşen elemanları satıra çevirir; aynı OSM nesnesi tek sefer yer alır."""
    rows: dict[str, dict[str, Any]] = {}
    for element in elements:
        row = element_to_row(element)
        if row is not None:
            rows.setdefault(row["extra_amenities"]["osm_id"], row)
    return list(rows.values())


async def bulk_insert_spots(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Satırları INSERT ... ON CONFLICT DO NOTHING ile toplu ekler; yeni eklenen sayısını döndürür."""
    inserted = 0
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        stmt = (
            pg_insert(Spot)
            .values(batch)
            .on_conflict_do_nothing(
                index_elements=[text("(extra_amenities ->> 'osm_id')")],
                index_where=text("source = 'OVERPASS_OSM'"),
            )
            .returning(Spot.id)
        )
        inserted += len((await db.execute(stmt)).all())
    await db.commit()
    return inserted


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Overpass API'den çevredeki mekanları spots tablosuna aktarır.")
    parser.add_argument("--lat", type=float, required=True, help="Merkez enlem, örn. 37.0")
    parser.add_argument("--lng", type=float, required=True, help="Merkez boylam, örn. 35.32")
    parser.add_argument(
        "--radius", type=int, default=5000, help=f"Yarıçap (metre, {MIN_RADIUS_M}-{MAX_RADIUS_M}). Varsayılan 5000."
    )
    parser.add_argument("--dry-run", action="store_true", help="Veritabanına yazmadan sadece özet göster.")
    parser.add_argument("--overpass-url", default=DEFAULT_OVERPASS_URL, help="Overpass API uç noktası.")
    args = parser.parse_args(argv)
    if not -90 <= args.lat <= 90 or not -180 <= args.lng <= 180:
        parser.error("Geçersiz koordinat.")
    if not MIN_RADIUS_M <= args.radius <= MAX_RADIUS_M:
        parser.error(f"--radius {MIN_RADIUS_M} ile {MAX_RADIUS_M} metre arasında olmalı.")
    return args


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    print(f"Overpass sorgulanıyor: ({args.lat}, {args.lng}) çevresinde {args.radius} m ...")
    try:
        elements = fetch_overpass(build_overpass_query(args.lat, args.lng, args.radius), url=args.overpass_url)
    except OverpassError as exc:
        hint = " Birkaç dakika sonra veya daha küçük bir yarıçapla tekrar deneyin." if exc.retryable else ""
        raise SystemExit(f"{exc}{hint}") from exc
    rows = elements_to_rows(elements)

    counts = Counter(row["category"].value for row in rows)
    print(f"{len(elements)} OSM nesnesi alındı, {len(rows)} tanesi eşleşti:")
    for category in SpotCategory:
        if counts[category.value]:
            print(f"  {category.value:<16} {counts[category.value]}")

    if args.dry_run:
        print("--dry-run: veritabanına yazılmadı.")
        return
    if not rows:
        return

    async with AsyncSessionLocal() as db:
        inserted = await bulk_insert_spots(db, rows)
    print(f"{inserted} yeni spot eklendi, {len(rows) - inserted} tanesi zaten vardı (atlandı).")


if __name__ == "__main__":
    asyncio.run(main())
