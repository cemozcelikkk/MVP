"""
Uygulama genelinde kullanılan ayarlar.

Pydantic Settings üzerinden .env dosyasından okunur. Tüm modüller
`settings` singleton'ını import ederek merkezi konfigürasyona erişir.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "KaravanTR API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Async engine (hem uygulama çalışma zamanı hem de Alembic migration'ları
    # için). Alembic tarafında ayrı bir sync sürücü/DSN'e ihtiyaç yok; env.py
    # `run_sync` ile bu async engine'i migration çalıştırırken kullanır.
    DATABASE_URL: str = "postgresql+asyncpg://karavantr:karavantr@localhost:5432/karavantr_db"

    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # /spots/bbox gibi mekansal endpoint'lerde tek istekte dönebilecek
    # azami kayıt sayısı. Harita çok fazla noktayı içerdiğinde istemciyi
    # ve veritabanını korumak için kullanılır.
    SPOTS_BBOX_MAX_LIMIT: int = 500
    SPOTS_BBOX_DEFAULT_LIMIT: int = 200

    # Web frontend (Vite dev server) tarayıcıdan doğrudan bu API'ye istek
    # attığı için CORS izin listesi gerekiyor. Vite'ın varsayılan portu
    # 5173'tür; 5173 doluysa Vite otomatik 5174'e geçer (bu yüzden 5174 de
    # listede). 4173 `vite preview`, 3000 alternatif bir dev port ihtimaline
    # karşı eklendi. `*` KASITLI OLARAK yok. Bu varsayılanlar YEREL GELİŞTİRME
    # içindir; üretimde `.env`'de CORS_ORIGINS'i gerçek alan adıyla, JSON dizisi
    # olarak tanımlayın (bkz. .env.example) - env değeri bu listeyi tamamen değiştirir.
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://localhost:3000",
        "https://mvp-k88h7hbns-cemozcelik295-9714s-projects.vercel.app",
    ]
    # Vercel her deploy'a yeni bir URL verir (mvp-<hash>-<takım>.vercel.app,
    # mvp-git-<branch>-<takım>.vercel.app); listeye tek tek eklemek yerine bu
    # projenin önizleme adreslerini regex'le kabul ediyoruz. Takım soneki
    # sadece bu Vercel hesabına verildiği için başkası bu kalıba uyan bir
    # adres alamaz. Boş string verilirse regex devre dışı kalır.
    CORS_ORIGIN_REGEX: str | None = (
        r"https://mvp-[a-z0-9-]+-cemozcelik295-9714s-projects\.vercel\.app"
    )

    ROUTING_URL: str = "https://router.project-osrm.org/route/v1/driving"
    GEOCODER_URL: str = "https://nominatim.openstreetmap.org/search"
    GEOCODER_USER_AGENT: str = "KaravanTR/0.1 (local development)"

    FRONTEND_URL: str = "http://localhost:5173"
    MAIL_BACKEND: Literal["file", "smtp"] = "file"
    MAIL_OUTBOX_DIR: Path = Path(".mail-outbox")
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@karavantr.local"
    SMTP_STARTTLS: bool = True
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_READ_PER_MINUTE: int = 180
    RATE_LIMIT_WRITE_PER_MINUTE: int = 30
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10

    # --- Medya / Depolama ---
    # "local": backend/uploads/ altına yazar (geliştirme ortamı varsayılanı).
    # "s3": AWS S3 veya Cloudflare R2 (S3 uyumlu API) - bkz. app/services/storage/.
    # Hangisi seçilirse seçilsin, DB'ye kaydedilen storage_url/thumbnail_url
    # zaten tam bir URL olduğu için backend'in geri kalanı hangi adaptörün
    # aktif olduğunu bilmek zorunda değildir (bkz. services/storage/get_storage()).
    STORAGE_BACKEND: Literal["local", "s3"] = "local"

    UPLOAD_DIR: Path = Path("uploads")
    MAX_UPLOAD_SIZE_MB: int = 5

    # STORAGE_BACKEND="s3" değilse hiçbiri zorunlu değildir (None kalabilir).
    S3_ENDPOINT_URL: str | None = None  # R2 için: https://<account_id>.r2.cloudflarestorage.com
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    S3_BUCKET_NAME: str | None = None
    S3_REGION_NAME: str | None = "auto"  # R2 "auto" kabul eder; gerçek AWS S3'te ör. "eu-central-1"
    # Bucket'a bir CDN/custom domain bağlıysa (ör. cdn.karavantr.com), public
    # URL'ler doğrudan bunun üzerinden üretilir; verilmezse endpoint/bucket'tan
    # path-style bir URL üretilir (bkz. S3Storage._public_url).
    S3_PUBLIC_CUSTOM_DOMAIN: str | None = None

    @model_validator(mode="after")
    def validate_production(self):
        if self.ENVIRONMENT != "production":
            return self
        if len(self.SECRET_KEY) < 48 or self.SECRET_KEY == "change-me-in-production":
            raise ValueError("Üretimde en az 48 karakterlik bağımsız SECRET_KEY gerekli.")
        database = urlparse(self.DATABASE_URL)
        if not database.password or database.password in {"karavantr", "postgres", "password"}:
            raise ValueError("Üretim veritabanı parolası varsayılan olamaz.")
        frontend = urlparse(self.FRONTEND_URL)
        if (
            frontend.scheme != "https"
            or not frontend.hostname
            or frontend.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("Üretimde FRONTEND_URL gerçek bir HTTPS origin olmalı.")
        if frontend.path not in {"", "/"} or frontend.query or frontend.fragment:
            raise ValueError("FRONTEND_URL yalnızca origin içermeli.")
        origin = self.FRONTEND_URL.rstrip("/")
        if (
            not self.CORS_ORIGINS
            or origin not in self.CORS_ORIGINS
            or any(
                urlparse(value).scheme != "https"
                or not urlparse(value).hostname
                or urlparse(value).hostname in {"localhost", "127.0.0.1"}
                or urlparse(value).path
                or urlparse(value).query
                or urlparse(value).fragment
                for value in self.CORS_ORIGINS
            )
        ):
            raise ValueError(
                "Üretim CORS listesi HTTPS origin'lerden oluşmalı ve FRONTEND_URL içermeli."
            )
        if self.MAIL_BACKEND != "smtp" or not self.SMTP_HOST or not self.SMTP_STARTTLS:
            raise ValueError("Üretimde TLS açık SMTP yapılandırması gerekli.")
        if any(
            "REPLACE_WITH" in value
            for value in (
                self.SECRET_KEY,
                self.SMTP_HOST,
                self.SMTP_USERNAME or "",
                self.SMTP_PASSWORD or "",
            )
        ):
            raise ValueError("Üretim ayarlarındaki örnek değerler değiştirilmelidir.")
        if self.SMTP_FROM.endswith("@karavantr.local") or "@" not in self.SMTP_FROM:
            raise ValueError("Üretimde gerçek SMTP_FROM adresi gerekli.")
        if self.SMTP_USERNAME and not self.SMTP_PASSWORD:
            raise ValueError("SMTP_USERNAME için SMTP_PASSWORD gerekli.")
        if self.SMTP_HOST == "smtp.gmail.com":
            if (
                not self.SMTP_USERNAME
                or self.SMTP_FROM != self.SMTP_USERNAME
                or self.SMTP_PORT != 587
            ):
                raise ValueError("Gmail için aynı gönderici/kullanıcı adresi ve 587 portu gerekli.")
            self.SMTP_PASSWORD = (self.SMTP_PASSWORD or "").replace(" ", "")
            if len(self.SMTP_PASSWORD) != 16:
                raise ValueError("Gmail için 16 karakterlik uygulama şifresi gerekli.")
        if not self.RATE_LIMIT_ENABLED:
            raise ValueError("Üretimde istek sınırları açık olmalı.")
        if self.STORAGE_BACKEND == "s3" and not all(
            (
                self.S3_ACCESS_KEY_ID,
                self.S3_SECRET_ACCESS_KEY,
                self.S3_BUCKET_NAME,
            )
        ):
            raise ValueError("S3 depolaması için kimlik ve bucket ayarları gerekli.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
