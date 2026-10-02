"""
Ziyaret sonrası "yerinde doğrulama" iş mantığı ve alan bazlı güncellik özeti.

## Kurallar

- **Geçerli check-in şartı:** kullanıcının bu noktada son `CHECKIN_WINDOW_HOURS`
  (72) saat içinde bir check-in kaydı olmalı. Pencere bilinçli kısa: "yerinde
  doğrulama" bir ZİYARETE bağlıdır; aylar önceki bir check-in ile bugünkü su
  durumu doğrulanamaz. Check-in kesin GPS kanıtı DEĞİLDİR (bkz.
  `checkin_service`) - bu yüzden arayüz "kesin doğrulandı" iddiasında bulunmaz.
- **Şişirme engeli:** özet, kullanıcı başına YALNIZCA `is_current` cevabı sayar.
  Aynı ziyaret (`check_in_id`) için aynı cevabı tekrar göndermek NO-OP'tur
  (yeni satır/zaman damgası yok). Yeni bir ziyarette aynı cevabı vermek yeni bir
  taze doğrulamadır ama yine TEK oy sayılır. Cevabı değiştirmek eski satırı
  `is_current=false` yapar (geçmiş korunur) ve yenisini ekler. Doğrulama güven
  puanı (`trust_score`) KAZANDIRMAZ - bu adımda o kanal bilinçli olarak kapalı.
- **Eşzamanlılık:** kullanıcı+nokta başına `pg_advisory_xact_lock` + DB kısmi
  unique index'i (bkz. `SpotFieldVerification`).
- Kalıcı teknik veri (`spot_amenities`/`spot_passability`) ASLA değiştirilmez.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check_in import CheckIn
from app.models.enums import RoadType
from app.models.field_verification import (
    SpotFieldVerification,
    VerifiableField,
    VerificationAnswer,
)
from app.models.spot import Spot
from app.schemas.field_verification import (
    FieldFreshnessRead,
    LiveSignalRead,
    ModerationVerificationRow,
    MyVerificationRow,
    MyVerifications,
    SpotFieldFreshness,
    VerificationResultItem,
    VerificationSubmit,
)
from app.services.field_freshness import (
    FIELD_CONFIG,
    PRIMARY_FIELDS,
    CurrentAnswer,
    evaluate_field,
)
from app.services.live_status import aggregates_from_statuses
from app.services.spot_service import SpotNotFoundError

CHECKIN_WINDOW_HOURS = 72

_ROAD_LABEL = {
    RoadType.ASPHALT: "Asfalt",
    RoadType.GRAVEL: "Çakıllı",
    RoadType.DIRT: "Toprak",
    RoadType.ROCKY: "Taşlık",
}


class NoValidCheckInError(Exception):
    """Kullanıcının bu noktada yakın zamanda (CHECKIN_WINDOW_HOURS) check-in'i yok."""


def _reported_text(spot: Spot, field: VerifiableField) -> str | None:
    """Noktanın KALICI, bildirilen bilgisi (doğrulama bunu değiştirmez)."""
    amenities, passability = spot.amenities, spot.passability
    flag = {
        VerifiableField.FRESH_WATER: getattr(amenities, "fresh_water_thread", None),
        VerifiableField.ELECTRICITY: getattr(amenities, "electricity_220v", None),
        VerifiableField.GREY_WATER: getattr(amenities, "grey_water", None),
        VerifiableField.BLACK_WATER: getattr(amenities, "black_water", None),
        VerifiableField.TOILET: getattr(amenities, "has_toilet", None),
        VerifiableField.TRASH_BINS: getattr(amenities, "has_trash_bins", None),
    }
    if field in flag:
        value = flag[field]
        return None if value is None else ("Var olarak bildirilmiş" if value else "Yok olarak bildirilmiş")
    if field in (VerifiableField.PRICE, VerifiableField.CAMPING_BEHAVIOR):
        if not amenities or not amenities.rule_information_known:
            return "Henüz bildirilmedi"
        if field is VerifiableField.PRICE:
            return "Ücretsiz olarak bildirilmiş" if amenities.is_free else (amenities.price_description or "Ücretli olarak bildirilmiş")
        return "Serbest olarak bildirilmiş" if amenities.camping_behavior_allowed else "İzin verilmiyor olarak bildirilmiş"
    if field is VerifiableField.ROAD_ACCESS:
        if passability is None:
            return None
        text_ = f"Yol tipi: {_ROAD_LABEL[passability.road_type]}"
        return text_ + (" · dik eğim" if passability.steep_incline else "")
    if field is VerifiableField.OVERNIGHT:
        return {"allowed": "Geceleme mümkün olarak bildirilmiş", "not_allowed": "Gecelemeye izin verilmiyor olarak bildirilmiş", "unknown": "Geceleme durumu bilinmiyor"}.get(spot.overnight_status)
    return None


async def _current_answers_by_field(
    db: AsyncSession, spot_id: uuid.UUID
) -> dict[VerifiableField, list[CurrentAnswer]]:
    rows = (
        await db.execute(
            select(SpotFieldVerification).where(
                SpotFieldVerification.spot_id == spot_id, SpotFieldVerification.is_current.is_(True)
            )
        )
    ).scalars()
    grouped: dict[VerifiableField, list[CurrentAnswer]] = {f: [] for f in VerifiableField}
    for row in rows:
        # `user_key` anonim: sadece "kaç bağımsız kişi" saymak için, dışarı çıkmaz.
        grouped[row.field].append(CurrentAnswer(str(row.user_id), row.answer, row.created_at))
    return grouped


async def build_spot_field_freshness(db: AsyncSession, spot: Spot) -> SpotFieldFreshness:
    """Tek ek sorgu (spot başına) - bbox'ta ÇAĞRILMAZ, harita performansı etkilenmez."""
    grouped = await _current_answers_by_field(db, spot.id)
    now = datetime.now(UTC)
    # `get_spot_by_id` dynamic_statuses'ı sadece AKTİF (süresi dolmamış, geri çekilmemiş/reddedilmemiş)
    # olanlarla yükler; ek sorgu yok. Bildirim süresi dolunca sinyal kendiliğinden kalkar.
    live = aggregates_from_statuses(spot.dynamic_statuses, now=now)

    def _one(field: VerifiableField) -> FieldFreshnessRead:
        result = evaluate_field(field, grouped[field], now=now, live_aggregates=live)

        def _signal(sig) -> LiveSignalRead:
            return LiveSignalRead(
                code=sig.code,
                severity=sig.severity,
                message=sig.message,
                conflicts_with_verification=sig.conflicts_with_verification,
                report_type=sig.report_type,
                reporter_count=sig.reporter_count,
                trust_level=sig.trust_level,
                expires_at=sig.expires_at,
            )

        return FieldFreshnessRead(
            field=field,
            label=FIELD_CONFIG[field].label,
            status=result.status,
            tone=result.tone,
            status_text=result.status_text,
            consensus_answer=result.consensus_answer,
            conflicting_answers=list(result.conflicting_answers),
            participant_count=result.participant_count,
            supporting_count=result.supporting_count,
            last_verified_on=result.last_verified_at.date() if result.last_verified_at else None,
            age_days=result.age_days,
            confidence=result.confidence,
            fresh_days=result.fresh_days,
            reported_text=_reported_text(spot, field),
            live_signal=_signal(result.live_signal) if result.live_signal else None,
            live_signals=[_signal(sig) for sig in result.live_signals],
            live_overrides=result.live_overrides,
        )

    primary = [_one(f) for f in PRIMARY_FIELDS]
    secondary = [_one(f) for f in VerifiableField if f not in PRIMARY_FIELDS]
    return SpotFieldFreshness(spot_id=spot.id, primary=primary, secondary=secondary)


async def _latest_valid_check_in(
    db: AsyncSession, *, spot_id: uuid.UUID, user_id: uuid.UUID
) -> CheckIn | None:
    since = datetime.now(UTC) - timedelta(hours=CHECKIN_WINDOW_HOURS)
    return await db.scalar(
        select(CheckIn)
        .where(CheckIn.spot_id == spot_id, CheckIn.user_id == user_id, CheckIn.checked_in_at >= since)
        .order_by(CheckIn.checked_in_at.desc())
        .limit(1)
    )


async def get_my_verifications(
    db: AsyncSession, *, spot_id: uuid.UUID, user_id: uuid.UUID
) -> MyVerifications:
    check_in = await _latest_valid_check_in(db, spot_id=spot_id, user_id=user_id)
    rows = list(
        (
            await db.execute(
                select(SpotFieldVerification)
                .where(SpotFieldVerification.spot_id == spot_id, SpotFieldVerification.user_id == user_id)
                .order_by(SpotFieldVerification.created_at.desc())
            )
        ).scalars()
    )
    current = {r.field: r.answer for r in rows if r.is_current}
    pending = check_in is not None and not any(r.check_in_id == check_in.id for r in rows)
    if check_in is None:
        code, message = (
            "NO_RECENT_CHECKIN",
            f"Yerinde doğrulama için son {CHECKIN_WINDOW_HOURS} saat içinde bu noktada check-in yapmış olmalısınız.",
        )
    else:
        code, message = "ELIGIBLE", "Bu ziyaret için saha bilgisini doğrulayabilirsiniz."
    return MyVerifications(
        eligible=check_in is not None,
        eligibility_code=code,  # type: ignore[arg-type]
        eligibility_message=message,
        check_in_at=check_in.checked_in_at if check_in else None,
        has_pending_prompt=pending,
        current_answers=current,
        history=[
            MyVerificationRow(field=r.field, answer=r.answer, created_at=r.created_at, is_current=r.is_current)
            for r in rows
        ],
    )


async def submit_verifications(
    db: AsyncSession, *, spot_id: uuid.UUID, user_id: uuid.UUID, data: VerificationSubmit
) -> list[VerificationResultItem]:
    """
    Raises: SpotNotFoundError, NoValidCheckInError. `commit` çağıran taraf değil
    burada yapılır; sonuç listesi her alan için eylemi (created/updated/unchanged/skipped) döner.
    """
    spot_exists = await db.scalar(select(Spot.id).where(Spot.id == spot_id, Spot.deleted_at.is_(None)))
    if spot_exists is None:
        raise SpotNotFoundError(spot_id)

    # Aynı kullanıcı+nokta için eşzamanlı gönderimleri sıraya sok (bkz. modül docstring'i).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"verify:{user_id}:{spot_id}"}
    )

    check_in = await _latest_valid_check_in(db, spot_id=spot_id, user_id=user_id)
    if check_in is None:
        raise NoValidCheckInError(spot_id)

    results: list[VerificationResultItem] = []
    for field, answer in data.answers.items():
        if answer is VerificationAnswer.UNKNOWN:
            results.append(VerificationResultItem(field=field, action="skipped"))
            continue

        existing = await db.scalar(
            select(SpotFieldVerification).where(
                SpotFieldVerification.spot_id == spot_id,
                SpotFieldVerification.user_id == user_id,
                SpotFieldVerification.field == field,
                SpotFieldVerification.is_current.is_(True),
            )
        )
        if existing is not None and existing.answer is answer and existing.check_in_id == check_in.id:
            results.append(VerificationResultItem(field=field, action="unchanged"))
            continue

        if existing is not None:
            existing.is_current = False
            await db.flush()  # kısmi unique index'i ihlal etmeden önce eskiyi kapat
        db.add(
            SpotFieldVerification(
                spot_id=spot_id,
                user_id=user_id,
                check_in_id=check_in.id,
                field=field,
                answer=answer,
                is_current=True,
            )
        )
        results.append(
            VerificationResultItem(field=field, action="updated" if existing is not None else "created")
        )

    await db.commit()
    return results


async def list_verifications_for_moderation(
    db: AsyncSession, *, spot_id: uuid.UUID, limit: int = 200
) -> list[ModerationVerificationRow]:
    rows = (
        await db.execute(
            select(SpotFieldVerification)
            .where(SpotFieldVerification.spot_id == spot_id)
            .order_by(SpotFieldVerification.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        ModerationVerificationRow(
            id=r.id,
            user_id=r.user_id,
            check_in_id=r.check_in_id,
            field=r.field,
            answer=r.answer,
            created_at=r.created_at,
            is_current=r.is_current,
        )
        for r in rows
    ]
