import asyncio
import hashlib
import secrets
import smtplib
import ssl
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.account_token import AccountToken
from app.models.user import User


def token_digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def deliver_message(email, purpose, raw):
    message = EmailMessage()
    message["To"] = email
    message["From"] = settings.SMTP_FROM
    message["Subject"] = "KaravanTR — " + (
        "Şifre sıfırlama" if purpose == "reset" else "E-posta doğrulama"
    )
    link = (
        settings.FRONTEND_URL.rstrip("/")
        + "/#"
        + urlencode({"account_action": purpose, "token": raw})
    )
    message.set_content(
        "Bu işlemi siz başlattıysanız bağlantıyı açın. Bağlantı tek kullanımlıktır.\n\n" + link
    )
    if settings.MAIL_BACKEND == "file":
        if settings.ENVIRONMENT != "development":
            raise RuntimeError("Üretimde SMTP yapılandırılmalı.")
        settings.MAIL_OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        (settings.MAIL_OUTBOX_DIR / f"{uuid.uuid4().hex}.eml").write_bytes(message.as_bytes())
    else:
        if not settings.SMTP_HOST:
            raise RuntimeError("SMTP_HOST eksik.")
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
            if settings.SMTP_STARTTLS:
                client.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            client.send_message(message)


async def issue_account_token(db, email, purpose):
    user = await db.scalar(
        select(User).where(User.email == email, User.is_active.is_(True)).with_for_update()
    )
    if not user or (purpose == "verify" and user.email_verified):
        return
    raw = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    await db.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    row = AccountToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=token_digest(raw),
        expires_at=now + timedelta(minutes=30 if purpose == "reset" else 1440),
    )
    db.add(row)
    await db.flush()
    # Delivery failure rolls back the new token and leaves prior tokens usable.
    await asyncio.to_thread(deliver_message, user.email, purpose, raw)
    await db.commit()


async def consume_account_token(db, raw, purpose, password=None):
    row = await db.scalar(
        select(AccountToken)
        .where(
            AccountToken.token_hash == token_digest(raw),
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
            AccountToken.expires_at > func.now(),
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(400, "Bağlantı geçersiz, kullanılmış veya süresi dolmuş.")
    user = await db.scalar(select(User).where(User.id == row.user_id).with_for_update())
    if not user or not user.is_active:
        raise HTTPException(400, "Bağlantı geçersiz.")
    if purpose == "reset":
        user.hashed_password = hash_password(password)
        # Compare whole-second JWT iat timestamps; new login is allowed from the next second.
        user.tokens_valid_after = datetime.now(UTC)
        await db.execute(
            update(AccountToken)
            .where(
                AccountToken.user_id == user.id,
                AccountToken.purpose == "reset",
                AccountToken.used_at.is_(None),
            )
            .values(used_at=func.now())
        )
    else:
        user.email_verified = True
        row.used_at = datetime.now(UTC)
    await db.commit()


async def delete_account(db, user, password, confirmation):
    if confirmation != "HESABIMI SİL" or not verify_password(password, user.hashed_password):
        raise HTTPException(400, "Şifreyi ve HESABIMI SİL onayını kontrol edin.")
    # Preserve shared spot information, remove personally attributable contributions.
    from app.models.check_in import CheckIn
    from app.models.dynamic_status import DynamicStatus
    from app.models.field_verification import SpotFieldVerification
    from app.models.review import Review
    from app.models.saved_list import SavedList
    from app.models.spot import Spot
    from app.models.spot_photo import SpotPhoto
    from app.models.vehicle_profile import VehicleProfile
    from app.services.review_service import _refresh_spot_rating_summary

    affected = list(
        (await db.scalars(select(Review.spot_id).where(Review.user_id == user.id).distinct())).all()
    )
    for model, column in (
        (Review, Review.user_id),
        (SpotFieldVerification, SpotFieldVerification.user_id),
        (CheckIn, CheckIn.user_id),
        (VehicleProfile, VehicleProfile.user_id),
        (SavedList, SavedList.user_id),
    ):
        await db.execute(delete(model).where(column == user.id))
    await db.execute(
        update(Spot)
        .where(Spot.created_by == user.id)
        .values(created_by=None, updated_at=func.now())
    )
    await db.execute(
        update(SpotPhoto).where(SpotPhoto.uploaded_by == user.id).values(uploaded_by=None)
    )
    await db.execute(
        update(DynamicStatus).where(DynamicStatus.reported_by == user.id).values(reported_by=None)
    )
    # Direct SQL avoids ORM relationships attempting to NULL non-null review/check-in FKs.
    await db.execute(delete(User).where(User.id == user.id))
    for spot_id in affected:
        await _refresh_spot_rating_summary(db, spot_id)
    await db.commit()
