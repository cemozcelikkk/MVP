"""
`spot_passability`: iOverlander tarzı arazi/erişilebilirlik yetenekleri.

`spots` ile 1-1 ilişkilidir (spot_id hem PK hem FK). Bir karavancının
"bu yola aracımla girebilir miyim?" sorusunu yanıtlamak için gereken
tüm alanları taşır.
"""
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ClearanceRequired, RoadType

if TYPE_CHECKING:
    from app.models.spot import Spot


class SpotPassability(Base):
    __tablename__ = "spot_passability"

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("spots.id", ondelete="CASCADE"),
        primary_key=True,
    )

    road_type: Mapped[RoadType] = mapped_column(
        SAEnum(
            RoadType,
            name="road_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    # Metre cinsinden azami araç uzunluğu (çeki dahil). Numeric kullanılır
    # ki 8.50 gibi hassas ondalık değerlerde yuvarlama hatası olmasın.
    max_vehicle_length: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)

    # "Karavan Profili ve Otomatik Nokta Uyumluluğu" özelliği için eklendi
    # (bkz. app.services.compatibility_service). ÜÇÜ DE nullable: saha
    # verisi bilinmiyorsa NULL kalır, asla 0 veya tahmini bir değerle
    # doldurulmaz - uyumluluk motoru NULL'u "insufficient_data" olarak
    # yorumlar, "sınırsız" ya da "0" olarak DEĞİL.
    max_vehicle_width: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    max_vehicle_height: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    max_vehicle_weight_kg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    clearance_required: Mapped[ClearanceRequired] = mapped_column(
        SAEnum(
            ClearanceRequired,
            name="clearance_required",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ClearanceRequired.STANDARD,
        nullable=False,
    )

    # CaravanType enum değerlerinden oluşan serbest uzunlukta dizi.
    # Postgres ARRAY(String) tercih edildi; olası değerler
    # app.models.enums.CaravanType üzerinden Pydantic katmanında doğrulanır.
    caravan_types_allowed: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)),
        default=list,
        nullable=False,
    )

    steep_incline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    spot: Mapped["Spot"] = relationship(back_populates="passability")

    __table_args__ = (
        # Yeni eklenen 3 alan için gerçek dışı/negatif değerleri DB
        # seviyesinde de reddet (Pydantic aynı üst sınırları istek
        # katmanında zaten uyguluyor - bkz. app.schemas.spot_passability).
        # `max_vehicle_length`'e kasıtlı olarak DOKUNULMADI (mevcut alan,
        # görev tanımı "mevcut alanları bozma" diyor).
        CheckConstraint(
            "max_vehicle_width IS NULL OR (max_vehicle_width > 0 AND max_vehicle_width <= 6)",
            name="ck_spot_passability_max_vehicle_width_range",
        ),
        CheckConstraint(
            "max_vehicle_height IS NULL OR (max_vehicle_height > 0 AND max_vehicle_height <= 5)",
            name="ck_spot_passability_max_vehicle_height_range",
        ),
        CheckConstraint(
            "max_vehicle_weight_kg IS NULL OR (max_vehicle_weight_kg > 0 AND max_vehicle_weight_kg <= 10000)",
            name="ck_spot_passability_max_vehicle_weight_kg_range",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SpotPassability spot_id={self.spot_id} road_type={self.road_type}>"
