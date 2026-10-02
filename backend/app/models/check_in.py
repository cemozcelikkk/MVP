"""
`check_ins`: Bir kullanıcının bir spot'ta fiilen konakladığını bildirmesi.

"Buradayım / burada kaldım" sinyali; hem güven puanlaması (gerçekten
ziyaret edilmiş mi) hem de crowd_level tahmini için veri kaynağıdır.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.spot import Spot
    from app.models.user import User


class CheckIn(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "check_ins"

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    planned_nights: Mapped[Optional[int]] = mapped_column(nullable=True)

    spot: Mapped["Spot"] = relationship(back_populates="check_ins")
    user: Mapped["User"] = relationship(back_populates="check_ins")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CheckIn spot_id={self.spot_id} user_id={self.user_id}>"
