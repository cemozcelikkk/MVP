"""unique osm_id for imported spots

Revision ID: c8e4a1f7b2d6
Revises: b5d2c7f1a9e3
Create Date: 2026-10-07 13:00:00.000000

OSM içe aktarımı (scripts/fetch_osm_places.py) tekrar çalıştırıldığında aynı
OSM nesnesinin ikinci kez eklenmemesi için kısmi, ifade tabanlı tekil index.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e4a1f7b2d6'
down_revision: Union[str, None] = 'b5d2c7f1a9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_spots_osm_id',
        'spots',
        [sa.text("(extra_amenities ->> 'osm_id')")],
        unique=True,
        postgresql_where=sa.text("source = 'OVERPASS_OSM'"),
    )


def downgrade() -> None:
    op.drop_index('uq_spots_osm_id', table_name='spots')
