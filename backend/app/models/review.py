"""`reviews`: Kullanıcıların spot'lara bıraktığı puan/yorum kayıtları.

## Çok boyutlu saha değerlendirmesi - tasarım kararı

Yedi ölçüt (güvenlik/sessizlik/yol erişimi/zemin/temizlik/manzara/çekim)
SABİT ve BİLİNEN bir kümedir - kullanıcı tanımlı, açık uçlu bir liste
DEĞİL. Bu yüzden ayrı bir `review_dimension_ratings` (EAV tarzı, review
başına N satır) çocuk tablosu yerine, tıpkı `SpotPassability`/
`SpotAmenities`/`VehicleProfile`'ın sabit alan kümeleri için zaten
kullandığı desenle birebir tutarlı olarak, DÜZ NULLABLE SÜTUNLAR seçildi:
- Mevcut mimariyle tutarlı (bu codebase'de sabit alan kümesi = düz sütun).
- Var olan `reviews` satırlarıyla trivially geriye dönük uyumlu (ALTER
  TABLE ... ADD COLUMN nullable, mevcut satırlar otomatik NULL alır).
- "Bir kişinin puanladığı ölçüt" sorgusu (ortalama+adet) tek bir
  `SELECT avg(col), count(col), ... FROM reviews WHERE spot_id=X` - JOIN
  gerekmez, EAV tablosuna göre daha basit ve hızlı.
Her sütun kendi `CheckConstraint`'iyle 1-5 aralığına (veya NULL) sabitlenir
- mevcut `rating` sütununun `ck_reviews_rating_range`'iyle aynı desen.

## Araç anlık görüntüsü (snapshot) - gizlilik kararı

`vehicle_type_snapshot`/`vehicle_length_m_snapshot` sadece iki SKALER
değerdir - `vehicle_profile_id` FK'si KASITLI OLARAK YOK. Görev tanımı
"kullanıcıya özel profil ID'sini... herkese açma" diyor; profili hiç
saklamayarak (sadece görüntülemek için gereken iki değeri kopyalayarak)
bu sızıntı yapısal olarak İMKANSIZ hale getirildi - ileride bir
serileştirme hatası bile profil ID'sini asla açığa çıkaramaz. Ayrıca bu
iki değer, kullanıcı profilini SONRADAN değiştirse/silse bile review
oluşturma anındaki hâliyle SABİT kalır (bkz. `review_service.add_review`).
"""
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, true
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import VehicleType

if TYPE_CHECKING:
    from app.models.spot import Spot
    from app.models.user import User

# Sabit boyut ölçütü anahtarları - hem model (sütun adı `<key>_rating`),
# hem şema, hem servis katmanı bu tek listeye referansla döngü kurar ki
# yeni bir ölçüt eklemek/çıkarmak TEK yerden yönetilsin.
DIMENSION_KEYS: tuple[str, ...] = (
    "safety",
    "quietness",
    "road_access",
    "ground_suitability",
    "cleanliness",
    "view",
    "signal",
)


class Review(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reviews"

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Kullanıcı+nokta başına YALNIZCA BİR aktif değerlendirme (bkz. aşağıdaki kısmi
    # unique index). Eski, mükerrer yorumlar SİLİNMEZ: migration en yenisi hariç
    # hepsini `is_active=false` (geçmiş/superseded) yapar; ortalama, sayaç, liste ve
    # boyut özetleri sadece aktif satırları sayar.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    # --- Çok boyutlu saha değerlendirmesi (hepsi opsiyonel - bkz. modül docstring'i) ---
    safety_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quietness_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    road_access_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ground_suitability_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cleanliness_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    view_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signal_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- Araç anlık görüntüsü (bkz. modül docstring'i) ---
    vehicle_type_snapshot: Mapped[Optional[VehicleType]] = mapped_column(
        SAEnum(
            VehicleType,
            name="vehicle_type",  # `vehicle_profiles.vehicle_type` ile AYNI mevcut Postgres enum tipi.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,  # tip zaten `vehicle_profiles` migration'ında oluşturuldu.
        ),
        nullable=True,
    )
    vehicle_length_m_snapshot: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)

    spot: Mapped["Spot"] = relationship(back_populates="reviews")
    user: Mapped["User"] = relationship(back_populates="reviews")

    __table_args__ = (
        Index(
            "uq_reviews_one_active_per_user_spot",
            "spot_id",
            "user_id",
            unique=True,
            postgresql_where=is_active.is_(True),
        ),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
        CheckConstraint(
            "safety_rating IS NULL OR (safety_rating >= 1 AND safety_rating <= 5)",
            name="ck_reviews_safety_rating_range",
        ),
        CheckConstraint(
            "quietness_rating IS NULL OR (quietness_rating >= 1 AND quietness_rating <= 5)",
            name="ck_reviews_quietness_rating_range",
        ),
        CheckConstraint(
            "road_access_rating IS NULL OR (road_access_rating >= 1 AND road_access_rating <= 5)",
            name="ck_reviews_road_access_rating_range",
        ),
        CheckConstraint(
            "ground_suitability_rating IS NULL OR (ground_suitability_rating >= 1 AND ground_suitability_rating <= 5)",
            name="ck_reviews_ground_suitability_rating_range",
        ),
        CheckConstraint(
            "cleanliness_rating IS NULL OR (cleanliness_rating >= 1 AND cleanliness_rating <= 5)",
            name="ck_reviews_cleanliness_rating_range",
        ),
        CheckConstraint(
            "view_rating IS NULL OR (view_rating >= 1 AND view_rating <= 5)",
            name="ck_reviews_view_rating_range",
        ),
        CheckConstraint(
            "signal_rating IS NULL OR (signal_rating >= 1 AND signal_rating <= 5)",
            name="ck_reviews_signal_rating_range",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Review spot_id={self.spot_id} rating={self.rating}>"
