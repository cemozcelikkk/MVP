"""
`03ceb2a3cea8` migration'ının mükerrer-yorum veri geçişinin mevcut veriyi KORUDUĞUNU
gerçek Postgres'te doğrular. Postgres DDL'i transaction'lıdır: test tek bir transaction
içinde (1) yeni unique index'i düşürür, (2) eski-tarz mükerrer yorumlar ekler, (3)
migration'ın GERÇEK SQL sabitlerini çalıştırır, (4) sonucu doğrular ve (5) ROLLBACK
eder - dev veritabanında hiçbir iz (ve hiçbir index eksikliği) kalmaz.
"""
import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import text

from app.core.database import engine

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "03ceb2a3cea8_add_field_verifications_and_single_.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_03ceb2a3cea8", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


async def test_duplicate_review_migration_keeps_every_row_and_recomputes_only_active_summary():
    mig = _load_migration()
    user_id, spot_id = uuid.uuid4(), uuid.uuid4()
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(text("DROP INDEX uq_reviews_one_active_per_user_spot"))
            await conn.execute(
                text(
                    "INSERT INTO users (id,email,display_name,hashed_password,is_active,trust_score,role) "
                    "VALUES (:u,:e,'m','x',true,0,'user')"
                ),
                {"u": user_id, "e": f"mig-{user_id.hex[:8]}@karavantr-qa.dev"},
            )
            await conn.execute(
                text(
                    "INSERT INTO spots (id,title,category,coordinates,is_verified,review_count) "
                    "VALUES (:s,'mig test','wild_camping',ST_SetSRID(ST_MakePoint(33,39),4326),false,3)"
                ),
                {"s": spot_id},
            )
            # Aynı kullanıcı+nokta için 3 yorum (eski sistemin izin verdiği durum), farklı zamanlarda.
            for rating, comment, offset in ((1, "en eski", 3), (4, "orta", 2), (2, "EN YENI", 1)):
                await conn.execute(
                    text(
                        "INSERT INTO reviews (id,spot_id,user_id,rating,comment,created_at,updated_at) "
                        "VALUES (gen_random_uuid(),:s,:u,:r,:c, now() - make_interval(hours => :o), now())"
                    ),
                    {"s": spot_id, "u": user_id, "r": rating, "c": comment, "o": offset},
                )

            await conn.execute(text(mig.DEDUPE_REVIEWS_SQL))
            await conn.execute(text(mig.RECOMPUTE_ACTIVE_SUMMARY_SQL))

            rows = (
                await conn.execute(
                    text("SELECT comment,rating,is_active FROM reviews WHERE spot_id=:s ORDER BY created_at"),
                    {"s": spot_id},
                )
            ).all()
            # Hiçbir satır silinmedi; metinler/puanlar aynen duruyor.
            assert [(r.comment, r.rating) for r in rows] == [("en eski", 1), ("orta", 4), ("EN YENI", 2)]
            # Sadece EN YENİ aktif.
            assert [r.is_active for r in rows] == [False, False, True]
            summary = (
                await conn.execute(
                    text("SELECT average_rating,review_count FROM spots WHERE id=:s"), {"s": spot_id}
                )
            ).one()
            assert (summary.average_rating, summary.review_count) == (2.0, 1)  # sadece aktif yorumdan
        finally:
            await trans.rollback()  # index dahil her şey geri alınır
