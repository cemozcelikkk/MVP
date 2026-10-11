"""
Eski "çok kategorili" `spots` kayıtlarının yeni modele (kamp noktası / hizmet noktası)
eşlenmesi - TEK KAYNAK burası; migration `e3a9c5d1f7b4` aynı kuralları kendi
içinde (bağımsız SQL olarak) uygular, `scripts/category_migration_report.py` bu
modülle taşımadan ÖNCE ne olacağını raporlar, moderatör kararları da buradan geçer.

## Eşleme tablosu

| Eski `spots.category` | Yeni yer                                   | Değerlendirmeler                          |
|-----------------------|--------------------------------------------|-------------------------------------------|
| CAMPING               | `spots` (değişmez)                         | değişmez (7 boyutlu)                      |
| HOTEL_POOL            | `spots` (değişmez, yeni eklemeye kapalı)   | değişmez                                  |
| FISH_RESTAURANT       | `service_points` FISH_RESTAURANT           | genel puan + yorum -> restoran değerlendirmesi |
| MEAT_RESTAURANT       | `service_points` MEAT_RESTAURANT           | genel puan + yorum -> restoran değerlendirmesi |
| HOSPITAL              | `service_points` HOSPITAL                  | (sağlıkta değerlendirme yok)              |
| HEALTH_CENTER         | `service_points` HEALTH_CENTER             | (sağlıkta değerlendirme yok)              |

## Belirsiz kayıtlar OTOMATİK TAŞINMAZ

Restoran/sağlık kategorisindeki bir kayıt kamp alanına özgü veri taşıyorsa (ör.
karavanların gece kalabildiği bir balık restoranı), taşımak o veriyi görünmez
kılardı. Bu kayıtlar `spots`'ta, olduğu gibi kalır; `extra_amenities`'e
`category_review=pending` ve nedenler yazılır ve moderatör kuyruğuna düşer
(bkz. `resolve_category_review`). Belirsizlik sinyalleri (`CAMP_SIGNALS`):

- check-in, canlı saha bildirimi, saha doğrulaması, fotoğraf, kaydedilmiş liste
- 7 boyutlu ölçüt veya araç anlık görüntüsü içeren değerlendirme
- sağlık kaydında HERHANGİ bir değerlendirme (yeni modelde sağlıkta değerlendirme yok)
- geceleme kuralı / giriş bilgisi, kamp olanakları (su, elektrik, WC ...), araç kısıtları
- bekleyen içerik bildirimi

Hiçbir kayıt FİZİKSEL OLARAK SİLİNMEZ: taşınan spot soft-delete edilir ve
`moved_to_service_points=true` ile işaretlenir; değerlendirme satırları `reviews`
tablosunda kalır. Downgrade hepsini geri açar.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ServicePointCategory, SpotCategory
from app.models.review import Review
from app.models.service_point import ServicePoint, ServicePointReview
from app.models.spot import Spot
from app.models.user import User

MOVABLE_CATEGORIES = ("FISH_RESTAURANT", "MEAT_RESTAURANT", "HOSPITAL", "HEALTH_CENTER")
FOOD_CATEGORIES = ("FISH_RESTAURANT", "MEAT_RESTAURANT")

# Her biri: (neden kodu, `s` = spots satırı için SQL koşulu). Migration'daki kopyayla AYNI olmalı.
CAMP_SIGNALS: list[tuple[str, str]] = [
    ("check_in", "EXISTS (SELECT 1 FROM check_ins x WHERE x.spot_id = s.id)"),
    ("live_report", "EXISTS (SELECT 1 FROM dynamic_status x WHERE x.spot_id = s.id)"),
    ("field_verification", "EXISTS (SELECT 1 FROM spot_field_verifications x WHERE x.spot_id = s.id)"),
    ("photo", "EXISTS (SELECT 1 FROM spot_photos x WHERE x.spot_id = s.id)"),
    ("saved_list", "EXISTS (SELECT 1 FROM saved_list_items x WHERE x.spot_id = s.id)"),
    (
        "camp_review",
        "EXISTS (SELECT 1 FROM reviews x WHERE x.spot_id = s.id AND (x.safety_rating IS NOT NULL OR "
        "x.quietness_rating IS NOT NULL OR x.road_access_rating IS NOT NULL OR x.ground_suitability_rating IS NOT NULL OR "
        "x.cleanliness_rating IS NOT NULL OR x.view_rating IS NOT NULL OR x.signal_rating IS NOT NULL OR "
        "x.vehicle_type_snapshot IS NOT NULL))",
    ),
    (
        "health_review",
        "s.category IN ('HOSPITAL','HEALTH_CENTER') AND EXISTS (SELECT 1 FROM reviews x WHERE x.spot_id = s.id)",
    ),
    (
        "camp_rules",
        "(s.overnight_status <> 'unknown' OR s.max_stay_nights IS NOT NULL OR s.rule_description IS NOT NULL OR "
        "s.rule_source IS NOT NULL OR s.private_property_permission <> 'unknown' OR s.entry_latitude IS NOT NULL OR "
        "s.approach_description IS NOT NULL OR s.access_season IS NOT NULL)",
    ),
    (
        "camp_amenities",
        "EXISTS (SELECT 1 FROM spot_amenities a WHERE a.spot_id = s.id AND (a.fresh_water_thread OR a.black_water OR "
        "a.grey_water OR a.electricity_220v OR a.has_toilet OR a.has_trash_bins OR a.rule_information_known OR "
        "a.gsm_signals <> '{}'::jsonb))",
    ),
    (
        "vehicle_access",
        "EXISTS (SELECT 1 FROM spot_passability p WHERE p.spot_id = s.id AND (p.road_type <> 'asphalt' OR "
        "p.max_vehicle_length IS NOT NULL OR p.max_vehicle_width IS NOT NULL OR p.max_vehicle_height IS NOT NULL OR "
        "p.max_vehicle_weight_kg IS NOT NULL OR p.clearance_required = 'high_4x4' OR p.steep_incline OR "
        "cardinality(p.caravan_types_allowed) > 0))",
    ),
    ("open_report", "EXISTS (SELECT 1 FROM content_reports x WHERE x.spot_id = s.id AND x.state = 'pending')"),
]

REASON_LABELS = {
    "check_in": "check-in kaydı var",
    "live_report": "canlı saha bildirimi var",
    "field_verification": "saha doğrulaması var",
    "photo": "fotoğrafı var",
    "saved_list": "kullanıcı listelerinde kayıtlı",
    "camp_review": "kamp ölçütleriyle değerlendirilmiş",
    "health_review": "sağlık kaydına değerlendirme yazılmış",
    "camp_rules": "geceleme/giriş bilgisi girilmiş",
    "camp_amenities": "kamp olanakları işaretlenmiş",
    "vehicle_access": "araç kısıtları girilmiş",
    "open_report": "bekleyen içerik bildirimi var",
}


def reasons_sql() -> str:
    """`s` takma adlı spots satırı için belirsizlik nedenlerini dizi olarak veren SQL ifadesi."""
    cases = ", ".join(f"CASE WHEN {condition} THEN '{code}' END" for code, condition in CAMP_SIGNALS)
    return f"array_remove(ARRAY[{cases}]::text[], NULL)"


async def classify_legacy_spots(db: AsyncSession) -> list[dict]:
    """Taşınabilir kategorideki AKTİF spot'lar ve kararı: `move` veya `review` (+ nedenler)."""
    categories = ",".join(f"'{c}'" for c in MOVABLE_CATEGORIES)
    rows = (
        await db.execute(
            text(
                f"SELECT s.id, s.title, s.category::text AS category, {reasons_sql()} AS reasons "
                f"FROM spots s WHERE s.deleted_at IS NULL AND s.category::text IN ({categories}) ORDER BY s.created_at"
            )
        )
    ).mappings().all()
    return [
        {**row, "reasons": list(row["reasons"]), "decision": "review" if row["reasons"] else "move"}
        for row in rows
    ]


# --- Moderatör kararı ----------------------------------------------------------------


class CategoryReviewError(Exception):
    pass


async def pending_reviews(db: AsyncSession) -> list[Spot]:
    stmt = (
        select(Spot)
        .where(Spot.deleted_at.is_(None), Spot.extra_amenities["category_review"].astext == "pending")
        .order_by(Spot.created_at)
    )
    return list((await db.scalars(stmt)).all())


def _clear_review_flags(spot: Spot) -> None:
    extra = dict(spot.extra_amenities or {})
    extra.pop("category_review", None)
    extra.pop("category_review_reasons", None)
    spot.extra_amenities = extra


async def resolve_category_review(db: AsyncSession, *, spot_id: uuid.UUID, action: str, moderator: User) -> dict:
    """Moderatör kararı:
    - `keep_as_camping`: kayıt bir kamp alanıdır -> kategori CAMPING, tüm verisi yerinde kalır.
    - `move_to_service`: kayıt bir hizmet noktasıdır -> taşınır (migration'la aynı kurallar;
      kamp verisi silinmez, soft-delete edilen spot'ta durur).
    - `keep_as_is`: kayıt eski kategorisinde (salt okunur, Havuz/Otel gibi) kalır.
    """
    from app.services.content_service import record_change, snapshot_spot
    from app.services.spot_service import get_spot_by_id

    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None or (spot.extra_amenities or {}).get("category_review") != "pending":
        raise CategoryReviewError("Bu kayıt için bekleyen bir kategori incelemesi yok.")
    before = snapshot_spot(spot)

    if action == "keep_as_camping":
        spot.category = SpotCategory.CAMPING
        _clear_review_flags(spot)
        result = {"spot_id": spot.id, "service_point_id": None}
    elif action == "keep_as_is":
        _clear_review_flags(spot)
        result = {"spot_id": spot.id, "service_point_id": None}
    elif action == "move_to_service":
        point = await _move_spot_to_service_point(db, spot)
        result = {"spot_id": spot.id, "service_point_id": point.id}
    else:  # pragma: no cover - şema zaten sınırlar
        raise CategoryReviewError(f"Bilinmeyen işlem: {action}")

    spot.updated_at = func.now()
    record_change(db, spot, moderator.id, f"cat_review:{action}", before)
    await db.commit()
    return result


async def _move_spot_to_service_point(db: AsyncSession, spot: Spot) -> ServicePoint:
    category = spot.category.value
    if category not in MOVABLE_CATEGORIES:
        raise CategoryReviewError("Bu kategori hizmet noktasına taşınamaz.")
    extra = {k: v for k, v in (spot.extra_amenities or {}).items() if not k.startswith("category_review")}
    is_health = category in ("HOSPITAL", "HEALTH_CENTER")
    name = spot.title
    if is_health and name.endswith(" (OSM)"):
        name = None
    point = ServicePoint(
        id=spot.id,  # aynı id: eski bağlantılar /service-points/{id} ile çözülebilir
        category=ServicePointCategory(category),
        name=name,
        coordinates=spot.coordinates,
        source=spot.source,
        osm_id=extra.get("osm_id") if spot.source.value == "OVERPASS_OSM" else None,
        extra={**extra, "legacy_spot_id": str(spot.id)},
        created_by=spot.created_by,
    )
    db.add(point)
    await db.flush()
    if category in FOOD_CATEGORIES:
        reviews = (await db.scalars(select(Review).where(Review.spot_id == spot.id, Review.is_active.is_(True)))).all()
        for review in reviews:
            db.add(
                ServicePointReview(
                    service_point_id=point.id, user_id=review.user_id, rating=review.rating,
                    comment=review.comment, created_at=review.created_at, updated_at=review.updated_at,
                )
            )
        await db.flush()
        average, count = (
            await db.execute(
                select(func.avg(ServicePointReview.rating), func.count()).where(
                    ServicePointReview.service_point_id == point.id, ServicePointReview.is_active.is_(True)
                )
            )
        ).one()
        point.average_rating = round(float(average), 2) if average is not None else None
        point.review_count = int(count)
    spot.extra_amenities = {**extra, "moved_to_service_points": True}
    spot.deleted_at = datetime.now(UTC)
    return point
