"""`/api/v1/auth` altındaki kimlik doğrulama endpoint'leri."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserRead
from app.services.auth_service import EmailAlreadyExistsError, authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> UserRead:
    try:
        user = await register_user(db, data=payload)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Bu e-posta adresi zaten kayıtlı."
        )
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    OAuth2 password flow (form-data: `username` + `password`) kullanır ki
    Swagger UI'daki "Authorize" düğmesi doğrudan çalışsın. `username`
    alanına kayıt olurken kullandığınız e-posta adresini girin.
    """
    user = await authenticate_user(db, email=form_data.username, password=form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id)
    return Token(access_token=token)


@router.get("/me", response_model=UserRead)
async def read_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


from app.schemas.user import EmailRequest, PasswordResetRequest, TokenRequest
from app.services.account_service import consume_account_token, issue_account_token


@router.post("/forgot-password")
async def forgot_password(payload: EmailRequest, db: AsyncSession = Depends(get_db)):
    try:
        await issue_account_token(db, payload.email, "reset")
    except Exception:
        await db.rollback()
        # Do not reveal account existence through provider errors.
        import logging
        logging.getLogger("karavantr.mail").error("Account mail delivery failed")
    return {"message": "Hesap uygunsa şifre sıfırlama bağlantısı gönderildi."}

@router.post("/reset-password")
async def reset_password(payload: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    await consume_account_token(db, payload.token, "reset", payload.password)
    return {"message": "Şifreniz güncellendi. Yeniden giriş yapabilirsiniz."}

@router.post("/request-verification")
async def request_verification(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await issue_account_token(db, user.email, "verify")
    except Exception:
        await db.rollback()
        raise HTTPException(503, "E-posta gönderilemedi. Daha sonra tekrar deneyin.")
    return {"message": "Doğrulama bağlantısı gönderildi."}

@router.post("/verify-email")
async def verify_email(payload: TokenRequest, db: AsyncSession = Depends(get_db)):
    await consume_account_token(db, payload.token, "verify")
    return {"message": "E-posta adresiniz doğrulandı."}
