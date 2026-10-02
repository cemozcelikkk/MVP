"""
`spot_field_verifications`: ziyaret sonrası, alan bazlı "yerinde doğrulama" kayıtları.

## Tasarım kararları

- **Kalıcı teknik veriyi DEĞİŞTİRMEZ.** `spot_amenities`/`spot_passability` (noktanın
  bildirilen kalıcı bilgisi) olduğu gibi kalır; bu tablo ayrı bir "topluluk
  doğrulaması" katmanıdır. Tek bir kullanıcının cevabı asla noktanın teknik
  verisini sessizce yazmaz. Süreli canlı bildirimlerden (`dynamic_status`,
  "zabıta var" gibi acil/geçici durumlar) de ayrıdır - ikisi arayüzde yan yana
  gösterilir, birbirinin yerine geçmez (bkz. `field_freshness.evaluate_field`).
- **Geçmiş korunur (append-only).** Bir kullanıcı aynı alanı sonraki ziyarette
  güncellerse eski satır SİLİNMEZ/EZİLMEZ; `is_current=false` yapılır ve yeni bir
  satır eklenir. Özet hesaplanırken kullanıcı başına YALNIZCA `is_current` satır
  sayılır - aynı kişi aynı alan için birden fazla "oy" oluşturamaz.
  `uq_spot_field_verifications_one_current` kısmi unique index'i bunu DB
  seviyesinde de garanti eder (bkz. `vehicle_profiles`'taki aynı desen).
- `check_in_id`: doğrulamanın bağlı olduğu ziyaret. Kesin GPS kanıtı DEĞİLDİR
  (check-in mesafe kontrolü sahteciliğe karşı kusursuz değil) - sadece bir
  "bu kullanıcı yakın zamanda noktada check-in yaptı" sinyalidir.
"""
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.check_in import CheckIn
    from app.models.spot import Spot
    from app.models.user import User


class VerifiableField(str, enum.Enum):
    """Yerinde doğrulanabilen saha bilgileri. Fiyat, mevcut şemada bir fiyat alanı
    olmadığı için KASITLI OLARAK yok ("Kamping bilgileri" adımına bırakıldı)."""

    ROAD_ACCESS = "road_access"
    OVERNIGHT = "overnight"
    FRESH_WATER = "fresh_water"
    ELECTRICITY = "electricity"
    GREY_WATER = "grey_water"
    BLACK_WATER = "black_water"
    TOILET = "toilet"
    TRASH_BINS = "trash_bins"
    PRICE = "price"
    CAMPING_BEHAVIOR = "camping_behavior"


class VerificationAnswer(str, enum.Enum):
    """Alan başına geçerli alt küme `VERIFIABLE_ANSWERS`'ta. `unknown` "bilmiyorum /
    kontrol etmedim" demektir: API kabul eder ama SAKLANMAZ ve hiçbir sayıma girmez."""

    WORKING = "working"
    NOT_WORKING = "not_working"
    ALLOWED = "allowed"
    NOT_ALLOWED = "not_allowed"
    PASSABLE = "passable"
    DIFFICULT = "difficult"
    IMPASSABLE = "impassable"
    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"


_SERVICE = (VerificationAnswer.WORKING, VerificationAnswer.NOT_WORKING)

VERIFIABLE_ANSWERS: dict[VerifiableField, tuple[VerificationAnswer, ...]] = {
    VerifiableField.ROAD_ACCESS: (
        VerificationAnswer.PASSABLE,
        VerificationAnswer.DIFFICULT,
        VerificationAnswer.IMPASSABLE,
    ),
    VerifiableField.OVERNIGHT: (VerificationAnswer.ALLOWED, VerificationAnswer.NOT_ALLOWED),
    VerifiableField.FRESH_WATER: _SERVICE,
    VerifiableField.ELECTRICITY: _SERVICE,
    VerifiableField.GREY_WATER: _SERVICE,
    VerifiableField.BLACK_WATER: _SERVICE,
    VerifiableField.TOILET: _SERVICE,
    VerifiableField.TRASH_BINS: _SERVICE,
    VerifiableField.PRICE: (VerificationAnswer.FREE, VerificationAnswer.PAID),
    VerifiableField.CAMPING_BEHAVIOR: (VerificationAnswer.ALLOWED, VerificationAnswer.NOT_ALLOWED),
}


class SpotFieldVerification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "spot_field_verifications"

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_in_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("check_ins.id", ondelete="SET NULL"), nullable=True
    )

    field: Mapped[VerifiableField] = mapped_column(
        SAEnum(
            VerifiableField,
            name="verifiable_field",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    answer: Mapped[VerificationAnswer] = mapped_column(
        SAEnum(
            VerificationAnswer,
            name="verification_answer",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Kullanıcı+nokta+alan başına en fazla BİR true satır (bkz. modül docstring'i).
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    spot: Mapped["Spot"] = relationship()
    user: Mapped["User"] = relationship()
    check_in: Mapped[Optional["CheckIn"]] = relationship()

    __table_args__ = (
        Index(
            "uq_spot_field_verifications_one_current",
            "spot_id",
            "user_id",
            "field",
            unique=True,
            postgresql_where=is_current.is_(True),
        ),
        Index("ix_spot_field_verifications_spot_current", "spot_id", "is_current"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SpotFieldVerification spot={self.spot_id} field={self.field} answer={self.answer}>"
