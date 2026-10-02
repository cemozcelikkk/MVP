# Geliştirme ortamı imajı: Windows'taki Smart App Control'ün native Python
# uzantılarını (pydantic_core vb.) engellemesi nedeniyle backend artık
# doğrudan Windows'ta değil, bu Linux container'ı içinde çalıştırılıyor.
FROM python:3.11-slim

# PostGIS/GeoAlchemy2 ile çalışan native Python paketleri (asyncpg, shapely,
# Pillow) için derleme araçları ve coğrafi kütüphaneler - slim imaj bunları
# içermez. `curl`, aşağıdaki HEALTHCHECK için gerekli.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgeos-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Önce sadece bağımlılık listesi kopyalanıp kuruluyor ki sadece uygulama
# kodu değiştiğinde (bağımlılıklar aynı kalırken) bu katman yeniden
# kullanılsın (Docker layer cache). requirements.txt, pyproject.toml ile
# senkron tutulur (bkz. dosyanın kendi başlığı).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Geliştirme ortamında bu kod docker-compose.yml'deki bind mount
# (./backend:/app) ile host'tan canlı olarak üzerine biner; buradaki COPY
# sadece imajın tek başına (mount'suz) da çalışabilmesini sağlar.
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
