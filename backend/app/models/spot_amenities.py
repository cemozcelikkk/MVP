"""
`spot_amenities`: park4night tarzı servis/altyapı yetenekleri.

`spots` ile 1-1 ilişkilidir. Karavancının su/elektrik/atık ve GSM çekim
gücü gibi "burada kaç gün idare ederim?" sorularına cevap verir.
"""
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, false, true
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.spot import Spot


class SpotAmenities(Base):
    __tablename__ = "spot_amenities"

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("spots.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Dişli vana / hortum takılabilir temiz su kaynağı var mı?
    fresh_water_thread: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Kaset tuvalet döküm noktası / fosseptik bağlantısı
    black_water: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Gri su (bulaşık/duş) ızgara boşaltımı
    grey_water: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    electricity_220v: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Serbest formatlı operatör -> sinyal gücü haritası.
    # Örn: {"turkcell": "good", "vodafone": "poor", "turk_telekom": "none"}
    # Değer kümesi app.models.enums.GsmOperator / SignalStrength ile
    # Pydantic katmanında doğrulanır; DB tarafında JSONB esnekliği korunur.
    has_toilet: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    has_trash_bins: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    price_description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    camping_behavior_allowed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)

    rule_information_known: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)

    gsm_signals: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    spot: Mapped["Spot"] = relationship(back_populates="amenities")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SpotAmenities spot_id={self.spot_id}>"
