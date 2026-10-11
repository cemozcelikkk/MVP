"""osm cache (osm_tiles / osm_pois) + service_points.osm_id + basemap_pois.virtual_id

Harici (OpenStreetMap/Overpass) hizmet noktaları için TTL'li önbellek ve
KaravanTR kayıtlarını OSM nesnelerine bağlayan `service_points.osm_id` -
bkz. app/models/osm_cache.py ve app/services/osm_source.py.

Revision ID: f1b7d3a9c2e5
Revises: e3a9c5d1f7b4
Create Date: 2026-10-09 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2  # noqa: F401
from sqlalchemy.dialects import postgresql

revision: str = "f1b7d3a9c2e5"
down_revision: Union[str, None] = "e3a9c5d1f7b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VIRTUAL_ID_SQL = "uuid_generate_v5(uuid_ns_url(), 'https://www.openstreetmap.org/' || osm_id)"


def upgrade() -> None:
    # uuid-ossp PG13+ "trusted" eklentidir; veritabanı sahibi oluşturabilir.
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.add_column(
        "basemap_pois",
        sa.Column("virtual_id", sa.UUID(), sa.Computed(VIRTUAL_ID_SQL, persisted=True), nullable=False),
    )
    op.create_unique_constraint("basemap_pois_virtual_id_key", "basemap_pois", ["virtual_id"])

    op.add_column("service_points", sa.Column("osm_id", sa.String(length=40), nullable=True))
    op.execute(
        "UPDATE service_points SET osm_id = extra ->> 'osm_id' "
        "WHERE source = 'OVERPASS_OSM' AND (extra ->> 'osm_id') IS NOT NULL"
    )
    op.drop_index("uq_service_points_osm_id", table_name="service_points")
    op.create_index(
        "uq_service_points_osm_id", "service_points", ["osm_id"], unique=True,
        postgresql_where=sa.text("osm_id IS NOT NULL"),
    )

    op.create_table(
        "osm_tiles",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("poi_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("status IN ('ok','failed')", name="ck_osm_tiles_status"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "osm_pois",
        sa.Column("osm_id", sa.String(length=40), nullable=False),
        sa.Column("virtual_id", sa.UUID(), sa.Computed(VIRTUAL_ID_SQL, persisted=True), nullable=False),
        sa.Column("category", postgresql.ENUM(name="service_point_category", create_type=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "coordinates",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326, from_text="ST_GeomFromEWKT", name="geometry", nullable=False),
            nullable=False,
        ),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("tile_key", sa.String(length=40), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("osm_id"),
        sa.UniqueConstraint("virtual_id"),
    )
    op.create_index("ix_osm_pois_category", "osm_pois", ["category"])
    op.create_index("ix_osm_pois_tile_key", "osm_pois", ["tile_key"])


def downgrade() -> None:
    op.drop_index("ix_osm_pois_tile_key", table_name="osm_pois")
    op.drop_index("ix_osm_pois_category", table_name="osm_pois")
    op.drop_table("osm_pois")
    op.drop_table("osm_tiles")
    op.drop_index("uq_service_points_osm_id", table_name="service_points")
    op.create_index(
        "uq_service_points_osm_id", "service_points", [sa.text("(extra ->> 'osm_id')")], unique=True,
        postgresql_where=sa.text("source = 'OVERPASS_OSM'"),
    )
    op.drop_column("service_points", "osm_id")
    op.drop_constraint("basemap_pois_virtual_id_key", "basemap_pois", type_="unique")
    op.drop_column("basemap_pois", "virtual_id")
