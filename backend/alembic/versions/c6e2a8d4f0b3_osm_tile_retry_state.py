"""osm tiles: retry state (attempts, last_requested_at, pending)

Overpass'ın geçici hatalarında hücreler üstel bekleme ile ve arka plan yenileyicisi
tarafından kendiliğinden yeniden denenir - bkz. app/services/osm_refresher.py.
Yalnızca EKLEME yapar; mevcut önbellek ve veriler korunur.

Revision ID: c6e2a8d4f0b3
Revises: a4c8e2f6b1d9
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c6e2a8d4f0b3"
down_revision: Union[str, None] = "a4c8e2f6b1d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("osm_tiles", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("osm_tiles", sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_osm_tiles_status", "osm_tiles", type_="check")
    op.create_check_constraint("ck_osm_tiles_status", "osm_tiles", "status IN ('ok','failed','pending')")
    # Mevcut başarısız hücreler hemen yeniden denenebilsin (eski sabit 15 dk bekleme yerine).
    op.execute("UPDATE osm_tiles SET attempts = 1, retry_after = now(), last_requested_at = now() WHERE status = 'failed'")


def downgrade() -> None:
    op.execute("UPDATE osm_tiles SET status = 'failed' WHERE status = 'pending'")
    op.drop_constraint("ck_osm_tiles_status", "osm_tiles", type_="check")
    op.create_check_constraint("ck_osm_tiles_status", "osm_tiles", "status IN ('ok','failed')")
    op.drop_column("osm_tiles", "last_requested_at")
    op.drop_column("osm_tiles", "attempts")
