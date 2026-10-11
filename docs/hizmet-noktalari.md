# Hizmet noktaları ve kategori geçişi

10 Ekim 2026. Kapsam: kamp/karavan noktaları ile çevresel hizmet noktalarının (restoran, sağlık, WC, duş) ayrılması, "Yakınımdakiler", OpenStreetMap verisi ve eski kayıtların geçişi.

## Veri modeli

| Tablo | İçerik |
|---|---|
| `spots` | Yalnızca kamp/karavan noktaları (+ yeni eklemeye kapalı eski `HOTEL_POOL`). Araç uyumu, 7 boyutlu değerlendirme, check-in, canlı bildirim burada kalır. |
| `service_points` | Restoran (et/balık/diğer), hastane, sağlık ocağı, WC, duş. Gruba göre: restoranda ad zorunlu; sağlıkta ad opsiyonel; WC/duşta ücret + kullanılabilirlik + son güncelleme. `osm_id` OSM nesnesine bağlantıdır. |
| `service_point_reviews` | Yalnızca Yeme & İçme: 1–5 yıldız + yorum, kullanıcı başına tek aktif kayıt. |
| `service_point_status_updates` | WC/duş durum tarihçesi. |
| `service_point_confirmations` | "Hâlâ burada / hizmet veriyor" teyidi (kullanıcı başına nokta başına 24 saatte bir). |
| `service_point_reports` | Hatalı konum / kapanmış / mükerrer bildirimleri (moderatör kuyruğu). |
| `osm_pois`, `osm_tiles` | OpenStreetMap önbelleği (TTL 7 gün). KaravanTR kaydı değildir. |

Kural ihlalleri hem API'de (422) hem veritabanı CHECK kısıtlarında engellenir: sağlıkta ve WC/duşta puan olamaz, restoran dışında ücret/durum alanı dolu olamaz, restoranın adı boş olamaz.

## Eski kategorilerin eşlenmesi

| Eski `spots.category` | Yeni yer | Değerlendirmeler |
|---|---|---|
| CAMPING | `spots` (değişmez) | değişmez |
| HOTEL_POOL | `spots` (değişmez, yeni eklemeye kapalı, salt okunur) | değişmez |
| FISH_RESTAURANT / MEAT_RESTAURANT | `service_points`, aynı id | genel puan + yorum restoran değerlendirmesine kopyalanır |
| HOSPITAL / HEALTH_CENTER | `service_points`, aynı id | sağlıkta değerlendirme yok |

**Belirsiz kayıtlar taşınmaz.** Restoran/sağlık kategorisinde olup kamp verisi taşıyan kayıt (check-in, canlı bildirim, saha doğrulaması, fotoğraf, kayıtlı liste, 7 boyutlu değerlendirme, sağlıkta herhangi bir değerlendirme, geceleme/giriş bilgisi, kamp olanakları, araç kısıtları, bekleyen içerik bildirimi) `spots`'ta kalır ve Moderasyon → **Kategori İnceleme** sekmesine düşer. Moderatör: *Kamp alanı olarak tut* / *Hizmet noktasına taşı* / *Olduğu gibi bırak*.

Hiçbir satır fiziksel olarak silinmez: taşınan spot soft-delete edilir ve `moved_to_service_points` ile işaretlenir; `reviews`, `check_ins`, fotoğraflar yerinde kalır. Kurallar: `backend/app/services/category_migration.py` (migration aynı kuralların sabitlenmiş kopyasını taşır; test ikisinin aynı olduğunu doğrular).

## Yayın prosedürü

1. Yedek alın (`docs/deployment/pilot-production.md`).
2. Ön raporu alın - hangi kayıt taşınacak, hangisi incelemeye kalacak:
   `docker exec karavantr_api python -m scripts.category_migration_report`
3. Migration: `alembic upgrade head` (`17f9e97a4d17` → `e3a9c5d1f7b4` → `f1b7d3a9c2e5` → `a4c8e2f6b1d9`).
   `f1b7d3a9c2e5` PostgreSQL `uuid-ossp` eklentisini oluşturur; veritabanı kullanıcısının buna yetkisi olmalı (PG13+ veritabanı sahibi için yeterli).
4. Moderasyon → Kategori İnceleme kuyruğunu boşaltın.
5. Geri dönüş: `alembic downgrade 17f9e97a4d17` taşınan spot'ları geri açar ve inceleme işaretlerini kaldırır; migration sonrası eklenen hizmet noktaları (WC/duş vb.) kaybolur - downgrade öncesi yedek alın.

## API değişiklikleri

Korunanlar: `/spots` uçlarının yanıt şekilleri, `/spots/sync` (taşınan kayıtlar `deleted_ids` içinde gelir - eski istemciler onları temiz biçimde düşürür), kamp değerlendirme/check-in/canlı bildirim uçları.

Bilinçli değişiklikler:
- `POST /spots` ve kategori değiştiren `PATCH /spots/{id}` yalnızca `CAMPING` kabul eder; diğerleri 422 (mesaj `/service-points`'e yönlendirir).
- `GET /spots?category=HOSPITAL` vb. artık yalnızca incelemeye kalmış eski kayıtları döndürür.

Yeni uçlar (`/api/v1`):
- `GET /service-points` (bbox, `category`, `group`) ve `GET /service-points/nearby` (`latitude`, `longitude`, `radius_m` ≤ 20 km; yakından uzağa, `distance_m`). Yanıtta `external_status` (`ok`, `partial`, `unavailable`, `too_wide`, `disabled`, `not_needed`) ve OSM atfı.
- `POST /service-points`, `GET|PATCH|DELETE /service-points/{id}`, `GET /service-points/name-suggestion`.
- Yorumlar: `GET|POST /service-points/{id}/reviews`, `GET .../reviews/me`, `PATCH|DELETE .../reviews/{review_id}`.
- `POST /service-points/{id}/status`, `GET .../status-history`, `POST .../confirm`, `POST .../reports`.
- Moderatör: `PATCH /service-points/{id}/verify`, `GET /moderation/service-point-reports`, `POST .../{id}/resolve`, `GET /moderation/category-review`, `POST /moderation/category-review/{spot_id}`.
- 409 yanıtı mükerrer kayıtta `existing_id` taşır.

## OpenStreetMap verisi

- Yeme & İçme, sağlık, WC, duş: bakılan bölge için 0.05° hücrelerle Overpass'tan, arka planda çekilir; harita isteği beklemez (ilk yüklemede yanıt `partial`, istemci ~50 sn boyunca artan aralıklarla yeniden sorar). Sağlık ayrıca haftalık `basemap_pois` içe aktarımından da gelir (doluysa hücre çekilmemiş bölgelerde de görünür; boş olsa da sağlık çalışır).
- Kullanım politikası: hücre başına 7 günde bir istek, sunucu genelinde dakikada 6 istek, süreç içinde tek eşzamanlı istek, hata sonrası 15 dk bekleme, `OVERPASS_USER_AGENT` ile tanıtım. Yanıtlarda ve detayda "© OpenStreetMap katkıcıları (ODbL)" atfı.
- OSM verisi doğrulanmış/açık gibi sunulmaz ("harita verisi" etiketi, kullanılabilirlik bilgisi OSM'den alınmaz). Bir kullanıcı puan/durum/teyit/bildirim verdiğinde nokta aynı id ile `service_points`'e bağlanır.
- Mükerrer önleme: OSM kimliği; aynı kategori ailesi + 40 m + ad benzerliği.
- Kaynak erişilemezse KaravanTR kayıtları ve önbellek çalışmaya devam eder.

## Kötüye kullanım önlemleri

HTTP katmanındaki IP başına sınıra ek olarak hesap başına: günde 30 nokta, 30 değerlendirme, 20 bildirim, 100 teyit; saatte 60 durum güncellemesi ve aynı noktada 10 dakikada en fazla 3 durum değişikliği (429 + `Retry-After`). Konum düzeltme ve onay yalnızca moderatörde; harici noktalar silinemez, bildirimle kaldırılır.

## Üretim ayarları

`OVERPASS_USER_AGENT` gerçek uygulama adı + iletişim adresi olmalı. İlgili diğer ayarlar `backend/app/core/config.py` içinde `OSM_*`, `OVERPASS_*`, `SERVICE_POINT_QUOTAS_ENABLED`.

## Production teşhisi ve sorun giderme

Sunucuda, API konteynerinin içinden (Cloudflare devre dışı) zinciri tek komutla kontrol edin:

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml exec -T api python - < deploy/check-nearby.py
```

Migration sürümü, sağlık verisi, OSM önbelleği, sunucudan Overpass'a çıkış ve gerçek "yakınımdakiler" yanıtını gösterir; sonunda yapılması gerekenleri listeler.

- **Gerçek istemci IP'si:** Caddy, Cloudflare (ve özel ağdaki bir proxy) arkasında `CF-Connecting-IP`'yi güvenilir kabul eder (`frontend/deploy/Caddyfile`). Bu olmadan tüm kullanıcılar aynı Cloudflare IP'sini paylaşır ve IP başına istek sınırı (dakikada 180 okuma) herkes için ortak dolar → 429.
- **Cloudflare güvenlik ayarları:** "I'm Under Attack" modu veya `/api/*` yollarına uygulanan challenge/Bot Fight Mode, tarayıcının arka plan isteklerine (fetch) 403 HTML döndürür. Cloudflare → Security → Events'te `/api/v1/service-points` engelleniyor mu bakın.
- **Bakım betikleri** production imajında: `python -m scripts.import_basemap_pois` (Türkiye geneli sağlık/akaryakıt/eczane, uzun sürer), `python -m scripts.category_migration_report`, `python -m scripts.fetch_osm_places --lat .. --lng .. --radius ..`.
