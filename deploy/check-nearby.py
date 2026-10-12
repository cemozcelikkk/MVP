"""
"Yakınımdakiler" (hizmet noktaları) production teşhisi - SALT OKUNUR, gizli değer yazdırmaz.

API konteynerinin İÇİNDE çalışır (Cloudflare/Caddy devre dışı), zincirin hangi halkasının
koptuğunu gösterir: migration sürümü, tablolar, sağlık verisi (basemap_pois), OSM önbelleği,
Overpass'a çıkış, servis katmanının gerçek "yakınımdakiler" yanıtı ve ayarlar.

    docker compose --env-file deploy/.env.production -f deploy/compose.production.yml \
        exec -T api python - < deploy/check-nearby.py

Varsayılan test noktası Kaş merkez; farklı bir yer için: NEARBY_LAT / NEARBY_LNG ortam değişkenleri.
"""
import asyncio
import os
import time

from sqlalchemy import text

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal

EXPECTED_REVISION = "c6e2a8d4f0b3"
LAT = float(os.environ.get("NEARBY_LAT", "36.2005"))
LNG = float(os.environ.get("NEARBY_LNG", "29.6395"))
problems: list[str] = []


def line(label: str, value) -> None:
    print(f"  {label:<38} {value}")


async def scalar(db, sql: str, **params):
    try:
        return (await db.execute(text(sql), params)).scalar()
    except Exception as exc:  # tablo yoksa vb.
        await db.rollback()
        return f"HATA: {type(exc).__name__}"


async def main() -> None:
    print("\n== Ayarlar")
    line("ENVIRONMENT", settings.ENVIRONMENT)
    line("OSM_EXTERNAL_ENABLED", settings.OSM_EXTERNAL_ENABLED)
    line("OSM_FETCH_IN_BACKGROUND", settings.OSM_FETCH_IN_BACKGROUND)
    line("OVERPASS_URL", settings.OVERPASS_URL)
    line("OVERPASS_USER_AGENT", settings.OVERPASS_USER_AGENT)
    line("RATE_LIMIT_ENABLED / okuma limiti", f"{settings.RATE_LIMIT_ENABLED} / {settings.RATE_LIMIT_READ_PER_MINUTE} dk")
    if "local development" in settings.OVERPASS_USER_AGENT:
        problems.append("OVERPASS_USER_AGENT varsayılan değerde - .env.production'a gerçek ad + iletişim ekleyin.")
    if not settings.OSM_EXTERNAL_ENABLED:
        problems.append("OSM_EXTERNAL_ENABLED=false - harici restoran/sağlık/WC verisi kapalı.")

    async with AsyncSessionLocal() as db:
        print("\n== Veritabanı")
        version = await scalar(db, "SELECT version_num FROM alembic_version")
        line("alembic sürümü", version)
        if version != EXPECTED_REVISION:
            problems.append(f"Migration güncel değil ({version}); beklenen {EXPECTED_REVISION} - yeni sürüm deploy edilmemiş.")
        sp = await scalar(db, "SELECT count(*) FROM service_points WHERE deleted_at IS NULL")
        line("service_points (aktif)", sp)
        health = await scalar(db, "SELECT count(*) FROM basemap_pois WHERE category IN ('hospital','clinic')")
        line("basemap_pois hastane+sağlık ocağı", health)
        if isinstance(health, int) and health == 0:
            problems.append("basemap_pois boş - harita kaynaklı sağlık noktaları gösterilemez (scripts.import_basemap_pois çalıştırın).")
        line("osm_pois (önbellek)", await scalar(db, "SELECT count(*) FROM osm_pois"))
        tiles_ok = await scalar(db, "SELECT count(*) FROM osm_tiles WHERE status='ok'")
        tiles_failed = await scalar(db, "SELECT count(*) FROM osm_tiles WHERE status='failed'")
        tiles_pending = await scalar(db, "SELECT count(*) FROM osm_tiles WHERE status='pending'")
        line("osm_tiles ok / failed / pending", f"{tiles_ok} / {tiles_failed} / {tiles_pending}")
        near = await scalar(
            db,
            "SELECT count(*) FROM osm_pois WHERE ST_DWithin(coordinates::geography, "
            "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, 5000)",
            lng=LNG, lat=LAT,
        )
        line("önbellekte test noktasına 5 km içinde", near)

        print(f"\n== Test noktasının hücreleri ({LAT}, {LNG}, 5 km)")
        from app.services.osm_source import tile_key, tiles_for_bbox

        keys = [tile_key(*c) for c in tiles_for_bbox(LNG - 0.056, LAT - 0.045, LNG + 0.056, LAT + 0.045)]
        rows = (
            await db.execute(
                text("SELECT key, status, attempts, retry_after FROM osm_tiles WHERE key = ANY(:k)"), {"k": keys}
            )
        ).all()
        known = {r.key: r for r in rows}
        summary: dict[str, int] = {}
        for key in keys:
            state = known[key].status if key in known else "hiç istenmemiş"
            summary[state] = summary.get(state, 0) + 1
        line("hücre durumları", summary)
        failed = [r for r in rows if r.status == "failed" and r.retry_after]
        if failed:
            line("başarısız hücrede en çok deneme", max(r.attempts for r in failed))
            line("sıradaki otomatik deneme", min(r.retry_after for r in failed).isoformat(timespec="seconds"))
        line("inceleme bekleyen eski kayıt", await scalar(
            db, "SELECT count(*) FROM spots WHERE deleted_at IS NULL AND extra_amenities->>'category_review'='pending'"))

    print("\n== Overpass sunucuları (her biri TEK deneme, küçük sorgu)")
    from app.services.osm_source import build_tile_query, fetch_overpass, fetch_overpass_with_fallback

    query = build_tile_query((LAT - 0.005, LNG - 0.005, LAT + 0.005, LNG + 0.005), 15)
    for url in [settings.OVERPASS_URL, *settings.OVERPASS_FALLBACK_URLS]:
        started = time.monotonic()
        try:
            elements = await asyncio.to_thread(fetch_overpass, query, url)
            line(url.split("/")[2], f"OK - {len(elements)} nesne, {time.monotonic() - started:.1f} sn")
        except Exception as exc:
            line(url.split("/")[2], f"hata - {exc} ({time.monotonic() - started:.1f} sn)")
    started = time.monotonic()
    try:
        elements = await asyncio.to_thread(fetch_overpass_with_fallback, query)
        line("uygulamanın tekrar denemeli çağrısı", f"OK - {len(elements)} nesne, {time.monotonic() - started:.1f} sn")
    except Exception as exc:
        line("uygulamanın tekrar denemeli çağrısı", f"BAŞARISIZ - {exc} ({time.monotonic() - started:.1f} sn)")
        problems.append(
            "Overpass'ın tüm sunucuları şu an yanıt vermiyor (kamu servisi). Başarısız hücreler arka plan "
            "yenileyicisiyle 1-30 dk arayla kendiliğinden tekrar denenir; KaravanTR kayıtları ve önbellek çalışır."
        )

    print(f"\n== Servis katmanı: yakınımdakiler ({LAT}, {LNG}, 5 km)")
    from app.services.service_point_service import list_nearby

    async with AsyncSessionLocal() as db:
        try:
            rows, status = await list_nearby(db, latitude=LAT, longitude=LNG, radius_m=5000)
            by_group: dict[str, int] = {}
            for view, _ in rows:
                group = getattr(view, "category").value
                by_group[group] = by_group.get(group, 0) + 1
            line("external_status", status.value)
            line("nokta sayısı (kategoriye göre)", by_group or 0)
            if status.value == "partial":
                print("  (bölge arka planda çekiliyor - 30-60 sn sonra bu betiği tekrar çalıştırın)")
        except Exception as exc:
            line("HATA", f"{type(exc).__name__}: {exc}")
            problems.append("Yakınımdakiler servis çağrısı hata verdi - api loglarına bakın.")

    print("\n== Sonuç")
    if problems:
        for problem in problems:
            print(f"  ! {problem}")
    else:
        print("  Sunucu tarafı sağlıklı. Tarayıcıda hâlâ çalışmıyorsa Cloudflare'i (403/challenge) ve konum iznini kontrol edin.")


asyncio.run(main())
