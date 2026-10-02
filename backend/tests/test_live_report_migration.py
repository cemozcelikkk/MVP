"""
`a7c3e1d94b52` migration'ının eski zabıta/doluluk kayıtlarını KORUDUĞUNU gerçek Postgres'te
doğrular. Test tek bir transaction içinde eski-tarz (`is_legacy=true`, `report_type` NULL)
satırlar ekler, migration'ın GERÇEK SQL sabitlerini çalıştırır, sonucu doğrular ve ROLLBACK
eder - dev veritabanında hiçbir iz kalmaz. (Boş DB'den `head` kurulumu ve gerçek veri
kopyası üzerinde upgrade/downgrade provası ayrıca elle yapılır; bkz. iş raporu.)
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
    / "a7c3e1d94b52_add_live_reports_and_moderation.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_a7c3e1d94b52", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


INSERT_LEGACY = text(
    "INSERT INTO dynamic_status (id, spot_id, reported_by, police_intervention, crowd_level, note, "
    "reported_at, valid_until, is_legacy) "
    "VALUES (:id, :s, :u, :p, :c, :n, now() - make_interval(hours => :ago), "
    "CASE WHEN :has_end THEN now() + interval '5 hours' END, true)"
)


async def test_legacy_police_and_crowd_rows_survive_the_migration_unchanged():
    mig = _load_migration()
    user_id, spot_id = uuid.uuid4(), uuid.uuid4()
    ids = {name: uuid.uuid4() for name in "ABCDEF"}
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
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
                    "VALUES (:s,'mig test','wild_camping',ST_SetSRID(ST_MakePoint(33,39),4326),false,0)"
                ),
                {"s": spot_id},
            )
            # Bildirimden 10 saat ÖNCE check-in yapmış kullanıcı -> "yerinde" sayılmalı.
            await conn.execute(
                text(
                    "INSERT INTO check_ins (id,spot_id,user_id,checked_in_at) "
                    "VALUES (gen_random_uuid(),:s,:u, now() - interval '20 hours')"
                ),
                {"s": spot_id, "u": user_id},
            )
            cases = [
                # ad, kullanıcı, police, crowd, not, kaç saat önce, valid_until var mı
                ("A", user_id, "warning", "medium", "uyarı notu", 10, True),
                ("B", None, "fine", "full", "ceza + dolu", 3, True),
                ("C", None, "none", "full", "sadece dolu", 3, True),
                ("D", None, "none", "medium", "salt bilgi", 3, True),
                ("E", None, "banned", None, None, 3, True),
                ("F", None, "warning", None, "süresiz eski kayıt", 3, False),
            ]
            for name, uid, police, crowd, note, ago, has_end in cases:
                await conn.execute(
                    INSERT_LEGACY,
                    {"id": ids[name], "s": spot_id, "u": uid, "p": police, "c": crowd, "n": note, "ago": ago, "has_end": has_end},
                )

            async def snapshot():
                return {
                    r.id: r
                    for r in (
                        await conn.execute(
                            text(
                                "SELECT id, police_intervention::text p, crowd_level::text c, note, reported_at, "
                                "valid_until, report_type::text rtype, moderation_state::text m, reporter_on_site, is_legacy "
                                "FROM dynamic_status WHERE spot_id=:s"
                            ),
                            {"s": spot_id},
                        )
                    ).all()
                }

            original = await snapshot()
            for _ in range(2):  # İKİ kez: idempotent olmalı (downgrade -> upgrade döngüsü)
                for sql in (
                    mig.BACKFILL_POLICE_TYPE_SQL,
                    mig.BACKFILL_FULL_COPY_SQL,
                    mig.BACKFILL_FULL_ONLY_SQL,
                    mig.BACKFILL_ON_SITE_SQL,
                ):
                    await conn.execute(text(sql))
            after = await snapshot()

            # 1) Hiçbir özgün satır silinmedi/değişmedi (yalnızca türetilmiş `report_type`/`on_site` eklendi).
            for name, rid in ids.items():
                before, now = original[rid], after[rid]
                assert (now.p, now.c, now.note, now.reported_at, now.valid_until) == (
                    before.p, before.c, before.note, before.reported_at, before.valid_until
                ), name
                assert now.m == "pending" and now.is_legacy is True

            # 2) Türetilen türler.
            assert after[ids["A"]].rtype == "official_warning" and after[ids["A"]].reporter_on_site is True
            assert after[ids["B"]].rtype == "fine_reported"
            assert after[ids["C"]].rtype == "full"
            assert after[ids["D"]].rtype is None  # salt bilgi satırı tür almaz ama silinmez
            assert after[ids["E"]].rtype == "overnight_restriction" and after[ids["E"]].reporter_on_site is False
            assert after[ids["F"]].rtype == "official_warning" and after[ids["F"]].valid_until is None  # süresiz aynen kaldı

            # 3) Hem ceza hem doluluk taşıyan B için TEK bir `full` kopyası (iki çalıştırmada da).
            extra = [r for rid, r in after.items() if rid not in ids.values()]
            assert len(extra) == 1
            assert (extra[0].rtype, extra[0].p, extra[0].c, extra[0].note) == ("full", "none", "full", "ceza + dolu")
            assert extra[0].is_legacy is True and len(after) == len(ids) + 1
        finally:
            await trans.rollback()
