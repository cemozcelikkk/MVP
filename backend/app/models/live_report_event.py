"""
`live_report_events`: canlı bildirimlerin moderasyon / geri çekme işlem geçmişi (append-only).

Her durum değişikliği (moderatör onayı, reddi, geri çekme; kullanıcının kendi geri
çekmesi dahil) bir satır bırakır: kim (`actor_id`, o andaki rolüyle), ne zaman, hangi
durumdan hangisine. Bildirim satırı silinmez; bu tablo "işlemi yapan moderatör ve
zaman kaydı" ihtiyacını karşılar. Yalnızca moderatör/admin uçlarından okunur.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import ReportModerationState, UserRole


class LiveReportEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "live_report_events"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dynamic_status.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Kullanıcı silinirse geçmiş kalır (kimlik NULL olur).
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # İşlem anındaki rol (rol sonradan değişse bile geçmiş doğru kalır).
    actor_role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            name="user_role",
            create_type=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    from_state: Mapped[ReportModerationState] = mapped_column(
        SAEnum(
            ReportModerationState,
            name="report_moderation_state",
            create_type=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    to_state: Mapped[ReportModerationState] = mapped_column(
        SAEnum(
            ReportModerationState,
            name="report_moderation_state",
            create_type=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
