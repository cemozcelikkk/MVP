"""`/api/v1/spots` altındaki endpoint'ler."""
import uuid
from datetime import UTC, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_moderator, resolve_user_from_authorization_header
from app.core.config import settings
from app.core.database import get_db
from app.models.enums import SpotCategory
from app.models.user import User
from app.schemas.compatibility import SpotCompatibilityResult, SpotCompatibilitySummary
from app.schemas.dynamic_status import DynamicStatusCreate, DynamicStatusRead
from app.schemas.geojson import Feature, FeatureCollection
from app.schemas.spot import (
    SpotCreate,
    SpotProperties,
    SpotRead,
    SpotUpdate,
    SpotVerifyUpdate,
    spot_to_feature,
)
from app.schemas.sync import SpotSyncResponse
from app.services.compatibility_service import evaluate_compatibility
from app.services.live_report_service import (
    DuplicateActiveReportError,
    InvalidExpiryError,
    build_live_access,
)
from app.services.review_service import get_spot_dimension_ratings
from app.services.spot_service import (
    SpotNotFoundError,
    SpotPermissionError,
    add_dynamic_status,
    create_spot,
    get_spot_by_id,
    get_spots_in_bbox,
    get_spots_sync,
    set_spot_verified,
    soft_delete_spot,
    update_spot,
)
from app.services.vehicle_profile_service import (
    VehicleProfileNotFoundError,
    VehicleProfilePermissionError,
    get_active_vehicle_profile,
    get_vehicle_profile,
)

router = APIRouter(prefix="/spots", tags=["spots"])


@router.get("/bbox", response_model=FeatureCollection[SpotProperties])
async def read_spots_in_bbox(
    min_lon: Annotated[float, Query(ge=-180, le=180, description="Dörtgenin batı sınırı (boylam)")],
    min_lat: Annotated[float, Query(ge=-90, le=90, description="Dörtgenin güney sınırı (enlem)")],
    max_lon: Annotated[float, Query(ge=-180, le=180, description="Dörtgenin doğu sınırı (boylam)")],
    max_lat: Annotated[float, Query(ge=-90, le=90, description="Dörtgenin kuzey sınırı (enlem)")],
    category: Annotated[
        list[SpotCategory] | None,
        Query(description="Kategoriye göre filtrele; parametre tekrarlanarak birden çok kategori seçilebilir"),
    ] = None,
    only_verified: Annotated[
        bool, Query(description="Yalnızca topluluk/moderatör tarafından doğrulanmış noktaları getir")
    ] = False,
    has_fresh_water: Annotated[
        bool | None, Query(description="Sadece dişli vana/hortum takılabilir temiz su kaynağı olanlar")
    ] = None,
    has_black_water: Annotated[
        bool | None, Query(description="Sadece kaset tuvalet döküm noktası/fosseptik bağlantısı olanlar")
    ] = None,
    has_electricity: Annotated[
        bool | None, Query(description="Sadece 220V elektrik bağlantısı olanlar")
    ] = None,
    has_toilet: bool | None = None,
    has_trash_bins: bool | None = None,
    is_free: bool | None = None,
    camping_behavior_allowed: bool | None = None,
    overnight_allowed: bool | None = None,
    max_vehicle_length: Annotated[
        float | None,
        Query(gt=0, le=30, description="Aracınızın (çeki dahil) metre cinsinden uzunluğu; bu uzunluğa uygun olmayan noktalar elenir"),
    ] = None,
    requires_4x4: Annotated[
        bool | None,
        Query(description="false verilirse 4x4/yüksek yer tutuşu gerektiren noktalar hariç tutulur"),
    ] = None,
    caravan_type: Annotated[
        str | None,
        Query(max_length=30, description="Sadece bu karavan tipine izin veren noktalar (ör. campervan, caravan, motorhome)"),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=settings.SPOTS_BBOX_MAX_LIMIT, description="Azami sonuç sayısı")
    ] = settings.SPOTS_BBOX_DEFAULT_LIMIT,
    with_compatibility: Annotated[
        bool,
        Query(
            description=(
                "true ise, kimliği doğrulanmış VE aktif araç profili olan kullanıcılar için her "
                "spot'a hafif bir `compatibility.status` özeti eklenir (harita 'Aracıma Uygun' "
                "filtresi için - bkz. endpoint docstring'i). Varsayılan false: MEVCUT davranış/"
                "performans birebir korunur, hiçbir ekstra sorgu çalışmaz."
            )
        ),
    ] = False,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> FeatureCollection[SpotProperties]:
    """
    Harita viewport'u (bounding box) içindeki spot'ları GeoJSON
    FeatureCollection olarak döndürür.

    İstemci (MapLibre/Mapbox) her pan/zoom sonrasında ekranın yeni
    min/max lon-lat değerleriyle bu endpoint'i çağırır ve dönen
    FeatureCollection'ı doğrudan bir GeoJSON source'a yükleyebilir.

    Altyapı (`has_*`) ve geçiş (`max_vehicle_length`, `requires_4x4`,
    `caravan_type`) parametreleri opsiyoneldir; hiçbiri verilmezse sadece
    mekansal filtre uygulanır. Filtre mantığının ayrıntısı için
    `spot_service.get_spots_in_bbox` docstring'ine bakınız.

    ## `with_compatibility` - "Aracıma Uygun" haritalama filtresi

    Bu endpoint zaten TÜM `passability` verisini her spot için taşıyor (N+1
    yok - tek `SELECT` + eager-load, bkz. `spot_service._SPOT_RELATIONSHIP_OPTIONS`).
    `with_compatibility=true` olduğunda, kullanıcının aktif araç profili
    BİR KEZ çekilir ve `compatibility_service.evaluate_compatibility` her
    spot için (DB'ye TEKRAR gitmeden, salt bellekte) çalıştırılır - "her
    marker için ayrı /compatibility isteği" YOKTUR, tek bir ekstra sorgu
    (aktif profil) + O(n) saf Python hesaplaması vardır.

    Performans notu: `authorization` başlığı BİLEREK `Depends(get_current_user)`
    yerine ham okunuyor ve kullanıcı çözümlemesi SADECE `with_compatibility=true`
    iken yapılıyor (bkz. `resolve_user_from_authorization_header`) - varsayılan
    (bayrak kapalı) çağrılar hiçbir token decode/kullanıcı sorgusu ÖDEMEZ,
    mevcut bbox performansı birebir korunur.
    """
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geçersiz bounding box: min_lon < max_lon ve min_lat < max_lat sağlanmalı.",
        )

    spots = await get_spots_in_bbox(
        db,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        categories=category,
        only_verified=only_verified,
        has_fresh_water=has_fresh_water,
        has_black_water=has_black_water,
        has_electricity=has_electricity,
        has_toilet=has_toilet,
        has_trash_bins=has_trash_bins,
        is_free=is_free,
        camping_behavior_allowed=camping_behavior_allowed,
        overnight_allowed=overnight_allowed,
        max_vehicle_length=max_vehicle_length,
        requires_4x4=requires_4x4,
        caravan_type=caravan_type,
        limit=limit,
    )

    vehicle = None
    if with_compatibility:
        current_user = await resolve_user_from_authorization_header(authorization, db)
        if current_user is not None:
            vehicle = await get_active_vehicle_profile(db, user_id=current_user.id)

    if vehicle is None:
        features = [spot_to_feature(spot) for spot in spots]
    else:
        features = []
        for spot in spots:
            result = evaluate_compatibility(spot_id=spot.id, passability=spot.passability, vehicle=vehicle)
            features.append(spot_to_feature(spot, compatibility=SpotCompatibilitySummary(status=result.status)))

    return FeatureCollection[SpotProperties](features=features)


@router.get("/sync", response_model=SpotSyncResponse)
async def sync_spots(
    since: Annotated[
        datetime,
        Query(
            description=(
                "Bu tarihten sonraki değişiklikleri getirir (ISO 8601). "
                "İlk (boş yerel veritabanı) senkron için 1970-01-01T00:00:00Z kullanın."
            )
        ),
    ],
    min_lon: Annotated[float | None, Query(ge=-180, le=180, description="Bölge filtresi (opsiyonel)")] = None,
    min_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    max_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    max_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    limit: Annotated[int, Query(ge=1, le=settings.SPOTS_BBOX_MAX_LIMIT)] = settings.SPOTS_BBOX_DEFAULT_LIMIT,
    db: AsyncSession = Depends(get_db),
) -> SpotSyncResponse:
    """
    Offline-first mobil istemci için delta (artımlı) senkron endpoint'i.

    `since`'den bu yana eklenen/değişen spot'ları (`upserts`) ve bu
    pencerede soft-delete edilmiş spot id'lerini (`deleted_ids`) döndürür.
    İstemci yanıttaki `server_time`'ı bir sonraki çağrıda `since` olarak
    kullanmalıdır - checkpoint güvenliği için ayrıntı `spot_service.get_spots_sync`
    docstring'indedir.

    `min_lon/min_lat/max_lon/max_lat` verilirse (dördü birden zorunlu),
    senkron yalnızca o bölgeyle sınırlandırılır - örn. bir karavancı sadece
    şu an içinde bulunduğu ili/bölgeyi offline paket olarak indirmek isteyebilir.
    """
    bbox_fields = (min_lon, min_lat, max_lon, max_lat)
    provided = [v is not None for v in bbox_fields]
    if any(provided) and not all(provided):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bölge filtresi için min_lon, min_lat, max_lon, max_lat parametrelerinin dördü birden verilmelidir.",
        )
    bbox = bbox_fields if all(provided) else None  # type: ignore[assignment]

    # İstemci offset'siz bir ISO datetime gönderirse (örn. "2026-01-01T00:00:00")
    # bunu UTC kabul ediyoruz; aksi halde tz-aware DB sütunuyla karşılaştırma hata verir.
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    upserts, deleted_ids, server_time = await get_spots_sync(db, since=since, bbox=bbox, limit=limit)

    return SpotSyncResponse(
        server_time=server_time,
        upserts=[SpotRead.model_validate(spot) for spot in upserts],
        deleted_ids=deleted_ids,
    )


@router.get("/{spot_id}", response_model=Feature[SpotProperties])
async def read_spot(spot_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Feature[SpotProperties]:
    """
    Tekil spot detayı (fotoğraflar, yorumlar özeti, canlı durum, passability
    ve amenities dahil eksiksiz GeoJSON Feature). Orijinal istek setinin bir
    parçası değildi; fotoğraf/detay verisini görüntüleyecek somut bir
    endpoint olması için eklendi - `/bbox` zaten aynı veriyi taşıyor, bu
    sadece tek bir noktayı ID ile çekmenin daha doğal yolu.

    Ayrıca çok boyutlu saha değerlendirmesinin (güvenlik/sessizlik/vb.)
    spot-geneli ortalama+adedini de taşır (`dimension_ratings`) - TEK ek
    sorgu, sadece burada (bkz. `review_service.get_spot_dimension_ratings`
    docstring'i - bbox'ta YOK, haritanın toplu sorgu performansı korunur).
    """
    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    dimension_ratings = await get_spot_dimension_ratings(db, spot_id=spot_id)
    return spot_to_feature(spot, dimension_ratings=dimension_ratings)


@router.get("/{spot_id}/compatibility", response_model=SpotCompatibilityResult)
async def read_spot_compatibility(
    spot_id: uuid.UUID,
    vehicle_profile_id: Annotated[
        uuid.UUID | None,
        Query(description="Değerlendirilecek araç profili. Verilmezse kullanıcının AKTİF profili kullanılır."),
    ] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpotCompatibilityResult:
    """
    Bir spot'un, kullanıcının (aktif veya belirtilen) araç profiliyle
    uyumluluğunu değerlendirir - bkz. `compatibility_service.evaluate_compatibility`.

    Karar mantığı tamamen backend'de: `status`/`reasons[].code`/
    `reasons[].severity` stabildir, istemci bunlara göre dallanmalı -
    `summary`/`reasons[].message` sadece gösterim metnidir (bkz. yanıt
    şemasının docstring'i). Sonuç kesin bir güvenlik garantisi DEĞİLDİR;
    topluluk tarafından bildirilen saha verisine dayanır.
    """
    spot = await get_spot_by_id(db, spot_id=spot_id)
    if spot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")

    if vehicle_profile_id is not None:
        try:
            vehicle = await get_vehicle_profile(
                db, profile_id=vehicle_profile_id, user_id=current_user.id
            )
        except VehicleProfileNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç profili bulunamadı.")
        except VehicleProfilePermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Bu araç profiline erişim yetkiniz yok."
            )
    else:
        vehicle = await get_active_vehicle_profile(db, user_id=current_user.id)
        if vehicle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aktif araç profili bulunamadı. Önce bir araç profili oluşturup aktif edin ya da vehicle_profile_id belirtin.",
            )

    result = evaluate_compatibility(spot_id=spot_id, passability=spot.passability, vehicle=vehicle)
    # Fiziksel uygunluk (`result.status`) DEĞİŞMEZ; "şu an erişilebilir mi" ayrı bir alanda.
    result.live_access = build_live_access(
        spot.dynamic_statuses, compatibility_status=result.status, now=datetime.now(UTC)
    )
    return result


@router.post("", response_model=Feature[SpotProperties], status_code=status.HTTP_201_CREATED)
async def create_spot_endpoint(
    payload: SpotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Feature[SpotProperties]:
    """
    Yeni bir spot ekler (kimlik doğrulama gerektirir).

    Gövdedeki `coordinates.{latitude,longitude}` PostGIS `Point(4326)`
    geometry'sine çevrilir; `spots`, `spot_passability` ve
    `spot_amenities` kayıtları tek transaction içinde oluşturulur (biri
    hata verirse hiçbiri kalıcı olmaz - bkz. `spot_service.create_spot`
    docstring'i). `created_by`, token'daki kullanıcıya ayarlanır.

    `payload.is_verified: true` sadece MODERATOR/ADMIN rolündeki
    kullanıcılar için geçerlidir; sıradan bir kullanıcı gönderse bile
    sessizce False'a zorlanır (bkz. `spot_service.create_spot`).
    """
    return await create_spot(
        db, data=payload, created_by=current_user.id, created_by_role=current_user.role
    )


@router.post(
    "/{spot_id}/status",
    response_model=DynamicStatusRead,
    status_code=status.HTTP_201_CREATED,
)
async def report_spot_status(
    spot_id: uuid.UUID,
    payload: DynamicStatusCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DynamicStatusRead:
    """
    ESKİ canlı durum ucu (zabıta müdahalesi + kalabalık) - geriye dönük uyumluluk için korunur;
    yeni istemciler `POST /spots/{id}/live-reports` (türlü, 6/12/24/48 saat) kullanmalıdır.
    `valid_until` gönderilmezse 24 saat sonrasına ayarlanır. Aynı kullanıcı aynı türü aktifken
    tekrar gönderirse 409 döner. `reported_by` yanıtta dönmez (gizlilik).
    """
    try:
        status_obj = await add_dynamic_status(db, spot_id=spot_id, data=payload, reported_by=current_user.id)
    except DuplicateActiveReportError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu noktada bu tür için zaten aktif bir bildiriminiz var; geri çekip yeniden bildirebilirsiniz.",
        )
    except InvalidExpiryError:
        raise HTTPException(
            status_code=422,  # HTTP_422_* sabiti Starlette sürümleri arasında yeniden adlandırıldı
            detail="`valid_until` gelecekte bir zaman olmalı.",
        )
    if status_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return DynamicStatusRead.model_validate(status_obj)


@router.put("/{spot_id}", response_model=Feature[SpotProperties])
@router.patch("/{spot_id}", response_model=Feature[SpotProperties])
async def update_spot_endpoint(
    spot_id: uuid.UUID,
    payload: SpotUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Feature[SpotProperties]:
    """
    Bir spot'un düzenlenebilir alanlarını değiştirir (kimlik doğrulama
    gerektirir). Sadece spot'un sahibi VEYA MODERATOR/ADMIN rolündekiler
    düzenleyebilir, aksi halde 403. Konum burada YOK (`SpotUpdate`'te
    `coordinates` tanımlı değil) - bu uç sadece içerik günceller, taşımaz.
    """
    try:
        return await update_spot(db, spot_id=spot_id, data=payload, current_user=current_user)
    except SpotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    except SpotPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu noktayı düzenleme yetkiniz yok."
        )


@router.delete("/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spot_endpoint(
    spot_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Spot'u soft-delete eder (`deleted_at` damgalanır, satır fiziksel olarak
    silinmez). Sadece spot'u oluşturan kullanıcı VEYA MODERATOR/ADMIN
    rolündekiler silebilir; aksi halde 403 döner (bkz.
    `spot_service.soft_delete_spot`).
    """
    try:
        await soft_delete_spot(db, spot_id=spot_id, current_user=current_user)
    except SpotNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı veya zaten silinmiş."
        )
    except SpotPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu noktayı silme yetkiniz yok."
        )


@router.patch("/{spot_id}/verify", response_model=Feature[SpotProperties])
async def verify_spot_endpoint(
    spot_id: uuid.UUID,
    payload: SpotVerifyUpdate,
    current_user: User = Depends(require_moderator),
    db: AsyncSession = Depends(get_db),
) -> Feature[SpotProperties]:
    """
    Bir spot'un doğrulama (`is_verified`) durumunu değiştirir. Sadece
    MODERATOR/ADMIN rolündeki kullanıcılar çağırabilir - yetki kontrolü
    `require_moderator` dependency'si tarafından yapılır (rolü uygun
    olmayan bir kullanıcı 403 alır, endpoint gövdesine hiç girilmez).
    """
    feature = await set_spot_verified(db, spot_id=spot_id, is_verified=payload.is_verified, actor_id=current_user.id)
    if feature is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spot bulunamadı.")
    return feature
