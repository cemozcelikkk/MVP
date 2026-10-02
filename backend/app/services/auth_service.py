"""Kullanıcı kayıt/giriş iş mantığı."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


class EmailAlreadyExistsError(Exception):
    """
    Sadece "bu e-posta zaten kayıtlı" durumunu işaretlemek için özel bir tip.

    Bilerek bare `ValueError` KULLANILMADI: `hash_password()` (passlib/bcrypt
    sürüm uyumsuzluğu gibi nedenlerle) kendi ValueError'unu fırlatabilir;
    endpoint bunu bare ValueError yakalasaydı gerçek hatayı yanlışlıkla
    409 "e-posta zaten kayıtlı" olarak raporlardı - geliştirme sırasında
    tam olarak bu yaşandı.
    """


async def get_user_by_email(db: AsyncSession, *, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def register_user(db: AsyncSession, *, data: UserCreate) -> User:
    """E-posta zaten kayıtlıysa `EmailAlreadyExistsError` fırlatır (endpoint bunu 409'a çevirir)."""
    existing = await get_user_by_email(db, email=data.email)
    if existing is not None:
        raise EmailAlreadyExistsError(data.email)

    user = User(
        email=data.email,
        display_name=data.username,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user, attribute_names=["created_at", "updated_at"])
    return user


async def authenticate_user(db: AsyncSession, *, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email=email)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        return None
    return user
