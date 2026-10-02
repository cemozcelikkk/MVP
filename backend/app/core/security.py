"""
Şifre hashleme ve JWT access token üretimi/doğrulaması.

Minimal bir JWT auth şeması: token payload'ı sadece `sub` (kullanıcı
UUID'si) ve `exp` (son kullanma) içerir - rol/izin sistemi ileride
gerekirse buraya eklenebilir.
"""
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(*, subject: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {"sub": str(subject), "exp": expire, "iat": datetime.now(timezone.utc).timestamp()}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Token geçersiz/süresi dolmuşsa None döner; endpoint bunu 401'e çevirir."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    subject = payload.get("sub")
    if subject is None:
        return None

    try:
        return uuid.UUID(subject)
    except ValueError:
        return None


def token_is_current(token: str, valid_after) -> bool:
    if valid_after is None:
        return True
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return float(payload.get("iat", 0)) > valid_after.timestamp()
    except (JWTError, ValueError, TypeError):
        return False
