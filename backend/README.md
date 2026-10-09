# KaravanTR — Backend

Türkiye pazarına özel karavan/off-grid topluluk platformu için FastAPI + PostgreSQL/PostGIS backend'i.

## Hızlı Başlangıç

```bash
cp .env.example .env
docker compose up -d          # PostGIS veritabanını ayağa kaldırır
pip install -e ".[dev]"
alembic upgrade head           # migration'ları uygular
python -m app.db.seed          # örnek Türkiye verisini basar
uvicorn app.main:app --reload
```

OpenStreetMap'ten çevredeki hastane, sağlık ocağı, balık/et restoranı ve otel/havuzları içe aktarmak için
(tekrar çalıştırmak güvenli; önce `--dry-run` ile özet görülebilir):

```bash
python -m scripts.fetch_osm_places --lat 37.0 --lng 35.32 --radius 5000 [--dry-run]
```

API dokümantasyonu: http://localhost:8000/docs
