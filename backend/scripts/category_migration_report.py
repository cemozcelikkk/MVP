"""
Kategori geçişi ön raporu (salt okunur) - `e3a9c5d1f7b4` migration'ını ÇALIŞTIRMADAN
önce hangi eski kaydın nereye gideceğini gösterir. Kurallar ve eşleme tablosu:
app/services/category_migration.py.

    docker exec karavantr_api python -m scripts.category_migration_report

Çıktı:
- `move`   : hizmet noktasına AYNI id ile taşınacak (temiz kayıtlar)
- `review` : kamp verisi taşıdığı için TAŞINMAYACAK, moderatör kuyruğuna düşecek
Migration sonrası çalıştırılırsa hâlâ taşınmamış (inceleme bekleyen) kayıtları listeler.
"""
import asyncio
from collections import Counter

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.services.category_migration import REASON_LABELS, classify_legacy_spots


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = await classify_legacy_spots(db)
    if not rows:
        print("Taşınacak / incelenecek eski kategori kaydı yok.")
        return
    decisions = Counter(row["decision"] for row in rows)
    print(f"{len(rows)} eski restoran/sağlık kaydı: {decisions['move']} taşınacak, {decisions['review']} incelemeye kalacak\n")
    for decision, title in (("move", "TAŞINACAK"), ("review", "İNCELEMEYE KALACAK (taşınmaz)")):
        selected = [r for r in rows if r["decision"] == decision]
        if not selected:
            continue
        print(f"== {title} ({len(selected)})")
        for row in selected:
            reasons = ", ".join(REASON_LABELS.get(r, r) for r in row["reasons"])
            print(f"  {row['id']}  {row['category']:<16} {row['title'][:50]}{'  <- ' + reasons if reasons else ''}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
