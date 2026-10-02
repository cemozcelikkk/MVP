"""
`saved_lists` / `saved_list_items`: Favoriler ve özel seyahat listeleri.

Favoriler ayrı bir tablo/sistem DEĞİLDİR: her kullanıcının
`is_default_favorites=True` olan tek bir SavedList'i vardır (ilk favori
eklemede örtük olarak oluşturulur, bkz. `saved_list_service`).
`POST /spots/{id}/favorite` bu listedeki öğeleri toggle'lar. Böylece
favoriler ve kullanıcı tanımlı özel listeler ("Ege Turu 2026" vb.) aynı
iki tabloyu paylaşır, paralel bir favoriler sistemi gerekmez.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.spot import Spot
    from app.models.user import User


class SavedList(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "saved_lists"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # True ise bu, kullanıcının POST /spots/{id}/favorite ile toggle'ladığı
    # varsayılan "Favoriler" listesidir. Kısmi (partial) unique index,
    # kullanıcı başına en fazla BİR default-favorites listesine izin verir;
    # is_default_favorites=False olan (özel) listeler bu kısıttan muaftır -
    # bir kullanıcı istediği kadar özel liste oluşturabilir.
    is_default_favorites: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    items: Mapped[list["SavedListItem"]] = relationship(
        back_populates="saved_list", cascade="all, delete-orphan"
    )
    user: Mapped["User"] = relationship()

    __table_args__ = (
        Index(
            "uq_saved_lists_one_default_favorites_per_user",
            "user_id",
            unique=True,
            postgresql_where=is_default_favorites.is_(True),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SavedList id={self.id} title={self.title!r} user_id={self.user_id}>"


class SavedListItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "saved_list_items"

    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("saved_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    planned_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    saved_list: Mapped["SavedList"] = relationship(back_populates="items")
    spot: Mapped["Spot"] = relationship()

    __table_args__ = (
        # Aynı spot aynı listeye iki kez eklenemez.
        UniqueConstraint("list_id", "spot_id", name="uq_saved_list_items_list_spot"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SavedListItem list_id={self.list_id} spot_id={self.spot_id}>"
