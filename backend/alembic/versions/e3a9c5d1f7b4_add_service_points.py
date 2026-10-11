"""add service points (restoran / sağlık / WC / duş)

Kamp alanı olmayan çevresel hizmet noktaları `spots`tan ayrı `service_points`
tablosuna taşınır - bkz. app/models/service_point.py.

Veri taşıma (eşleme tablosu ve gerekçesi: app/services/category_migration.py;
taşımadan ÖNCE `python -m scripts.category_migration_report` ile raporlanabilir):

1. BELİRSİZ kayıtlar taşınmaz: FISH/MEAT_RESTAURANT / HOSPITAL / HEALTH_CENTER
   kategorisinde olup kamp alanına özgü veri taşıyan spot'lar (check-in, fotoğraf,
   7 boyutlu değerlendirme, geceleme kuralı, kamp olanağı, araç kısıtı, kayıtlı
   liste, sağlıkta değerlendirme ...) `spots`'ta olduğu gibi kalır ve
   `extra_amenities.category_review=pending` (+ nedenler) ile moderatör kuyruğuna düşer.
2. Kalan (temiz) kayıtlar AYNI id ile service_points'e kopyalanır; restoranların
   aktif değerlendirmeleri (yalnızca genel puan + yorum - temiz kayıtlarda 7 boyutlu
   ölçüt zaten yok) restoran değerlendirmesine kopyalanır.
3. Taşınan spot'lar SİLİNMEZ: soft-delete + `moved_to_service_points` işareti;
   `reviews` satırlarına dokunulmaz. Downgrade hepsini geri açar ve inceleme
   işaretlerini kaldırır; migration SONRASI eklenen hizmet noktaları (ör. WC/duş) kaybolur.

Revision ID: e3a9c5d1f7b4
Revises: 17f9e97a4d17
Create Date: 2026-10-09 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2  # noqa: F401
from sqlalchemy.dialects import postgresql

revision: str = "e3a9c5d1f7b4"
down_revision: Union[str, None] = "17f9e97a4d17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES = ("MEAT_RESTAURANT", "FISH_RESTAURANT", "OTHER_RESTAURANT", "HOSPITAL", "HEALTH_CENTER", "WC", "SHOWER")
MOVED_SPOT_CATEGORIES = "('FISH_RESTAURANT','MEAT_RESTAURANT','HOSPITAL','HEALTH_CENTER')"
FOOD = "('MEAT_RESTAURANT','FISH_RESTAURANT','OTHER_RESTAURANT')"
BASIC = "('WC','SHOWER')"

# app/services/category_migration.CAMP_SIGNALS'ın bu revizyondaki KOPYASI - migration
# uygulama koduna bağımlı olmasın diye burada sabitlenmiştir.
_CAMP_SIGNALS = [
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
REASONS_SQL = "array_remove(ARRAY[" + ", ".join(
    f"CASE WHEN {condition} THEN '{code}' END" for code, condition in _CAMP_SIGNALS
) + "]::text[], NULL)"


def upgrade() -> None:
    category_enum = postgresql.ENUM(*CATEGORIES, name="service_point_category")
    category_enum.create(op.get_bind(), checkfirst=True)
    source_enum = postgresql.ENUM(name="spot_source", create_type=False)

    op.create_table(
        "service_points",
        sa.Column("category", postgresql.ENUM(name="service_point_category", create_type=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "coordinates",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326, from_text="ST_GeomFromEWKT", name="geometry", nullable=False),
            nullable=False,
        ),
        sa.Column("source", source_enum, server_default="USER_ADDED", nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("average_rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fee_status", sa.String(length=10), server_default="unknown", nullable=False),
        sa.Column("availability_status", sa.String(length=12), server_default="unknown", nullable=False),
        sa.Column("status_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("fee_status IN ('free','paid','unknown')", name="ck_service_points_fee_status"),
        sa.CheckConstraint(
            "availability_status IN ('available','unavailable','unknown')", name="ck_service_points_availability_status"
        ),
        sa.CheckConstraint(
            f"category NOT IN {FOOD} OR (name IS NOT NULL AND length(btrim(name)) > 0)",
            name="ck_service_points_food_requires_name",
        ),
        sa.CheckConstraint(
            f"category IN {BASIC} OR (fee_status = 'unknown' AND availability_status = 'unknown' AND status_checked_at IS NULL)",
            name="ck_service_points_status_only_basic",
        ),
        sa.CheckConstraint(
            f"category IN {FOOD} OR (review_count = 0 AND average_rating IS NULL)",
            name="ck_service_points_rating_only_food",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # GiST index (idx_service_points_coordinates) GeoAlchemy tarafından create_table ile oluşturulur.
    op.create_index("ix_service_points_category", "service_points", ["category"])
    op.create_index("ix_service_points_deleted_at", "service_points", ["deleted_at"])
    op.create_index(
        "uq_service_points_osm_id",
        "service_points",
        [sa.text("(extra ->> 'osm_id')")],
        unique=True,
        postgresql_where=sa.text("source = 'OVERPASS_OSM'"),
    )

    op.create_table(
        "service_point_reviews",
        sa.Column("service_point_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_service_point_reviews_rating_range"),
        sa.ForeignKeyConstraint(["service_point_id"], ["service_points.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_point_reviews_service_point_id", "service_point_reviews", ["service_point_id"])
    op.create_index("ix_service_point_reviews_user_id", "service_point_reviews", ["user_id"])
    op.create_index(
        "uq_service_point_reviews_one_active",
        "service_point_reviews",
        ["service_point_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "service_point_status_updates",
        sa.Column("service_point_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("fee_status", sa.String(length=10), nullable=True),
        sa.Column("availability_status", sa.String(length=12), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "fee_status IS NULL OR fee_status IN ('free','paid','unknown')", name="ck_service_point_status_updates_fee"
        ),
        sa.CheckConstraint(
            "availability_status IS NULL OR availability_status IN ('available','unavailable','unknown')",
            name="ck_service_point_status_updates_availability",
        ),
        sa.CheckConstraint(
            "fee_status IS NOT NULL OR availability_status IS NOT NULL", name="ck_service_point_status_updates_not_empty"
        ),
        sa.ForeignKeyConstraint(["service_point_id"], ["service_points.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_point_status_updates_service_point_id", "service_point_status_updates", ["service_point_id"]
    )

    op.create_table(
        "service_point_reports",
        sa.Column("service_point_id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('wrong_location','closed','duplicate','wrong_info','other')", name="ck_service_point_reports_reason"
        ),
        sa.CheckConstraint("state IN ('pending','resolved','rejected')", name="ck_service_point_reports_state"),
        sa.ForeignKeyConstraint(["service_point_id"], ["service_points.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_point_reports_service_point_id", "service_point_reports", ["service_point_id"])
    op.create_index("ix_service_point_reports_state_created", "service_point_reports", ["state", "created_at"])
    op.create_index(
        "uq_service_point_reports_one_pending",
        "service_point_reports",
        ["service_point_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )

    # --- Veri taşıma ---
    # 1) Belirsiz kayıtları işaretle (taşıma YOK). Kurallar category_migration.CAMP_SIGNALS ile aynı.
    op.execute(
        f"""
        WITH classified AS (
            SELECT s.id, {REASONS_SQL} AS reasons
            FROM spots s
            WHERE s.deleted_at IS NULL AND s.category::text IN {MOVED_SPOT_CATEGORIES}
        )
        UPDATE spots
        SET extra_amenities = spots.extra_amenities || jsonb_build_object(
                'category_review', 'pending',
                'category_review_reasons', array_to_string(classified.reasons, ',')),
            updated_at = now()
        FROM classified
        WHERE spots.id = classified.id AND cardinality(classified.reasons) > 0
        """
    )
    # 2) Temiz kayıtları aynı id ile kopyala. OSM içe aktarımının adsız kayıtlara verdiği
    #    "Hastane (OSM)" gibi yedek başlıklar ad değildir; sağlıkta ad NULL kalır.
    op.execute(
        f"""
        INSERT INTO service_points (id, category, name, coordinates, source, extra, created_by, created_at, updated_at)
        SELECT s.id,
               s.category::text::service_point_category,
               CASE WHEN s.category IN ('HOSPITAL','HEALTH_CENTER') AND right(s.title, 6) = ' (OSM)' THEN NULL
                    ELSE s.title END,
               s.coordinates, s.source,
               s.extra_amenities || jsonb_build_object('legacy_spot_id', s.id::text),
               s.created_by, s.created_at, now()
        FROM spots s
        WHERE s.deleted_at IS NULL AND s.category::text IN {MOVED_SPOT_CATEGORIES}
          AND (s.extra_amenities ->> 'category_review') IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO service_point_reviews (id, service_point_id, user_id, rating, comment, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), sp.id, r.user_id, r.rating, r.comment, true, r.created_at, r.updated_at
        FROM reviews r
        JOIN service_points sp ON sp.id = r.spot_id
        WHERE r.is_active AND sp.category IN ('MEAT_RESTAURANT','FISH_RESTAURANT')
        """
    )
    op.execute(
        """
        UPDATE service_points sp
        SET review_count = agg.n, average_rating = round(agg.avg_rating::numeric, 2)
        FROM (
            SELECT service_point_id, count(*) AS n, avg(rating) AS avg_rating
            FROM service_point_reviews WHERE is_active GROUP BY service_point_id
        ) agg
        WHERE agg.service_point_id = sp.id
        """
    )
    # 3) Taşınanları gizle (silme yok).
    op.execute(
        """
        UPDATE spots
        SET deleted_at = now(), updated_at = now(),
            extra_amenities = extra_amenities || '{"moved_to_service_points": true}'::jsonb
        WHERE id IN (SELECT id FROM service_points)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE spots
        SET deleted_at = NULL, updated_at = now(),
            extra_amenities = extra_amenities - 'moved_to_service_points'
        WHERE (extra_amenities ->> 'moved_to_service_points') IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE spots
        SET extra_amenities = extra_amenities - 'category_review' - 'category_review_reasons'
        WHERE (extra_amenities ->> 'category_review') IS NOT NULL
        """
    )
    op.drop_table("service_point_reports")
    op.drop_table("service_point_status_updates")
    op.drop_table("service_point_reviews")
    op.drop_index("uq_service_points_osm_id", table_name="service_points")
    op.drop_index("ix_service_points_deleted_at", table_name="service_points")
    op.drop_index("ix_service_points_category", table_name="service_points")
    op.drop_table("service_points")
    postgresql.ENUM(name="service_point_category").drop(op.get_bind(), checkfirst=True)
