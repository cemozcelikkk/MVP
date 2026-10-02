"""
Backend testleri için ortak pytest fixture'ları.

`vehicle_profile_service` testleri (compatibility_service'in aksine) saf
fonksiyonlar DEĞİL - gerçek transaction/commit, `pg_advisory_xact_lock` ve
DB'deki kısmi (partial) unique index'e dayanıyorlar. Bu yüzden GERÇEK bir
Postgres bağlantısı kullanılıyor (docker-compose'daki geliştirme
veritabanı, `settings.DATABASE_URL` üzerinden - `app.core.database.AsyncSessionLocal`
ile birebir aynı engine) - sahte/mock bir session, "tek aktif profil"
garantisinin GERÇEKTEN Postgres seviyesinde tuttuğunu doğrulayamaz.

Her test kendi rastgele e-postalı (`pytest-<uuid>@karavantr-qa.dev`)
kullanıcısını/kullanıcılarını oluşturur ve `make_user` fixture'ı test
bitince bunları SİLER (users.id -> vehicle_profiles.user_id ON DELETE
CASCADE olduğu için ilişkili profiller de otomatik temizlenir) - dev
veritabanında kalıcı test verisi bırakmaz.
"""
import logging
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from datetime import UTC, datetime, timedelta

import httpx
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.check_in import CheckIn
from app.models.enums import SpotCategory
from app.models.spot import Spot
from app.models.user import User
from app.schemas.common import Coordinates
from app.schemas.spot import SpotCreate
from app.schemas.spot_amenities import SpotAmenitiesCreate
from app.schemas.spot_passability import SpotPassabilityCreate
from app.services.spot_service import create_spot

# Testlerde SQL echo gürültüsünü sustur (settings.ENVIRONMENT=development
# iken engine echo=True kuruluyor - bkz. app/core/database.py; global engine
# ayarını DEĞİŞTİRMİYORUZ, sadece bu logger'ın seviyesini yükseltiyoruz).
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def make_user(
    db_session: AsyncSession,
) -> AsyncGenerator[Callable[..., Coroutine[None, None, User]], None]:
    """
    `await make_user()` her çağrıda YENİ bir test kullanıcısı oluşturur ve
    commit eder; fixture teardown'ında hepsi silinir. Birden çok kullanıcı
    gerektiren testler (ör. "başkasının profiline erişim") bunu birden
    fazla kez çağırabilir.
    """
    created: list[User] = []

    async def _make(display_name: str = "Pytest Test User") -> User:
        user = User(
            email=f"pytest-{uuid.uuid4().hex[:12]}@karavantr-qa.dev",
            display_name=display_name,
            hashed_password="x",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        created.append(user)
        return user

    yield _make

    for user in created:
        await db_session.delete(user)
    if created:
        await db_session.commit()


@pytest_asyncio.fixture
async def make_spot(db_session: AsyncSession) -> AsyncGenerator[Callable[..., Coroutine[None, None, uuid.UUID]], None]:
    """
    `await make_spot(created_by=some_user.id)` - `review_service` testleri
    için minimal (varsayılan passability/amenities) bir spot oluşturur,
    `spot_id`'sini döner. Teardown'da hard-delete eder (spot'a bağlı
    review/check_in satırları `ondelete=CASCADE` ile otomatik temizlenir).
    """
    created: list[uuid.UUID] = []

    async def _make(*, created_by: uuid.UUID | None = None, title: str = "Test Spot") -> uuid.UUID:
        feature = await create_spot(
            db_session,
            data=SpotCreate(
                title=title,
                category=SpotCategory.WILD_CAMPING,
                coordinates=Coordinates(latitude=39.0, longitude=33.0),
                passability=SpotPassabilityCreate(road_type="asphalt"),
                amenities=SpotAmenitiesCreate(),
            ),
            created_by=created_by,
        )
        spot_id = feature.properties.id
        created.append(spot_id)
        return spot_id

    yield _make

    for spot_id in created:
        await db_session.execute(sa_delete(Spot).where(Spot.id == spot_id))
    if created:
        await db_session.commit()


@pytest_asyncio.fixture
async def api_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Gerçek FastAPI uygulamasına ASGI üzerinden (ağ olmadan) istek atan istemci."""
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


@pytest_asyncio.fixture
async def make_check_in(db_session: AsyncSession) -> Callable[..., Coroutine[None, None, CheckIn]]:
    """`await make_check_in(user, spot_id, hours_ago=0)` - geçerlilik penceresi testleri için kayıt ekler.
    Kayıtlar kullanıcı/spot silinince CASCADE ile temizlenir."""

    async def _make(user: User, spot_id: uuid.UUID, hours_ago: float = 0) -> CheckIn:
        row = CheckIn(
            spot_id=spot_id, user_id=user.id, checked_in_at=datetime.now(UTC) - timedelta(hours=hours_ago)
        )
        db_session.add(row)
        await db_session.commit()
        await db_session.refresh(row)
        return row

    return _make
