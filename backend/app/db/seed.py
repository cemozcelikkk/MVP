"""
Geliştirme ortamı için örnek veri tohumlama betiği.

Kullanım (backend/ dizininden, .venv aktifken):
    python -m app.db.seed

Türkiye'den 4 farklı kategoriyi temsil eden, amenities + passability +
dynamic_status alanları dolu zengin örnek spot'lar ekler. Idempotent'tir:
aynı başlığa sahip bir kayıt zaten varsa atlanır, böylece betik yanlışlıkla
birden çok kez çalıştırılsa da veritabanı şişmez.
"""
import asyncio
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.enums import (
    CaravanType,
    ClearanceRequired,
    CrowdLevel,
    PoliceInterventionStatus,
    RoadType,
    SpotCategory,
    UserRole,
)
from app.models.spot import Spot
from app.models.user import User
from app.schemas.common import Coordinates
from app.schemas.dynamic_status import DynamicStatusCreate
from app.schemas.spot import SpotCreate
from app.schemas.spot_amenities import SpotAmenitiesCreate
from app.schemas.spot_passability import SpotPassabilityCreate
from app.services.spot_service import add_dynamic_status, create_spot

# Geliştirme ortamı için sabit bir moderatör/admin hesabı. Şifre kasıtlı
# olarak basit tutuldu - bu SADECE yerel/dev veritabanında var, üretimde
# seed.py hiç çalıştırılmamalı.
ADMIN_EMAIL = "admin@karavantr.com"
ADMIN_PASSWORD = "admin123456"

SEED_ENTRIES: list[dict] = [
    {
        "spot": SpotCreate(
            title="Kaş Sahil Kenarı Vahşi Kamp",
            description=(
                "Akdeniz'e sıfır, çakıllı bir koyda gölgesiz vahşi kamp alanı. "
                "Tekne turlarının kalktığı iskeleye yürüme mesafesinde."
            ),
            category=SpotCategory.WILD_CAMPING,
            altitude=15,
            coordinates=Coordinates(latitude=36.1964, longitude=29.6382),
            passability=SpotPassabilityCreate(
                road_type=RoadType.GRAVEL,
                max_vehicle_length=7.5,
                clearance_required=ClearanceRequired.STANDARD,
                caravan_types_allowed=[CaravanType.CAMPERVAN, CaravanType.MOTORHOME],
                steep_incline=False,
            ),
            amenities=SpotAmenitiesCreate(
                fresh_water_thread=False,
                black_water=False,
                grey_water=False,
                electricity_220v=False,
                gsm_signals={"turkcell": "good", "vodafone": "medium", "turk_telekom": "poor"},
            ),
        ),
        "status": DynamicStatusCreate(
            police_intervention=PoliceInterventionStatus.NONE,
            crowd_level=CrowdLevel.MEDIUM,
            note="Yaz aylarında hafta sonları hızlı doluyor; erken gelin.",
        ),
    },
    {
        "spot": SpotCreate(
            title="Akyaka Çiftlik Konaklaması",
            description=(
                "Sedir Dağı eteklerinde, zeytinlik içinde tam donanımlı çiftlik "
                "konaklaması. Ev yapımı süt ürünleri satın alınabilir."
            ),
            category=SpotCategory.FARM_STAY,
            altitude=5,
            coordinates=Coordinates(latitude=37.0533, longitude=28.3269),
            passability=SpotPassabilityCreate(
                road_type=RoadType.ASPHALT,
                max_vehicle_length=9.0,
                clearance_required=ClearanceRequired.LOW,
                caravan_types_allowed=[
                    CaravanType.CARAVAN,
                    CaravanType.MOTORHOME,
                    CaravanType.CAMPERVAN,
                    CaravanType.TENT_TRAILER,
                ],
                steep_incline=False,
            ),
            amenities=SpotAmenitiesCreate(
                fresh_water_thread=True,
                black_water=True,
                grey_water=True,
                electricity_220v=True,
                gsm_signals={"turkcell": "good", "vodafone": "good", "turk_telekom": "good"},
            ),
        ),
        "status": DynamicStatusCreate(
            police_intervention=PoliceInterventionStatus.NONE,
            crowd_level=CrowdLevel.LOW,
        ),
    },
    {
        "spot": SpotCreate(
            title="Uçhisar Kapadokya Manzara Noktası",
            description=(
                "Peri bacalarına ve balon manzarasına hakim, arazi aracı gerektiren "
                "yüksek rakımlı vahşi kamp alanı. Sabah balon kalkışları buradan izlenir."
            ),
            category=SpotCategory.WILD_CAMPING,
            altitude=1300,
            coordinates=Coordinates(latitude=38.6431, longitude=34.8306),
            passability=SpotPassabilityCreate(
                road_type=RoadType.DIRT,
                max_vehicle_length=6.0,
                clearance_required=ClearanceRequired.HIGH_4X4,
                caravan_types_allowed=[CaravanType.CAMPERVAN, CaravanType.TRUCK_CAMPER],
                steep_incline=True,
            ),
            amenities=SpotAmenitiesCreate(
                fresh_water_thread=False,
                black_water=False,
                grey_water=False,
                electricity_220v=False,
                gsm_signals={"turkcell": "medium", "vodafone": "poor", "turk_telekom": "none"},
            ),
        ),
        "status": DynamicStatusCreate(
            police_intervention=PoliceInterventionStatus.WARNING,
            crowd_level=CrowdLevel.HIGH,
            note="Hafta sonu yoğun; jandarma gece 23:00'ten sonra sessizlik uyarısı yapabiliyor.",
        ),
    },
    {
        "spot": SpotCreate(
            title="Datça Yarımadası Sanistasyon Noktası",
            description="Belediyeye ait, sadece gri/siyah su boşaltımı için düzenlenmiş istasyon.",
            category=SpotCategory.SANISTATION_ONLY,
            altitude=20,
            coordinates=Coordinates(latitude=36.7028, longitude=27.6889),
            passability=SpotPassabilityCreate(
                road_type=RoadType.ASPHALT,
                max_vehicle_length=None,
                clearance_required=ClearanceRequired.LOW,
                caravan_types_allowed=[CaravanType.CARAVAN, CaravanType.MOTORHOME, CaravanType.CAMPERVAN],
                steep_incline=False,
            ),
            amenities=SpotAmenitiesCreate(
                fresh_water_thread=True,
                black_water=True,
                grey_water=True,
                electricity_220v=False,
                gsm_signals={"turkcell": "good", "vodafone": "good", "turk_telekom": "medium"},
            ),
        ),
        "status": DynamicStatusCreate(
            police_intervention=PoliceInterventionStatus.NONE,
            crowd_level=CrowdLevel.EMPTY,
        ),
    },
]


async def seed_admin_user(db) -> None:
    existing = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
    if existing is not None:
        print(f"↷ Atlandı (zaten var): {ADMIN_EMAIL}")
        return

    admin = User(
        email=ADMIN_EMAIL,
        display_name="KaravanTR Moderatör",
        hashed_password=hash_password(ADMIN_PASSWORD),
        role=UserRole.ADMIN,
    )
    db.add(admin)
    await db.commit()
    print(f"✓ Eklendi: {ADMIN_EMAIL} (ADMIN, şifre: {ADMIN_PASSWORD})")


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        await seed_admin_user(db)

        for entry in SEED_ENTRIES:
            spot_data: SpotCreate = entry["spot"]

            existing = await db.scalar(select(Spot).where(Spot.title == spot_data.title))
            if existing is not None:
                print(f"↷ Atlandı (zaten var): {spot_data.title}")
                continue

            spot = await create_spot(db, data=spot_data)
            await add_dynamic_status(db, spot_id=spot.id, data=entry["status"])
            print(f"✓ Eklendi: {spot_data.title} ({spot.id})")


if __name__ == "__main__":
    # Windows konsolları varsayılan olarak cp1254/cp1252 gibi kod sayfaları
    # kullanabilir ve "✓"/"↷" gibi karakterleri basamayabilir; bu betiği
    # nereden çalıştırılırsa çalıştırılsın güvenli hale getiriyoruz.
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(seed())
