"""`spot_photos`: Bir spot'a ait kullanıcı fotoğrafları."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, String, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.spot import Spot


class SpotPhoto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "spot_photos"

    photo_kind: Mapped[str] = mapped_column(
        String(20), default="general", server_default="general", nullable=False
    )
    is_hidden: Mapped[bool] = mapped_column(default=False, server_default=false(), nullable=False)

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Nesne depolama (S3 / Cloudflare R2 vb.) üzerindeki dosya anahtarı/URL'i.
    # Mobil istemci offline modda yerel dosya yolunu tutar, senkron sırasında
    # önce depolamaya yüklenip bu alan güncellenir.
    storage_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Harita pinleri / kart görünümleri için 300x300 küçük WebP versiyonu
    # (bkz. photo_service._process_image). NULL olabilir: bu alan
    # eklenmeden önce yüklenmiş eski fotoğraflarda thumbnail üretilmemiştir.
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    caption: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    spot: Mapped["Spot"] = relationship(back_populates="photos")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SpotPhoto spot_id={self.spot_id}>"
