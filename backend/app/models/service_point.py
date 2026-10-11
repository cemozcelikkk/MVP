"""
`service_points`: kamp alanı OLMAYAN çevresel hizmet/ihtiyaç noktaları -
restoran, hastane, sağlık ocağı, WC ve duş.

`spots` (kamp/karavan konaklama noktaları) ile bilinçli olarak ayrı tablodadır:
bu kayıtlar araç uyumluluğu, yol/zemin bilgisi, 7 boyutlu değerlendirme, check-in
veya canlı saha bildirimi taşımaz. Gruba göre farklı, hafif bir veri taşırlar:

- Yeme & İçme: ad zorunlu; 1-5 yıldız + metin yorum (`service_point_reviews`,
  kullanıcı başına tek aktif değerlendirme - `reviews` ile aynı kural).
- Sağlık: ad opsiyonel; puan/yorum YOK.
- Temel ihtiyaçlar (WC/duş): ücret ve kullanılabilirlik durumu + son doğrulama
  zamanı. Her güncelleme `service_point_status_updates`'e tarihçe olarak yazılır;
  güncel değer satırda denormalize tutulur (harita sorgusu JOIN atmasın diye).

Tüm türler için kullanıcılar hatalı konum / kapanmış / mükerrer kayıt
bildirebilir (`service_point_reports`, moderatör kuyruğu).
"""
import uuid
from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
    true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ServicePointCategory, SpotSource
from app.utils.geo import wkb_to_lonlat

FEE_STATUSES = ("free", "paid", "unknown")
AVAILABILITY_STATUSES = ("available", "unavailable", "unknown")
REPORT_REASONS = ("wrong_location", "closed", "duplicate", "wrong_info", "other")
REPORT_STATES = ("pending", "resolved", "rejected")

_FOOD_SQL = "('MEAT_RESTAURANT','FISH_RESTAURANT','OTHER_RESTAURANT')"
_BASIC_SQL = "('WC','SHOWER')"


def _sql_in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


class ServicePoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_points"

    category: Mapped[ServicePointCategory] = mapped_column(
        SAEnum(
            ServicePointCategory,
            name="service_point_category",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    # Restoranlarda zorunlu (şema + CHECK), sağlık/WC/duşta opsiyonel.
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    coordinates: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )
    source: Mapped[SpotSource] = mapped_column(
        SAEnum(
            SpotSource,
            name="spot_source",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,  # tip `spots` ile paylaşılıyor
        ),
        default=SpotSource.USER_ADDED,
        server_default=SpotSource.USER_ADDED.value,
        nullable=False,
    )
    # Bu kayıt bir OpenStreetMap nesnesine karşılık geliyorsa onun kimliği ("node/123").
    # OSM kaynaklı bir nokta, bir kullanıcı ona katkı yaptığında (puan/durum/bildirim)
    # buraya bu kimlikle "somutlaşır"; kullanıcı eklediği bir nokta da eşleşen OSM
    # nesnesine bağlanabilir. Harita birleştirmesinde aynı OSM nesnesinin ikinci
    # marker'ı bu sütunla elenir - soft-delete edilmiş satır da (ör. "kapanmış")
    # OSM'den gelen kopyayı bastırmaya devam eder.
    osm_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # OSM etiketleri (phone, opening_hours ...) ve taşınan eski spot'un kimliği
    # (`legacy_spot_id`) gibi serbest ek bilgiler.
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Soft-delete (kapanmış/mükerrer kayıtlar moderatörce kaldırılır). NULL = aktif.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Yalnızca Yeme & İçme - denormalize puan özeti (service_point_reviews'tan).
    average_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Yalnızca WC/duş - güncel pratik durum ve son doğrulama.
    fee_status: Mapped[str] = mapped_column(String(10), default="unknown", server_default="unknown", nullable=False)
    availability_status: Mapped[str] = mapped_column(
        String(12), default="unknown", server_default="unknown", nullable=False
    )
    status_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Doğrulama - tüm türler. `is_verified`: moderatör onayı. Topluluk teyidi ("hâlâ burada /
    # hizmet veriyor"): farklı kullanıcı sayısı + en son teyit zamanı (denormalize, bkz.
    # service_point_confirmations). Sağlıkta puan/yorum yerine güvenin tek kaynağı budur.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    confirmation_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"fee_status IN {_sql_in(FEE_STATUSES)}", name="ck_service_points_fee_status"),
        CheckConstraint(
            f"availability_status IN {_sql_in(AVAILABILITY_STATUSES)}",
            name="ck_service_points_availability_status",
        ),
        CheckConstraint(
            f"category NOT IN {_FOOD_SQL} OR (name IS NOT NULL AND length(btrim(name)) > 0)",
            name="ck_service_points_food_requires_name",
        ),
        CheckConstraint(
            f"category IN {_BASIC_SQL} OR (fee_status = 'unknown' AND availability_status = 'unknown' AND status_checked_at IS NULL)",
            name="ck_service_points_status_only_basic",
        ),
        CheckConstraint(
            f"category IN {_FOOD_SQL} OR (review_count = 0 AND average_rating IS NULL)",
            name="ck_service_points_rating_only_food",
        ),
        Index("uq_service_points_osm_id", "osm_id", unique=True, postgresql_where=text("osm_id IS NOT NULL")),
    )

    @property
    def latitude(self) -> float:
        return float(wkb_to_lonlat(self.coordinates)[1])

    @property
    def longitude(self) -> float:
        return float(wkb_to_lonlat(self.coordinates)[0])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ServicePoint id={self.id} category={self.category} name={self.name!r}>"


class ServicePointReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Yeme & İçme değerlendirmesi: 1-5 yıldız + opsiyonel metin. Kamp alanlarının
    7 boyutlu `reviews` tablosundan tamamen bağımsızdır."""

    __tablename__ = "service_point_reviews"

    service_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # `reviews.is_active` ile aynı anlam: kullanıcı silince/moderatör kaldırınca
    # satır durur ama ortalamaya ve listeye girmez.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)

    __table_args__ = (
        Index(
            "uq_service_point_reviews_one_active",
            "service_point_id",
            "user_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_service_point_reviews_rating_range"),
    )


class ServicePointStatusUpdate(UUIDPrimaryKeyMixin, Base):
    """WC/duş pratik durum güncellemesi (tarihçe). `None` alan = o soruya yanıt verilmedi."""

    __tablename__ = "service_point_status_updates"

    service_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    fee_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    availability_status: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"fee_status IS NULL OR fee_status IN {_sql_in(FEE_STATUSES)}",
            name="ck_service_point_status_updates_fee",
        ),
        CheckConstraint(
            f"availability_status IS NULL OR availability_status IN {_sql_in(AVAILABILITY_STATUSES)}",
            name="ck_service_point_status_updates_availability",
        ),
        CheckConstraint(
            "fee_status IS NOT NULL OR availability_status IS NOT NULL",
            name="ck_service_point_status_updates_not_empty",
        ),
    )


class ServicePointReport(UUIDPrimaryKeyMixin, Base):
    """Hatalı konum / kapanmış / mükerrer kayıt bildirimi - moderatör kuyruğu."""

    __tablename__ = "service_point_reports"

    service_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending", nullable=False)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"reason IN {_sql_in(REPORT_REASONS)}", name="ck_service_point_reports_reason"),
        CheckConstraint(f"state IN {_sql_in(REPORT_STATES)}", name="ck_service_point_reports_state"),
        # Aynı kullanıcı aynı noktayı, bekleyen bildirimi varken tekrar bildiremez.
        Index(
            "uq_service_point_reports_one_pending",
            "service_point_id",
            "reporter_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ),
        Index("ix_service_point_reports_state_created", "state", "created_at"),
    )


class ServicePointConfirmation(UUIDPrimaryKeyMixin, Base):
    """"Bu yer hâlâ burada / açık" teyidi. Kullanıcı başına nokta başına TEK satır; tekrar
    teyit (bekleme süresinden sonra) aynı satırın zamanını günceller."""

    __tablename__ = "service_point_confirmations"

    service_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_points.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("uq_service_point_confirmations_user", "service_point_id", "user_id", unique=True),
    )
