"""
OpenStreetMap (Overpass) hizmet noktası CACHE'i - KaravanTR kaydı DEĞİL.

Restoran/kafe, WC ve duş için harici veri, kullanıcı haritada bir bölgeye
baktığında hücre (tile) bazında Overpass'tan çekilir ve burada TTL'li olarak
tutulur (bkz. app/services/osm_source.py). Kurallar:

- `osm_pois` yalnızca bir önbellektir: satırlar `service_points`'e KOPYALANMAZ.
  Bir kullanıcı bir OSM noktasına katkı yaptığında (puan, durum, bildirim) o
  nokta `service_points`'e `osm_id` ile bağlanarak "somutlaşır" (bkz.
  service_point_service.resolve_for_contribution); katkılar hep oraya yazılır.
- `virtual_id`, OSM kimliğinden türetilen KARARLI bir UUID'dir
  (uuid5(NAMESPACE_URL, "https://www.openstreetmap.org/<osm_id>")). Somutlaşan
  `service_points` satırı da AYNI id'yi alır - istemcinin elindeki id değişmez.
- Hücre yeniden çekildiğinde artık OSM'de olmayan noktalar silinir; hiç
  bakılmayan bölgeler hiç çekilmez (kontrolsüz toplu yazma yok).
"""
import uuid
from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, Computed, DateTime, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import ServicePointCategory

# Python tarafındaki `osm_virtual_id` ile birebir aynı (uuid-ossp eklentisi).
VIRTUAL_ID_SQL = "uuid_generate_v5(uuid_ns_url(), 'https://www.openstreetmap.org/' || osm_id)"


def osm_virtual_id(osm_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"https://www.openstreetmap.org/{osm_id}")


class OsmTile(Base):
    """Bir hücrenin çekim durumu.

    - `ok`: veri önbellekte (TTL dolunca istendiğinde arka planda tazelenir; eski veri gösterilmeye devam eder).
    - `pending`: istendi ama henüz çekilemedi (ör. sunucu geneli dakikalık sınır) - yenileyici alır.
    - `failed`: son deneme başarısız; `retry_after`a kadar beklenir. Bekleme `attempts` ile
      üstel büyür (1 dk, 2 dk, 4 dk ... en çok 30 dk); arka plan yenileyicisi (osm_refresher)
      son zamanlarda istenmiş (`last_requested_at`) hücreleri kendiliğinden yeniden dener.
    """

    __tablename__ = "osm_tiles"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)  # "0.05:<ix>:<iy>"
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    retry_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    poi_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (CheckConstraint("status IN ('ok','failed','pending')", name="ck_osm_tiles_status"),)


class OsmPoi(Base):
    __tablename__ = "osm_pois"

    osm_id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "node/123"
    virtual_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), Computed(VIRTUAL_ID_SQL, persisted=True), nullable=False, unique=True
    )
    category: Mapped[ServicePointCategory] = mapped_column(
        SAEnum(
            ServicePointCategory,
            name="service_point_category",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    coordinates: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )
    # Yalnızca gösterilen küçük etiket alt kümesi (telefon, saatler, ücret ...).
    tags: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    tile_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
