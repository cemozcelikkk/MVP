"""park4night categories, spot source and extra_amenities

Revision ID: b5d2c7f1a9e3
Revises: 00fae9a72c8b
Create Date: 2026-10-07 12:00:00.000000

- `spot_category` enum'u yeni çok-tipli harita kategorileriyle DEĞİŞTİRİLİR.
  Eski 5 kamp kategorisinin (wild_camping, campsite, sanistation_only,
  day_parking, farm_stay) hepsi CAMPING'e taşınır - bu ayrım kalıcı olarak
  kaybolur, migration öncesi yedek alınmalıdır.
- `spots.source` (spot_source enum, varsayılan USER_ADDED) eklenir.
- `spots.extra_amenities` (JSONB, varsayılan {}) eklenir.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b5d2c7f1a9e3'
down_revision: Union[str, None] = '00fae9a72c8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_CATEGORIES = (
    'CAMPING', 'FISH_RESTAURANT', 'MEAT_RESTAURANT', 'HOTEL_POOL', 'HOSPITAL', 'HEALTH_CENTER',
)
OLD_CATEGORIES = ('wild_camping', 'campsite', 'sanistation_only', 'day_parking', 'farm_stay')
SOURCES = ('USER_ADDED', 'OVERPASS_OSM', 'GOOGLE_PLACES')


def _replace_category_enum(values: tuple[str, ...], using: str) -> None:
    op.execute("ALTER TYPE spot_category RENAME TO spot_category_old")
    postgresql.ENUM(*values, name='spot_category').create(op.get_bind())
    op.execute(f"ALTER TABLE spots ALTER COLUMN category TYPE spot_category USING ({using})")
    op.execute("DROP TYPE spot_category_old")


def upgrade() -> None:
    # Eski kamp kategorilerinin tümü CAMPING olur (bilinçli, kayıplı eşleme).
    _replace_category_enum(NEW_CATEGORIES, "'CAMPING'::spot_category")

    spot_source = postgresql.ENUM(*SOURCES, name='spot_source')
    spot_source.create(op.get_bind())
    op.add_column(
        'spots',
        sa.Column('source', spot_source, server_default='USER_ADDED', nullable=False),
    )
    op.create_index(op.f('ix_spots_source'), 'spots', ['source'], unique=False)
    op.add_column(
        'spots',
        sa.Column(
            'extra_amenities',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('spots', 'extra_amenities')
    op.drop_index(op.f('ix_spots_source'), table_name='spots')
    op.drop_column('spots', 'source')
    postgresql.ENUM(name='spot_source').drop(op.get_bind())

    # Kamp dışı kategorilerin eski şemada karşılığı yok; sessizce yanlış veriye
    # çevirmek yerine geri dönüşü durdur.
    non_camping = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM spots WHERE category <> 'CAMPING'")
    )
    if non_camping:
        raise RuntimeError(
            f"{non_camping} spot kamp dışı kategoride; eski spot_category enum'unda karşılığı yok. "
            "Downgrade öncesi bu kayıtları silin veya taşıyın."
        )
    # Orijinal alt kategori (wild_camping/campsite/...) upgrade'de kaybolduğu için
    # hepsi 'campsite' olarak geri döner.
    _replace_category_enum(OLD_CATEGORIES, "'campsite'::spot_category")
