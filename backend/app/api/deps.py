"""API genelinde paylaşılan FastAPI dependency'leri (auth, RBAC vb.)."""
from collections.abc import Callable, Coroutine

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token, token_is_current
from app.models.enums import UserRole
from app.models.user import User

# tokenUrl, Swagger UI'daki "Authorize" penceresinin token almak için POST
# edeceği endpoint'i belirtir; gerçek doğrulama burada değil get_current_user
# içinde yapılır.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Kimlik doğrulanamadı.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_exception

    user = await db.get(User, user_id)
    if user is None or not user.is_active or not token_is_current(token, user.tokens_valid_after):
        raise credentials_exception

    return user


async def resolve_user_from_authorization_header(
    authorization: str | None, db: AsyncSession
) -> User | None:
    """
    `get_current_user`'ın `Depends()` OLMAYAN, manuel çağrılan hafif
    eşleniği - eksik/geçersiz token'da 401 FIRLATMAZ, sessizce `None` döner.

    Bir `Depends()` bağımlılığı tanımlandığı endpoint'e gelen HER istekte
    koşulsuz çalışır. Bu fonksiyon ise çağıran tarafından SADECE gerçekten
    gerektiğinde (ör. bir query flag true ise) çağrılır - böylece o bayrak
    kapalıyken (varsayılan/çoğunluk durum) hiçbir token decode/DB sorgusu
    YAPILMAZ. Sadece `GET /spots/bbox?with_compatibility=true` gibi, çok sık
    çağrılan ama auth'un GERÇEKTEN opsiyonel olduğu performans-kritik
    uçlarda kullanın - genel kural hâlâ `Depends(get_current_user)`.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None

    token = authorization[7:]
    user_id = decode_access_token(token)
    if user_id is None:
        return None

    user = await db.get(User, user_id)
    if user is None or not user.is_active or not token_is_current(token, user.tokens_valid_after):
        return None
    return user


def require_role(allowed_roles: list[UserRole]) -> Callable[[User], Coroutine[None, None, User]]:
    """
    Generic RBAC dependency factory: sadece `allowed_roles` içindeki role
    sahip kullanıcıların geçmesine izin verir, aksi halde 403 fırlatır.

    Kullanım: `current_user: User = Depends(require_role([UserRole.ADMIN]))`.
    """

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz yok.",
            )
        return current_user

    return dependency


# En az MODERATOR (ya da ADMIN) rolü gerektiren endpoint'ler için hazır
# dependency - `require_role` her çağrıda yeniden tanımlamak yerine.
require_moderator = require_role([UserRole.MODERATOR, UserRole.ADMIN])
