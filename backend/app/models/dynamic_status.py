"""
`dynamic_status`: Türkiye gerçeklerine özel canlı/geçici durum bildirimleri.

Bir spot için "şu an zabıta uyarısı var mı, ne kadar kalabalık?" gibi
zamanla değişen bilgileri tutar. `spots` ile 1-N ilişkilidir: her
bildirim yeni bir satır olarak eklenir, en güncel durum
`reported_at DESC` sıralamasıyla okunur ve `valid_until` geçtiğinde
istemci tarafında/serviste süresi dolmuş sayılır.

## Süreli canlı saha bildirimleri (genişletme)

Aynı tablo artık türlü, moderasyonlu, süreli saha bildirimlerini de taşır
(`report_type`, `moderation_state`, ...). Eski `police_intervention`/`crowd_level`
sütunları ve satırları KORUNUR (geriye dönük API uyumu); yeni türler için bu
sütunlar en yakın eski karşılığıyla türetilerek doldurulur (bkz.
`app.services.live_status.legacy_columns_for`).

- **Aktiflik sorgu anında belirlenir** (`ACTIVE_REPORT_CONDITION`): cron yok. Süresi
  dolan/geri çekilen/reddedilen satır silinmez, sadece aktif sonuçlardan düşer.
  `valid_until IS NULL` (eski "süresiz" kayıtlar) `reported_at + 24 saat` sayılır -
  yanlışlıkla sonsuza dek "aktif" kalan eski uyarı olmasın.
- **Bağımsız destek sayımı:** aynı (nokta, kullanıcı, tür) için AKTİF penceresi
  çakışan ikinci bir bildirim `ex_dynamic_status_one_active_report_per_user_type`
  exclusion constraint'iyle DB seviyesinde engellenir (eşzamanlı isteklerde de).
  Eski (`is_legacy`) satırlar kapsam dışıdır - migration bunları olduğu gibi korur.
- `reporter_on_site`: bildirimin GÖNDERİLDİĞİ anda kullanıcının son 72 saat içinde o
  noktada check-in'i var mıydı (tam check-in zamanı/konumu HİÇBİR yerde saklanmaz/dönmez).
"""
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    and_,
    false,
    func,
    literal_column,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import (
    CrowdLevel,
    LiveReportType,
    PoliceInterventionStatus,
    ReportModerationState,
)

# `valid_until` NULL olan eski kayıtların "süresiz aktif" kalmaması için varsayılan ömür.
LEGACY_OPEN_ENDED_HOURS = 24


if TYPE_CHECKING:
    from app.models.spot import Spot
    from app.models.user import User


class DynamicStatus(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "dynamic_status"

    spot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reported_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    police_intervention: Mapped[PoliceInterventionStatus] = mapped_column(
        SAEnum(
            PoliceInterventionStatus,
            name="police_intervention_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=PoliceInterventionStatus.NONE,
        nullable=False,
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    crowd_level: Mapped[Optional[CrowdLevel]] = mapped_column(
        SAEnum(
            CrowdLevel,
            name="crowd_level",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )

    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Bildirimin ne kadar süre geçerli sayılacağı (örn. "zabıta 2 saat
    # sonra gider" gibi topluluk tahminine dayanır). NULL ise süresiz.
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Süreli canlı saha bildirimi alanları ---
    # NULL = "tür atanmamış" bilgi satırı (ör. eski yalnızca-kalabalık notu); aktif
    # uyarı/güncellik hesaplarına GİRMEZ. Runtime'da eski yazıcılar (seed vb.) için
    # `live_status.effective_report_type` police/crowd'dan türetir.
    report_type: Mapped[Optional[LiveReportType]] = mapped_column(
        SAEnum(
            LiveReportType,
            name="live_report_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    moderation_state: Mapped[ReportModerationState] = mapped_column(
        SAEnum(
            ReportModerationState,
            name="report_moderation_state",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ReportModerationState.PENDING,
        server_default=ReportModerationState.PENDING.value,
        nullable=False,
    )
    # Kullanıcının seçtiği süre (6/12/24/48); eski kayıtlarda NULL.
    duration_hours: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    # Bildirim anında bildiren son 72 saatte o noktada check-in yapmış mıydı (bkz. modül docstring'i).
    reporter_on_site: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Migration öncesi satırlar: DB seviyesindeki "tek aktif bildirim" kuralının kapsamı dışında.
    is_legacy: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)

    spot: Mapped["Spot"] = relationship(back_populates="dynamic_statuses")
    reported_by_user: Mapped[Optional["User"]] = relationship()

    __table_args__ = (
        # Aynı kullanıcı + nokta + tür için AKTİF pencereleri çakışan ikinci bildirim
        # engellenir -> tekrar gönderimle destek sayısı şişirilemez (eşzamanlı istekler dahil).
        # NULL reported_by / NULL report_type satırları hiçbir zaman çakışmaz (SQL NULL semantiği).
        ExcludeConstraint(
            ("spot_id", "="),
            ("reported_by", "="),
            ("report_type", "="),
            (
                literal_column(
                    "(CASE WHEN valid_until IS NULL THEN tstzrange(reported_at, NULL) "
                    "ELSE tstzrange(reported_at, GREATEST(valid_until, reported_at)) END)"
                ),
                "&&",
            ),
            using="gist",
            where=text("NOT is_legacy AND moderation_state IN ('pending', 'confirmed')"),
            name="ex_dynamic_status_one_active_report_per_user_type",
        ),
        Index("ix_dynamic_status_moderation", "moderation_state", "valid_until"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DynamicStatus spot_id={self.spot_id} police={self.police_intervention}>"


# Sorgu-anı aktiflik koşulu (cron YOK): moderasyon durumu pending/confirmed VE süresi dolmamış.
# `spot_service` (bbox/sync/detay eager-load) ve canlı bildirim servisi aynı koşulu paylaşır.
REPORT_NOT_EXPIRED = (
    func.coalesce(
        DynamicStatus.valid_until,
        DynamicStatus.reported_at + timedelta(hours=LEGACY_OPEN_ENDED_HOURS),
    )
    > func.now()
)
REPORT_STATE_OPEN = DynamicStatus.moderation_state.in_(
    [ReportModerationState.PENDING, ReportModerationState.CONFIRMED]
)
ACTIVE_REPORT_CONDITION = and_(REPORT_STATE_OPEN, REPORT_NOT_EXPIRED)
