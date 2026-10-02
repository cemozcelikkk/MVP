"""add_live_reports_and_moderation

Süreli canlı saha bildirimleri: `dynamic_status` genişletilir (tür, moderasyon durumu, süre,
yerinde-bulunma, eski kayıt işareti), aynı kullanıcı+nokta+tür için aktif pencerelerin
çakışması DB seviyesinde engellenir ve moderasyon/geri çekme geçmişi için
`live_report_events` eklenir.

Revision ID: a7c3e1d94b52
Revises: 03ceb2a3cea8
Create Date: 2026-09-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c3e1d94b52'
down_revision: Union[str, None] = '03ceb2a3cea8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Veri geçişi SQL'leri (modül seviyesinde) ---------------------------------------------------
# `tests/test_live_report_migration.py` bunları gerçek DB'de (transaction içinde, sonunda
# ROLLBACK ile) doğrular. HİÇBİR satır silinmez/üzerine yazılmaz; yalnızca türetilmiş
# `report_type` ve (gerekirse) ek bir `full` satırı eklenir.
#
# Sıra ÖNEMLİ: (1) zabıta türü -> (2) hem zabıta hem `full` kalabalık taşıyan satırın `full` kopyası
# -> (3) yalnızca `full` kalabalık olanlar -> (4) bildirim anında yerinde bulunma.

BACKFILL_POLICE_TYPE_SQL = """
UPDATE dynamic_status SET report_type = CASE police_intervention
    WHEN 'warning' THEN 'official_warning'::live_report_type
    WHEN 'fine'    THEN 'fine_reported'::live_report_type
    WHEN 'banned'  THEN 'overnight_restriction'::live_report_type
END
WHERE is_legacy AND report_type IS NULL AND police_intervention IN ('warning', 'fine', 'banned')
"""

# Tek satır iki anlam taşıyorsa (ör. ceza + tamamen dolu) ikinci anlam için ayrı satır eklenir;
# özgün satır olduğu gibi kalır (eski API'nin gördüğü şey değişmez).
BACKFILL_FULL_COPY_SQL = """
INSERT INTO dynamic_status (
    id, spot_id, reported_by, police_intervention, note, crowd_level, reported_at, valid_until,
    report_type, moderation_state, duration_hours, reporter_on_site, is_legacy
)
SELECT gen_random_uuid(), d.spot_id, d.reported_by, 'none', d.note, 'full', d.reported_at, d.valid_until,
       'full'::live_report_type, d.moderation_state, NULL, d.reporter_on_site, true
FROM dynamic_status d
WHERE d.is_legacy AND d.crowd_level = 'full'
  AND d.report_type IN ('official_warning', 'fine_reported', 'overnight_restriction')
  -- İdempotent: downgrade -> upgrade döngüsünde (kopya satır downgrade'de kalır) tekrar kopyalama.
  AND NOT EXISTS (
      SELECT 1 FROM dynamic_status x
      WHERE x.id <> d.id AND x.spot_id = d.spot_id
        AND x.reported_by IS NOT DISTINCT FROM d.reported_by
        AND x.reported_at = d.reported_at AND x.note IS NOT DISTINCT FROM d.note
        AND x.police_intervention = 'none' AND x.crowd_level = 'full'
  )
"""

BACKFILL_FULL_ONLY_SQL = """
UPDATE dynamic_status SET report_type = 'full'::live_report_type
WHERE is_legacy AND report_type IS NULL AND crowd_level = 'full'
"""

# Bildirimden önceki 72 saatte aynı noktada check-in'i olan bildiren "yerinde" sayılır.
BACKFILL_ON_SITE_SQL = """
UPDATE dynamic_status d SET reporter_on_site = true
WHERE d.is_legacy AND d.reported_by IS NOT NULL AND EXISTS (
    SELECT 1 FROM check_ins c
    WHERE c.spot_id = d.spot_id AND c.user_id = d.reported_by
      AND c.checked_in_at BETWEEN d.reported_at - interval '72 hours' AND d.reported_at
)
"""

LIVE_REPORT_TYPES = (
    'overnight_restriction', 'official_warning', 'fine_reported', 'road_closed', 'access_difficult',
    'full', 'fresh_water_unavailable', 'electricity_unavailable', 'grey_water_unavailable',
    'black_water_unavailable', 'mud_risk', 'fire_or_flood_access_issue',
)
MODERATION_STATES = ('pending', 'confirmed', 'rejected', 'withdrawn')


def upgrade() -> None:
    # tstzrange + uuid/enum eşitliği için (exclusion constraint). Postgres'te "trusted" eklentidir.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    bind = op.get_bind()
    report_type_enum = postgresql.ENUM(*LIVE_REPORT_TYPES, name='live_report_type', create_type=False)
    state_enum = postgresql.ENUM(*MODERATION_STATES, name='report_moderation_state', create_type=False)
    report_type_enum.create(bind, checkfirst=True)
    state_enum.create(bind, checkfirst=True)

    op.add_column('dynamic_status', sa.Column('report_type', report_type_enum, nullable=True))
    op.add_column('dynamic_status', sa.Column('moderation_state', state_enum, server_default='pending', nullable=False))
    op.add_column('dynamic_status', sa.Column('duration_hours', sa.SmallInteger(), nullable=True))
    op.add_column('dynamic_status', sa.Column('reporter_on_site', sa.Boolean(), server_default=sa.false(), nullable=False))
    # Mevcut TÜM satırlar eski kayıt sayılır (geçici varsayılan true), sonra varsayılan false'a çekilir.
    op.add_column('dynamic_status', sa.Column('is_legacy', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.alter_column('dynamic_status', 'is_legacy', server_default=sa.false())

    op.execute(BACKFILL_POLICE_TYPE_SQL)
    op.execute(BACKFILL_FULL_COPY_SQL)
    op.execute(BACKFILL_FULL_ONLY_SQL)
    op.execute(BACKFILL_ON_SITE_SQL)

    # Eski satırlar (is_legacy) kapsam dışıdır; constraint yalnızca yeni bildirimleri korur.
    # Aralık ifadesi GREATEST ile güvenli: geçmişte biten (valid_until < reported_at) bir satır
    # doğrudan eklense bile `tstzrange` hata vermez (boş aralık = hiçbir şeyle çakışmaz);
    # NULL valid_until sınırsız aralık sayılır. (`+ interval` index ifadesinde STABLE olduğu için kullanılamaz.)
    op.execute(
        """
        ALTER TABLE dynamic_status ADD CONSTRAINT ex_dynamic_status_one_active_report_per_user_type
        EXCLUDE USING gist (
            spot_id WITH =, reported_by WITH =, report_type WITH =,
            (CASE WHEN valid_until IS NULL THEN tstzrange(reported_at, NULL) ELSE tstzrange(reported_at, GREATEST(valid_until, reported_at)) END) WITH &&
        ) WHERE (NOT is_legacy AND moderation_state IN ('pending', 'confirmed'))
        """
    )
    op.create_index('ix_dynamic_status_moderation', 'dynamic_status', ['moderation_state', 'valid_until'], unique=False)

    op.create_table('live_report_events',
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('actor_role', postgresql.ENUM(name='user_role', create_type=False), nullable=False),
        sa.Column('from_state', postgresql.ENUM(name='report_moderation_state', create_type=False), nullable=False),
        sa.Column('to_state', postgresql.ENUM(name='report_moderation_state', create_type=False), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['report_id'], ['dynamic_status.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_live_report_events_report_id'), 'live_report_events', ['report_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_live_report_events_report_id'), table_name='live_report_events')
    op.drop_table('live_report_events')
    op.drop_index('ix_dynamic_status_moderation', table_name='dynamic_status')
    op.execute("ALTER TABLE dynamic_status DROP CONSTRAINT ex_dynamic_status_one_active_report_per_user_type")
    # Satırlar SİLİNMEZ: yalnızca yeni sütunlar kalkar. Upgrade'in eklediği türetilmiş `full` kopya
    # satırları ve yeni türlü bildirimler (eski sütunlarda en yakın karşılıkla) tabloda kalır;
    # eski kod bunları sıradan police/crowd kayıtları olarak okur.
    op.drop_column('dynamic_status', 'is_legacy')
    op.drop_column('dynamic_status', 'reporter_on_site')
    op.drop_column('dynamic_status', 'duration_hours')
    op.drop_column('dynamic_status', 'moderation_state')
    op.drop_column('dynamic_status', 'report_type')
    # Postgres ENUM tipleri drop_column ile otomatik silinmez (bkz. add_vehicle_profiles).
    postgresql.ENUM(name='report_moderation_state').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='live_report_type').drop(op.get_bind(), checkfirst=True)
    # btree_gist eklentisi bilerek bırakılır (başka nesneler kullanıyor olabilir).
