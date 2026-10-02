"""
`vehicle_profiles`: Kullanıcının kaydettiği karavan/kamp aracı teknik
profilleri ("Karavan Profili ve Otomatik Nokta Uyumluluğu" özelliği).

Bir kullanıcının birden fazla profili olabilir (örn. "Ducato" ve "Yedek
Çekme Karavan") ama bunlardan en fazla BİRİ aktif olabilir - uyumluluk
motoru (bkz. gelecekteki `compatibility_service`) her zaman kullanıcının
TEK aktif profilini bir spot'un `SpotPassability`siyle karşılaştırır.

Bu kısıt iki katmanda uygulanır:
1. Kısmi (partial) unique index - `is_active IS true` olan satırlarda
   `user_id` üzerinde - veritabanı seviyesinde son söz (bkz. migration).
2. `vehicle_profile_service` - bir profili aktif yaparken aynı kullanıcının
   diğer aktif profilini tek transaction içinde deaktive eder; eşzamanlı
   isteklerde yarış durumunu önlemek için `pg_advisory_xact_lock` kullanır
   (bkz. `_lock_user_vehicle_profiles`).

Sadece web frontend'e özel bir yapı DEĞİLDİR: model ve servis katmanı,
gelecekteki React Native/Expo istemcisinin de aynı `/vehicle-profiles`
API'sini kullanabileceği şekilde tasarlanmıştır (frontend'e gömülü
hesaplama yok).
"""
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Drivetrain, VehicleType

if TYPE_CHECKING:
    from app.models.user import User


class VehicleProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vehicle_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Kullanıcının verdiği serbest metin etiket, ör. "Ducato".
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    vehicle_type: Mapped[VehicleType] = mapped_column(
        SAEnum(
            VehicleType,
            name="vehicle_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    # Numeric(4,2): spot_passability.max_vehicle_length ile aynı hassasiyet
    # (8.50 gibi santimetre çözünürlüklü ölçüler, yuvarlama hatası yok).
    length_m: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    width_m: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    height_m: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    weight_kg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    drivetrain: Mapped[Drivetrain] = mapped_column(
        SAEnum(
            Drivetrain,
            name="vehicle_drivetrain",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=Drivetrain.TWO_WHEEL_DRIVE,
        nullable=False,
    )

    has_grey_water_tank: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_black_water_cassette: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_solar_power: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    travels_with_pet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Kullanıcı başına en fazla bir aktif profil - bkz. modül docstring'i.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="vehicle_profiles")

    __table_args__ = (
        # Gerçek dışı/negatif ölçü ve ağırlıkları veritabanı seviyesinde de
        # reddet - Pydantic (app.schemas.vehicle_profile) aynı üst sınırları
        # istek katmanında zaten uyguluyor, bu ikinci bir savunma hattı.
        CheckConstraint("length_m > 0 AND length_m <= 30", name="ck_vehicle_profiles_length_m_range"),
        CheckConstraint(
            "width_m IS NULL OR (width_m > 0 AND width_m <= 6)",
            name="ck_vehicle_profiles_width_m_range",
        ),
        CheckConstraint(
            "height_m IS NULL OR (height_m > 0 AND height_m <= 5)",
            name="ck_vehicle_profiles_height_m_range",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR (weight_kg > 0 AND weight_kg <= 10000)",
            name="ck_vehicle_profiles_weight_kg_range",
        ),
        # Kullanıcı başına en fazla bir `is_active = true` satır - bkz.
        # `saved_lists.uq_saved_lists_one_default_favorites_per_user` ile
        # aynı desen (kısmi/partial unique index).
        Index(
            "uq_vehicle_profiles_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=is_active.is_(True),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VehicleProfile id={self.id} user_id={self.user_id} name={self.name!r}>"
