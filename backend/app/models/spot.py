"""
`spots`: Sistemin çekirdek POI (Point of Interest) tablosu.

`coordinates` alanı PostGIS GEOMETRY(Point, 4326) tipindedir; WGS84
(GPS) koordinat sistemini kullanır ve tüm mekansal sorgular (bbox,
yakınlık, mesafe) bu sütun üzerinden GiST index ile çalışır.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SpotCategory

if TYPE_CHECKING:
    from app.models.check_in import CheckIn
    from app.models.dynamic_status import DynamicStatus
    from app.models.review import Review
    from app.models.spot_amenities import SpotAmenities
    from app.models.spot_passability import SpotPassability
    from app.models.spot_photo import SpotPhoto
    from app.models.user import User


class Spot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "spots"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category: Mapped[SpotCategory] = mapped_column(
        SAEnum(
            SpotCategory,
            name="spot_category",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        index=True,
    )

    # SRID 4326 = WGS84 (standart GPS lat/lon). geography yerine geometry
    # kullanıyoruz çünkü Türkiye ölçeğindeki bbox sorguları için index
    # performansı yeterli ve ST_MakeEnvelope ile doğrudan uyumlu.
    coordinates: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )

    altitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Denormalize edilmiş yorum özet alanları: her yorum eklendiğinde
    # review_service.add_review() tarafından yeniden hesaplanır. Her bbox/sync
    # isteğinde reviews tablosuna JOIN/aggregate atmamak için burada tutulur.
    average_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Soft-delete damgası. Fiziksel DELETE yerine burası doldurulur; böylece
    # offline istemciler /spots/sync üzerinden "bu nokta kaldırıldı"
    # bilgisini delta olarak alıp yerel SQLite'tan silebilir. NULL = aktif.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    overnight_status: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown", nullable=False
    )
    max_stay_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rule_checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    private_property_permission: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown", nullable=False
    )
    entry_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    approach_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_season: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # --- İlişkiler ---
    created_by_user: Mapped[Optional["User"]] = relationship(back_populates="spots_created")

    passability: Mapped[Optional["SpotPassability"]] = relationship(
        back_populates="spot", uselist=False, cascade="all, delete-orphan"
    )
    amenities: Mapped[Optional["SpotAmenities"]] = relationship(
        back_populates="spot", uselist=False, cascade="all, delete-orphan"
    )
    dynamic_statuses: Mapped[list["DynamicStatus"]] = relationship(
        back_populates="spot",
        cascade="all, delete-orphan",
        order_by="DynamicStatus.reported_at.desc()",
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="spot", cascade="all, delete-orphan"
    )
    photos: Mapped[list["SpotPhoto"]] = relationship(
        back_populates="spot", cascade="all, delete-orphan"
    )
    check_ins: Mapped[list["CheckIn"]] = relationship(
        back_populates="spot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "overnight_status IN ('allowed','not_allowed','unknown')",
            name="ck_spots_overnight_status",
        ),
        CheckConstraint(
            "private_property_permission IN ('required','not_required','unknown')",
            name="ck_spots_property_permission",
        ),
        CheckConstraint(
            "max_stay_nights IS NULL OR max_stay_nights BETWEEN 1 AND 365", name="ck_spots_max_stay"
        ),
        CheckConstraint(
            "(entry_latitude IS NULL AND entry_longitude IS NULL) OR (entry_latitude BETWEEN -90 AND 90 AND entry_longitude BETWEEN -180 AND 180 AND entry_latitude IS NOT NULL AND entry_longitude IS NOT NULL)",
            name="ck_spots_entry_coordinates",
        ),
        # GiST index Geometry(spatial_index=True) ile otomatik oluşur;
        # burada ek olarak sık filtrelenen alanlar için composite index.
        Index("ix_spots_category_verified", "category", "is_verified"),
        # /spots/sync delta sorgusunun hot path'i: "updated_at > since".
        Index("ix_spots_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Spot id={self.id} title={self.title!r} category={self.category}>"
