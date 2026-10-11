"""
`basemap_pois`: harita altlığında DÜŞÜK zoom'da (11-13) gösterilen önemli OSM
noktaları - hastane, sağlık ocağı, eczane, akaryakıt, polis.

Bunlar KaravanTR kayıtları DEĞİLDİR (`spots` ile ilişkisi yok, kullanıcı
düzenleyemez/yorumlayamaz). Vektör tile'larda bu POI'ler yalnızca zoom 14+'te
bulunduğu için düşük zoom'a özel bu tablo `scripts/import_basemap_pois.py` ile
periyodik olarak (ör. haftalık) OSM Overpass'tan doldurulur; harita isteği
hiçbir zaman Overpass'ı beklemez.
"""
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, Computed, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.osm_cache import VIRTUAL_ID_SQL

# Sıra = önem: düşük zoom'da çakışma/limit durumunda öndekiler kazanır.
BASEMAP_POI_CATEGORIES = ("hospital", "fuel", "police", "clinic", "pharmacy")


class BasemapPoi(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "basemap_pois"

    # "node/123", "way/456" - içe aktarımın upsert anahtarı.
    osm_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    # Hastane/sağlık ocağı kayıtları hizmet noktası katmanında da (harici kaynak olarak)
    # gösterilir; istemcideki kararlı id (bkz. app/models/osm_cache.py::osm_virtual_id).
    virtual_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), Computed(VIRTUAL_ID_SQL, persisted=True), nullable=False, unique=True
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    coordinates: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )
    # Ham OSM etiketlerinin küçük, işe yarar alt kümesi (telefon, acil servis vb.).
    tags: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    # Son içe aktarımda OSM'de hâlâ görüldüğü an; tam bir çalışmadan sonra
    # bu damgası eski kalanlar OSM'den kalkmış sayılıp silinir.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('hospital','fuel','police','clinic','pharmacy')",
            name="ck_basemap_pois_category",
        ),
    )
