# Karavan uygulaması — test kontrol listesi

30 Eylül 2026. Kapsam: geceleme/kurallar, gerçek araç girişi, arama/filtreler, içerik moderasyonu ve değişiklik geçmişi, hesap işlemleri, operasyon kontrolleri, seyahat planı. Önceki değerlendirmedeki 3. madde (işletme/iletişim/tesis bilgileri) ve 4. madde (çevrimdışı kullanım) bu sürüme dahil edilmedi.

## Yerel ortam ve doğrulama

- Arayüz: http://127.0.0.1:5173
- API dokümantasyonu: http://localhost:8000/docs
- Canlılık: `GET /health`; veritabanı hazır olma kontrolü: `GET /health/ready`.
- Migration zinciri: `13c0faa836cf` → `41126d9a82bc` → `00fae9a72c8b` (son sürüm).
- PostgreSQL üzerinde tüm backend testleri: **223 başarılı**. Son koordinat doğrulama düzeltmesinden sonra ilgili 22 test yeniden başarılı. Testler ana veritabanından ayrı, geri yüklenen test veritabanında çalıştırıldı.
- TypeScript ve üretim derlemesi başarılı. Lint hata vermedi; mevcut ExploreHero, ReportStatusModal ve ModerationPanel dosyalarında uyarılar var. Vite büyük harita paketi için boyut uyarısı veriyor.
- Harici arama/rota servisleri otomatik testlerde taklit edildi; canlı sağlayıcı davranışını aşağıdaki manuel adımlarda deneyin.
- Yedek geri yüklemesi doğrulandı: `backups/karavantr-20260930-183918.dump`. Bu yedek yeni migration'lardan **önce** alındı. Ana veritabanını değiştirmeden ayrı veritabanına geri yüklenip migration'lar uygulandı.

## Nokta oluşturma ve düzenleme

1. Normal kullanıcıyla giriş yapın; WC ve çöp kutusunu açarak nokta oluşturun. Detay ve düzenleme formunda değerlerin korunduğunu kontrol edin.
2. “Kural bilgisi biliniyor” seçeneğini açın; ücretsiz seçeneğini kapatın, ücret açıklaması girin. Kamp davranışı iznini kapatın. Kaydetme, tekrar açma ve detay gösterimini deneyin.
3. Ücretsiz seçeneğini tekrar açın: ücret açıklaması temizlenmeli. Bilgisi bilinmeyen eski noktalar ücret/kamp izni alanlarında “Bilinmiyor” göstermeli, ücretsiz filtresine dahil olmamalı.
4. Geceleme izni, maksimum kalış, özel mülk izni, kaynak ve kontrol tarihi girin. Gelecek tarih ve tek başına giriş enlemi/boylamı reddedilmeli. İki koordinatı birlikte boşaltmak giriş bilgisini temizlemeli.
5. Araç giriş koordinatı, yaklaşım açıklaması ve mevsim bilgisini kaydedin. Google Haritalar bağlantısının nokta merkezi yerine girişe yöneldiğini kontrol edin.
6. Oluşturma sırasında giriş/yaklaşım fotoğrafı işaretleyin veya detaydan giriş fotoğrafı yükleyin; etiketi kontrol edin.
7. Başka kullanıcı noktanızı düzenleyememeli. Nokta merkezi koordinatını yalnızca moderatör/admin düzeltebilmeli.

## Keşif ve saha bilgisi

1. Keşif panelinde nokta adı/açıklaması arayın; sonucu seçip haritada ve detayda açın.
2. Şehir/ilçe aramasında bir yer seçin; harita o konuma gitmeli. Arama yalnızca Ara düğmesiyle yapılır; OSM atfı gösterilir.
3. Yakınımda için konum izni verin; mesafeyi değiştirin. İzin reddi durumunda anlaşılır hata olmalı.
4. WC, çöp kutusu, ücretsiz, kamp davranışı ve geceleme filtrelerini tek tek ve birlikte deneyin. Temizle/Uygula davranışını kontrol edin.
5. Check-in sonrasında WC, çöp kutusu, ücret ve kamp davranışı saha doğrulamalarını gönderin; bilginin güncellik değerlendirmesini kontrol edin.

## Moderasyon ve geçmiş

1. Nokta, fotoğraf ve yorum için içerik bildirimi gönderin. Aynı kullanıcının aynı hedef/sebep için ikinci bekleyen bildirimi engellenmeli.
2. Normal kullanıcı moderasyon API'sine erişememeli. Moderatör bekleyen/çözülen/reddedilen listelerini ve sayfalamayı deneyebilmeli.
3. Bir noktanın konumunu/bilgisini düzeltip bildirimi açıklamayla sonuçlandırın; değişiklik geçmişinde önce/sonra değerleri görünmeli. Eski kayıtlar için geçmiş geriye dönük üretilmez.
4. Fotoğraf/yorum gizleme sonrası herkese açık detayları yeniden açın. Gizlenen yorum puan ortalamasından çıkarılmalı; sonuçlanmış bildirim tekrar işlenmemeli.

## Hesap işlemleri

1. Şifremi Unuttum akışını bilinen ve bilinmeyen e-posta ile deneyin; yanıt kullanıcı varlığını açıklamamalı.
2. Geliştirme modunda `backend/.mail-outbox` altındaki `.eml` dosyasından bağlantıyı açın. Yeni şifreyle giriş yapın; eski oturum geçersizleşmeli. Kullanılmış ve süresi dolmuş bağlantı reddedilmeli.
3. Hesap menüsünden doğrulama bağlantısı isteyin; bağlantıyı açıp doğrulamayı gönderin. E-posta doğrulanmış durumu güncellenmeli.
4. Yalnızca deneme hesabı üzerinde hesap silmeyi deneyin: şifre ve `HESABIMI SİL` metni gerekli. Kişisel listeler ve kullanıcı kayıtları kaldırılır; topluluğa ait noktalar/fotoğraflar kullanıcıdan ayrılarak korunur.
5. Çıkış sonrası favoriler ve seyahat planı verilerinin diğer oturumlara taşınmadığını kontrol edin.

## Seyahat planı

1. Hesap menüsünden özel plan oluşturun; nokta detayından plana durak ekleyin. Tarih ve kişisel not kaydedin, durak sırasını değiştirin; yeniden açınca korunduğunu kontrol edin.
2. 2–10 durak için rota hesaplayın; mesafe, yaklaşık sürüş süresi, harita çizgisi ve rota çevresindeki noktaları inceleyin.
3. Yakındaki bir noktayı plana ekleyin; rota yeniden hesaplanabilmeli. Durak çıkarma, plan silme onayı ve başka kullanıcının planına erişememe davranışını kontrol edin.
4. Rota **standart araç rotasıdır**; karavan yüksekliği/ağırlığı/yol kısıtlarını hesaplamaz. Nokta düzeyindeki mevcut araç uyumluluğu kontrolü ayrıca gösterilir.

## İşletim ayarları

`backend/.env.example` yeni ayarları içerir. Yerel geliştirmede `MAIL_BACKEND=file`; bağlantılar `.eml` dosyalarına yazılır ve gerçek e-posta gönderilmez. Üretimde `MAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS=true` ve gerçek `FRONTEND_URL` tanımlanmalıdır. Dosya e-posta modu üretimde kullanılamaz.

Arama `GEOCODER_URL`/`GEOCODER_USER_AGENT`, rota `ROUTING_URL` üzerinden yapılandırılır. Varsayılan Nominatim ve OSRM adresleri geliştirme içindir; üretim kapasitesine uygun sağlayıcı seçilmelidir. Yer araması 7 gün, rota 6 saat önbelleğe alınır. Nominatim istekleri ortak veritabanı üzerinden saniyede bir ile sınırlanır. Sağlayıcı politikaları: [Nominatim](https://operations.osmfoundation.org/policies/nominatim/), [OSRM API](https://project-osrm.org/docs/v5.24.0/api/).

İstek limitleri PostgreSQL'de paylaşılır: varsayılan dakikada 180 okuma, 30 yazma, 10 kimlik işlemi. Aşıldığında 429 ve Retry-After döner. Proxy kullanıyorsanız yalnızca güvenilen proxy'den gelen istemci IP bilgisini kabul edecek şekilde Uvicorn/proxy ayarlarını yapın. Üretimde ayrı SECRET_KEY, gerçek CORS origin'leri ve HTTPS yapılandırın. İstek kayıtları kimlik, yol, durum ve süreyi içerir; sorgu metni ve parola gövdesi kaydedilmez.

Yedek almak ve mevcut veritabanına dokunmadan geri yükleme denemek için:

```powershell
.\scripts\backup-database.ps1
.\scripts\verify-backup.ps1 -BackupPath C:\MVP\backups\karavantr-20260930-183918.dump
```

Geri yükleme script'i benzersiz isimli ayrı bir veritabanı oluşturup inceleme için bırakır. Veritabanı yedeğine ek olarak yerel `backend/uploads` dosyaları da ayrıca yedeklenmelidir. Migration downgrade yeni topluluk doğrulama enum değerlerini korur; eski uygulama sürümüne dönmeden önce yeni değerlerle yazılmış kayıtların uyumluluğunu kontrol edin.
