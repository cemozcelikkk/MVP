# Pilot yayın hazırlığı

Bu paket Docker Compose çalıştırabilen tek sunucu için hazırlandı. Gerçek hosting, alan adı ve Gmail gönderici hesabı henüz verilmediği için internet yayını ve gerçek SMTP gönderimi yapılmadı. Mevcut geliştirme veritabanından bağımsız `karavantr-pilot` projesi ve volume'ları kullanılır; geliştirme verileri kendiliğinden taşınmaz.

30 Eylül 2026 doğrulama sonucu: **239 backend testi başarılı**. Üretim frontend/backend imajları derlendi; Python bağımlılık kontrolü temiz. Ayrı `karavantr-smoke` ortamında migration sıfırdan son sürüme ilerledi; proxy üzerinden kayıt, giriş, nokta ekleme/düzenleme ve giriş fotoğrafı yükleme/servis etme geçti. API yeniden başlatıldıktan sonra fotoğraf servis edildi. `backup-20260930T165210Z-1` yedeğinin SHA256 kontrolleri ve ayrı `restorecheck_20260930T165306_1` veritabanına/fotoğraf klasörüne geri yüklemesi başarılı. Caddy HTTPS yapılandırması geçerli; gerçek domain sertifikası ve Gmail teslimatı bu yerel provada sınanmadı.

## Hazırlanan yapı

- `deploy/compose.production.yml`: yalnızca web proxy 80/443 portlarını yayınlar; API ve PostgreSQL için host portu yoktur.
- `backend/Dockerfile.production`: test edilmiş sürümleri sabitleyen runtime lock dosyası, root olmayan kullanıcı, iki worker, reload olmadan API.
- `frontend/Dockerfile.production`: Vite geliştirme sunucusu yerine derlenmiş statik arayüz; aynı origin'de `/api/v1` ve `/uploads`.
- Caddy: otomatik HTTPS, SPA fallback, güvenlik başlıkları, sınırlı gövde boyutu. DNS ve 80/443 erişimi gerçek ortamda sağlanmalıdır. [Caddy belgeleri](https://caddyserver.com/docs/automatic-https).
- API başlamadan önce migration'ın başarıyla bitmesi gerekir. [Compose başlangıç sırası](https://docs.docker.com/compose/how-tos/startup-order/).
- PostgreSQL, fotoğraflar ve TLS verileri ayrı kalıcı volume'larda tutulur. Log dosyaları boyut ve adet olarak sınırlıdır.
- Üretim ayarları eksik veya varsayılan anahtar/parola, HTTP origin, dosya e-postası, TLS'siz SMTP içeriyorsa API başlamaz.

## Alan adı ve Gmail ayarları

Sunucuda proje kökünden, gerçek hostname ve gönderici Gmail adresiyle:

```sh
python3 deploy/init-production.py --domain kamp.SIZIN-ALAN-ADINIZ --email GMAIL-ADRESINIZ
```

Script iki bağımsız rastgele sır üretir; bunları konsola yazmaz ve mevcut dosyanın üzerine yazmaz. `deploy/.env.production` git ve Docker build bağlamlarından dışlanır. Linux'ta yalnızca dosya sahibine izin verilir; Windows üzerinde erişim izinlerini ayrıca sınırlandırın. Kaynak paylaşırken bu dosyayı, geliştirme `.env` dosyasını, yedekleri veya `.mail-outbox` klasörünü göndermeyin.

Google hesabında iki adımlı doğrulamayı açın ve KaravanTR için uygulama şifresi oluşturun. [Google uygulama şifresi belgesi](https://support.google.com/accounts/answer/185833?hl=en). Uygulama şifresi seçeneği hesabınızda sunulmuyorsa hesap/Workspace politikası kontrol edilmeli; normal Google hesap şifresi kullanılmaz.

Yerel editör veya sunucu secret yönetimiyle `deploy/.env.production` içindeki `SMTP_PASSWORD` alanına uygulama şifresini yazın. Diğer hazır Gmail ayarları: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`; `SMTP_USERNAME` ve `SMTP_FROM` aynı tam Gmail adresidir. [Google SMTP ayarları](https://support.google.com/mail/answer/7104828?hl=en). Alan adına ait farklı bir gönderen kullanılacaksa ayrıca Gmail/Workspace gönderen doğrulaması gerekir.

SMTP şifresi terminal komutunun içine veya sohbet mesajına yazılmamalıdır. Ayar kontrolü değerleri göstermeden yapılır:

```sh
python3 deploy/check-production.py
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml config --quiet
```

API çalıştıktan sonra TLS ve Gmail oturumunu mesaj göndermeden kontrol etmek için:

```sh
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml exec -T api python - < deploy/check-smtp.py
```

Kendi posta kutunuza bir tanı iletisi gönderip teslimatı görmek için aynı komutta `python - --send-to GMAIL-ADRESINIZ` kullanın. Gerçek şifre sıfırlama/doğrulama bağlantısı testi ayrıca arayüzden yapılır.

Yedekleme için `sh deploy/tools/backup-production.sh` komutu API'yi durdurur, DB ve fotoğraf yedeği alır ve hata halinde de API'yi tekrar başlatır. Hosting seçildiğinde bu komut sunucunun zamanlayıcısına bağlanabilir.

Sunucuya domain A kaydını yönlendirin; AAAA kaydı varsa IPv6 da doğru sunucuya ulaşmalı. Sunucu firewall'ında SSH yönetimi ve 80/443 haricinde PostgreSQL/API portlarını açmayın. Hosting ağınız `172.29.41.0/24` ile çakışıyorsa Compose subnet'i, web IP'si (`172.29.41.254`) ve `FORWARDED_ALLOW_IPS` birlikte değiştirilmelidir. Güvenilen proxy adresi yalnızca Caddy'dir. Harici CDN/proxy kullanılacaksa istemci IP aktarımı ayrıca yapılandırılmalıdır.

## İlk kurulum ve güncelleme

```sh
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml build
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml up -d
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml ps
```

API sağlık kontrolü veritabanına sorgu yapar. Migration logunda hata varsa yayın devam etmez. `docker compose ... logs migrate api web` ile kontrol edin; hiçbir komutta secrets içeren tam `config` çıktısını paylaşmayın.

Güncellemeden önce yedek alın. `down -v` kalıcı verileri siler; bu yayın akışında kullanılmaz. Veritabanı parolasını yalnızca env dosyasında değiştirmek mevcut PostgreSQL kullanıcısının parolasını değiştirmez. Secret rotasyonu ayrı ve kontrollü bir işlemdir. Eski imaja dönmeden önce migration geriye uyumluluğunu kontrol edin; uygulama rollback'i ile veritabanı restore'u aynı işlem değildir.

## Veritabanı ve fotoğraf yedeği

Pilot ortamında tutarlı snapshot için kısa bakım aralığında API'yi durdurup yedek alın; yedek bittikten sonra API'yi başlatın. Fotoğraf ekleme/silme devam ederken veritabanı ve dosya snapshot'ı birbirinden farklı anları temsil edebilir.

```sh
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml stop api
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml --profile tools run --rm backup
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml start api
```

Yedek başarısız olsa da API'yi tekrar başlatın. `deploy/backups/backup-...` klasörü DB dump, fotoğraf arşivi, migration sürümü ve SHA256 doğrulamalarını içerir. Sunucu dışında güvenli bir kopyasını saklayın. Hosting belli olduğunda periyodik çalışma ve harici yedek hedefi kurulmalıdır; şu anda bir sunucu zamanlayıcısı kurulmadı.

Mevcut DB'yi değiştirmeden restore denemesi:

```sh
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml --profile tools run --rm --entrypoint sh backup /tools/verify-restore.sh YEDEK-KLASOR-ADI
```

Bu işlem ayrı `restorecheck_...` veritabanı ve ayrı fotoğraf klasörü oluşturup inceleme için bırakır. Gerçek felaket kurtarmada yeni bir stack/volume'a DB ve fotoğrafları birlikte yükleyin; doğrulamadan sonra trafik yönlendirin.

## Yerel üretim provası

Bu prova HTTPS sertifikasını veya Gmail teslimatını test etmez. Ayrı proje/volume ve yalnızca loopback HTTP portu kullanır:

```sh
python3 deploy/init-production.py --domain camp.pilot.test --email tester@pilot.test --smoke
docker compose --env-file deploy/.env.production-smoke -f deploy/compose.production.yml -f deploy/compose.smoke.yml -p karavantr-smoke build
docker compose --env-file deploy/.env.production-smoke -f deploy/compose.production.yml -f deploy/compose.smoke.yml -p karavantr-smoke up -d
python3 deploy/smoke-test.py
```

Smoke testi gerçek HTTP üzerinden arayüz, proxy, hazır olma, kayıt/giriş, nokta oluşturma/düzenleme, giriş fotoğrafı yükleme ve fotoğraf servis etmeyi kontrol eder. Sonunda sentetik nokta soft-delete edilir ve deneme hesabı kaldırılır. Kalıcı fotoğraf ve soft-delete edilmiş nokta test volume'unda kalır; gerçek kullanıcı verisi değildir. Smoke ayarları gerçek SMTP kimliği içermez.

## Linki arkadaşlarla paylaşmadan önce

1. Gerçek alan adında geçerli HTTPS ve HTTP→HTTPS yönlendirmesini doğrulayın.
2. Telefon üzerinden kayıt, giriş, nokta ekleme ve fotoğraf yüklemeyi deneyin.
3. Gmail üzerinden şifre sıfırlama ve e-posta doğrulama iletilerinin ulaştığını, bağlantıların gerçek alan adını açtığını kontrol edin.
4. Container'lar yeniden başlatıldığında kayıt ve fotoğrafın korunduğunu doğrulayın.
5. DB/fotoğraf yedeğini geri yükleyerek kontrol edin.
6. Genel Nominatim ve OSRM sağlayıcılarını yalnızca politikalara uygun pilot kullanımda kullanın; kapasite büyüdüğünde sağlayıcıyı değiştirin. Önceden eklenen karavan rotası sınırlaması arayüzde görünür.

Hosting sağlayıcısı, sunucu erişim yöntemi, domain ve gönderici Gmail adresi belirlenince gerçek ortama uygun son ayarlar yapılacak. Şifre ve özel anahtarlar sohbetten alınmayacak.
