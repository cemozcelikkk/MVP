"""
Alembic migration ortamı — async SQLAlchemy 2.0 engine ile çalışır.

`DATABASE_URL` (asyncpg) doğrudan kullanılır; ayrı bir senkron
sürücüye/DSN'e ihtiyaç yoktur. Migration'lar, async engine üzerinden
açılan bir bağlantının `run_sync()` metodu ile senkron Alembic
context'ine köprülenerek çalıştırılır (SQLAlchemy'nin resmi
"asyncio + Alembic" deseni).
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# --- Uygulama tarafı importlar ---
# `app.models` paketi tüm ORM modellerini içe aktarır; bu satır olmadan
# Base.metadata boş kalır ve autogenerate hiçbir tablo göremez.
from app.core.config import settings
from app.core.database import Base
from app.models import *  # noqa: F401,F403

# Alembic Config nesnesi; .ini dosyasındaki değerlere erişim sağlar.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini'de sqlalchemy.url kasıtlı boş; tek doğruluk kaynağı olan
# uygulama ayarlarından (.env) enjekte ediyoruz.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    PostGIS/tiger_geocoder/postgis_topology uzantıları kendi tablolarını
    `public`, `tiger`, `tiger_data`, `topology` şemalarına ekler. Bunlar
    bizim ORM modellerimizde tanımlı olmadığından autogenerate, onları
    "silinmesi gereken tablo" sanıp DROP TABLE üretebilir. `do_run_migrations`
    içinde search_path'i `public`'e sabitlesek de (esas savunma hattı),
    `spatial_ref_sys` her koşulda `public` şemasında kaldığı için burada
    ayrıca eleniyor.
    """
    schema = getattr(object, "schema", None)
    if schema in {"tiger", "tiger_data", "topology"}:
        return False
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    return True


def run_migrations_offline() -> None:
    """`--sql` bayrağıyla, DB bağlantısı açmadan SQL script üretmek için."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Bu veritabanının search_path'i (postgis_tiger_geocoder/postgis_topology
    # kurulumundan dolayı) "$user", public, topology, tiger şeklindedir.
    # SQLAlchemy'nin şemasız (schema=None) tablo reflection'ı bu durumda
    # search_path'teki TÜM şemalardaki tabloları döndürüyor; bu da
    # autogenerate'in tiger/topology'nin kendi tablolarını (state, county,
    # place, ...) yanlışlıkla "silinecek tablo" sanmasına yol açıyor.
    # Migration session'ı için search_path'i sadece `public` ile
    # sınırlandırarak bu sızıntıyı kaynağında kapatıyoruz.
    #
    # ÖNEMLİ: Bu execute() çağrısı SQLAlchemy 2.0'ın "autobegin" davranışıyla
    # bağlantıda örtük bir transaction başlatır. Hemen commit etmezsek,
    # aşağıdaki context.begin_transaction() bunu var olan bir transaction
    # sanıp SAVEPOINT'e düşer; asıl (dıştaki) transaction hiç commit
    # edilmeden bağlantı kapanır ve TÜM migration sessizce rollback olur
    # (hata vermeden!). Bu yüzden search_path ayarını kendi başına
    # commit'liyoruz ki asıl migration transaction'ı temiz başlasın.
    connection.execute(text("SET search_path TO public"))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        # PostGIS Geometry sütunlarındaki ince tip farklarını (ör. srid)
        # da yakalayabilmek için tip karşılaştırmasını açıyoruz.
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
