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

API dokümantasyonu: http://localhost:8000/docs
