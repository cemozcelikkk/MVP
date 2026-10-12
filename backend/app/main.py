"""FastAPI uygulama giriş noktası."""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.http_middleware import request_middleware

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # OSM önbelleği yenileyicisi: Overpass'ın geçici hatalarında başarısız kalan hücreleri
    # kullanıcı beklemeden tamamlar (bkz. app/services/osm_refresher.py). Birden çok worker
    # olsa da DB advisory lock sayesinde aynı anda tek süreç iş yapar.
    task = None
    if settings.OSM_EXTERNAL_ENABLED and settings.OSM_REFRESH_ENABLED:
        from app.services.osm_refresher import run_forever

        task = asyncio.create_task(run_forever())
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.middleware("http")(request_middleware)

# Web frontend (frontend/, Vite dev server) tarayıcıdan doğrudan bu API'ye
# istek attığı için gerekli - aksi halde tarayıcı cross-origin isteği
# sessizce engeller. Sadece geliştirme origin'lerine izin verilir
# (bkz. settings.CORS_ORIGINS); credentials=True JWT'yi Authorization
# header'ıyla taşıdığımız için gerekli değil ama ileride cookie-tabanlı
# bir auth'a geçilirse hazır olsun diye açık bırakıldı.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

# Spot fotoğrafları için yerel statik dosya servisi (geliştirme ortamı).
# photo_service.save_spot_photo() dosyaları settings.UPLOAD_DIR'e yazar ve
# DB'ye "/uploads/{filename}" göreli URL'sini kaydeder; bu mount o URL'yi
# gerçekten servis eden taraf. Dizin uygulama ilk kez fotoğraf almadan önce
# de var olsun diye burada da oluşturuluyor (StaticFiles, olmayan bir
# dizinle mount edilirse hata verir).
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="uploads")


@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.get("/health/ready")
async def readiness():
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}
