"""
User modeli.

Minimal JWT auth sistemi için gerekli alanları içerir. `display_name`,
kayıt (register) isteğindeki `username` alanını karşılar - ayrı bir
"username" kolonu tutmuyoruz, uygulama genelinde görünen ad olarak bu
kullanılıyor.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, false
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.check_in import CheckIn
    from app.models.review import Review
    from app.models.spot import Spot
    from app.models.vehicle_profile import VehicleProfile


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    email_verified: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False
    )
    tokens_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Topluluk güveni skoru: check-in, doğrulanmış katkı gibi eylemlerle
    # artar. Şimdilik basit bir sayaç; ileride ağırlıklı bir formüle
    # (GPS doğrulamalı check-in, moderatör onayı vb.) evrilebilir.
    trust_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Sahiplik kontrolü (DELETE /spots/{id}) ve moderasyon (PATCH /verify)
    # yetkilerinin dayandığı rol. Varsayılan: sıradan kullanıcı.
    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            name="user_role",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=UserRole.USER,
        nullable=False,
    )

    spots_created: Mapped[list["Spot"]] = relationship(back_populates="created_by_user")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")
    check_ins: Mapped[list["CheckIn"]] = relationship(back_populates="user")
    vehicle_profiles: Mapped[list["VehicleProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
