"""
Karavan Profili <-> Nokta uyumluluk motoru.

Bilerek router'dan ve veritabanından TAMAMEN bağımsız, saf bir hesaplama
fonksiyonudur (`evaluate_compatibility`): girdi olarak `SpotPassability` ve
`VehicleProfile` ORM nesnelerini alır (DB oturumu GEREKMEDEN, düz Python
constructor'ıyla da kurulabilirler - bkz. `tests/test_compatibility_service.py`),
DB'ye dokunmaz, yan etkisi yoktur, aynı girdi her zaman aynı çıktıyı üretir.
Eşik değerleri (6/5/10000 gibi büyüklükler DEĞİL - onlar `app.schemas.vehicle_profile`/
`app.schemas.spot_passability`'de zaten var; burdaki eşikler "kaç alan bilinmiyorsa
insufficient_data" gibi KARAR eşikleri) SADECE burada yaşar - React tarafında
hiçbir eşik/karar mantığı YOKTUR, frontend yalnızca `status`/`reasons`i gösterir.

## Kural seti (bu sırayla değerlendirilir)

1. Araç uzunluğu > noktanın azami uzunluğu (biliniyorsa)              -> blocking
2. Araç genişliği BİLİNİYOR ve > noktanın azami genişliği (biliniyorsa) -> blocking
3. Araç yüksekliği BİLİNİYOR ve > noktanın azami yüksekliği (biliniyorsa) -> blocking
4. Araç ağırlığı BİLİNİYOR ve > noktanın azami ağırlığı (biliniyorsa)  -> blocking
5. Nokta `clearance_required=HIGH_4X4` VE araç `TWO_WHEEL_DRIVE` ise:
   mevcut veri modelinde bu alan bir ÖNERİ değil, adının ("clearance_REQUIRED")
   ve `spot_service.get_spots_in_bbox`'taki `requires_4x4` filtresinin
   ("4x4 gerektiren noktalar") ima ettiği gibi KESİN BİR GEREKSİNİMDİR ->
   blocking (bkz. `_check_drivetrain`). Veri modeli ileride "recommended"
   diye ayrı bir seviye kazanırsa, O seviye caution/warning olarak eklenir -
   şu an öyle bir ayrım YOK, tek sinyal var ve o "gerekli" anlamına geliyor.
6. Zorlayıcı yol yüzeyi (DIRT/ROCKY) veya `steep_incline=true`         -> warning (caution)

## Nihai `status` (deterministik, sadece severity'lere bakar - metne değil)

    herhangi bir "blocking"           -> not_compatible   (HER ZAMAN kazanır)
    yoksa herhangi bir "warning"      -> caution
    yoksa: 4 kritik boyuttan (uzunluk/genişlik/yükseklik/ağırlık) ÇOĞU
           (>%50, yani 4 alanda >=3) "unknown" ise                    -> insufficient_data
    aksi halde                                                        -> compatible

"Kritik alanların ÇOĞU" eşiği bilinçli: TEK bir bilinmeyen alan (ör. sadece
ağırlık limiti hiç girilmemiş), diğer her şey biliniyorsa ve engel yoksa,
sonucu insufficient_data'ya DÜŞÜRMEZ - `compatible` döner (bilinmeyen alan
yine de ayrı bir "unknown" reason olarak listede kalır, sadece genel kararı
domine etmez). Bu, görev tanımındaki "bilinmeyen her alan nedeniyle uygun
bir noktayı otomatik olarak tehlikeli/uygunsuz sayma" kuralının birebir
uygulanışıdır - bkz. `_INSUFFICIENT_DATA_MIN_UNKNOWN_DIMENSIONS` ve
testlerdeki `test_minority_unknown_dimensions_still_compatible`.
"""
import uuid
from datetime import UTC, datetime

from app.models.enums import ClearanceRequired, Drivetrain, RoadType
from app.models.spot_passability import SpotPassability
from app.models.vehicle_profile import VehicleProfile
from app.schemas.compatibility import (
    CompatibilityReason,
    CompatibilityStatus,
    SpotCompatibilityResult,
)

_SEVERITY_PRIORITY = ("blocking", "warning", "unknown", "info")

# "Kritik teknik alanlar" = araç <-> nokta arasında doğrudan ölçü/kapasite
# karşılaştırması yapılan 4 boyut. Çekiş(4x4)/eğim/yol yüzeyi bunun DIŞINDA -
# onlar birer "caution" sinyali, "insufficient_data" sayacına girmez (zaten
# her zaman bilinen bir enum değerine sahiptirler, "unknown" durumları yok).
_CRITICAL_DIMENSIONS = ("LENGTH", "WIDTH", "HEIGHT", "WEIGHT")
# Çoğunluk = %50'den FAZLA. 4 kritik alanda bu tam olarak ">= 3" demektir;
# sayıyı sabit "3" yerine oranla ifade ediyoruz ki `_CRITICAL_DIMENSIONS`
# listesi büyürse/küçülürse eşik kendiliğinden doğru ölçeklensin.
_INSUFFICIENT_DATA_MIN_UNKNOWN_DIMENSIONS = len(_CRITICAL_DIMENSIONS) // 2 + 1  # -> 3

_SUMMARY_BY_STATUS: dict[CompatibilityStatus, str] = {
    "not_compatible": "Bildirilen ölçülere göre aracınız bu noktaya uygun değil.",
    "caution": "Bu noktaya dikkatli giriş yapmanız öneriliyor.",
    "insufficient_data": "Bu nokta için aracınızın uyumluluğunu tam değerlendirecek yeterli saha verisi yok.",
    "compatible": "Bildirilen ölçülere göre aracınız bu noktaya uygun görünüyor.",
}

_DIMENSION_LABEL = {
    "LENGTH": "Araç uzunluğu",
    "WIDTH": "Araç genişliği",
    "HEIGHT": "Araç yüksekliği",
    "WEIGHT": "Araç ağırlığı",
}
# İyelik eki OLMADAN çıplak isim - "maksimum uzunluk 6 m" gibi cümlelerde
# (LABEL'daki "uzunluğu" burada gramer olarak yanlış olurdu).
_DIMENSION_BARE_NOUN = {
    "LENGTH": "uzunluk",
    "WIDTH": "genişlik",
    "HEIGHT": "yükseklik",
    "WEIGHT": "ağırlık",
}


def _fmt_m(value: float) -> str:
    """3.50 -> '3,5' / 6.0 -> '6' - Türkçe ondalık ayraç, gereksiz sıfır yok."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _check_dimension(
    *,
    dimension: str,  # "LENGTH" | "WIDTH" | "HEIGHT" | "WEIGHT" - bkz. _CRITICAL_DIMENSIONS
    vehicle_value: float | None,
    spot_max: float | None,
    unit: str,
    vehicle_required: bool,
) -> CompatibilityReason:
    """
    Tek bir ölçü ekseni için ortak karşılaştırma mantığı - uzunluk/genişlik/
    yükseklik/ağırlık dörtte de aynı 3 durum söz konusu: taraflardan biri
    bilinmiyor (severity=unknown), sınır aşılıyor (blocking) ya da sınır
    içinde (info). ASLA `None` dönmez - her boyut için tam olarak bir reason
    üretilir ki `_count_unknown_dimensions` güvenilir sayabilsin.

    `vehicle_required=True` sadece `length_m` içindir (VehicleProfile'da
    zorunlu/NOT NULL alan) - `vehicle_value` orada asla None olamaz.
    """
    label = _DIMENSION_LABEL[dimension]
    bare_noun = _DIMENSION_BARE_NOUN[dimension]

    if vehicle_value is None and not vehicle_required:
        return CompatibilityReason(
            code=f"{dimension}_VEHICLE_UNKNOWN",
            severity="unknown",
            message=f"{label} araç profilinizde belirtilmemiş.",
        )

    if spot_max is None:
        return CompatibilityReason(
            code=f"{dimension}_UNKNOWN",
            severity="unknown",
            message=f"{label} sınırı hakkında yeterli saha verisi bulunmuyor.",
        )

    assert vehicle_value is not None  # yukarıdaki erken dönüş sonrası garanti
    if vehicle_value > spot_max:
        return CompatibilityReason(
            code=f"{dimension}_EXCEEDS_LIMIT",
            severity="blocking",
            message=(
                f"Aracınız {_fmt_m(vehicle_value)} {unit}, bu noktada bildirilen "
                f"maksimum {bare_noun} {_fmt_m(spot_max)} {unit}."
            ),
        )

    return CompatibilityReason(
        code=f"{dimension}_OK",
        severity="info",
        message=f"{label} ({_fmt_m(vehicle_value)} {unit}) bu noktanın bildirilen sınırları içinde.",
    )


def _check_drivetrain(
    *, clearance_required: ClearanceRequired, drivetrain: Drivetrain
) -> CompatibilityReason | None:
    """
    Bkz. modül docstring'indeki 5. madde: mevcut veri modelinde HIGH_4X4
    bir ÖNERİ değil kesin gereksinim anlamına gelir, bu yüzden blocking.
    """
    if clearance_required != ClearanceRequired.HIGH_4X4:
        # LOW/STANDARD: özel bir çekiş gereksinimi bildirilmemiş - alakasız
        # bir "her şey yolunda" notu eklemiyoruz (bkz. modül docstring'i).
        return None

    if drivetrain == Drivetrain.FOUR_WHEEL_DRIVE:
        return CompatibilityReason(
            code="FOUR_WHEEL_DRIVE_OK",
            severity="info",
            message="Bu nokta 4x4 gerektiriyor ve aracınız 4x4 - uygun.",
        )

    return CompatibilityReason(
        code="FOUR_WHEEL_DRIVE_REQUIRED",
        severity="blocking",
        message="Bu noktaya ulaşmak için 4x4 gerekiyor; aracınız 4x2 çekişli.",
    )


def _check_steep_incline(*, steep_incline: bool) -> CompatibilityReason | None:
    if not steep_incline:
        return None
    return CompatibilityReason(
        code="STEEP_INCLINE_CAUTION",
        severity="warning",
        message="Bu noktaya giden yolda dik eğim/zorlu viraj bildirilmiş - dikkatli sürüş gerekir.",
    )


# "Zorlayıcı" yüzey = iyileştirilmemiş yüzeyler. ASPHALT/GRAVEL çoğu karavan
# için normal kabul edilir; DIRT/ROCKY manevra kabiliyeti düşük/uzun
# araçlarda dikkat gerektirir (ama HANGİ aracın geçemeyeceğini kesin olarak
# BİLEMEYİZ - bu yüzden blocking değil, warning/caution).
_CHALLENGING_ROAD_TYPES = (RoadType.DIRT, RoadType.ROCKY)


def _check_road_surface(*, road_type: RoadType) -> CompatibilityReason | None:
    if road_type not in _CHALLENGING_ROAD_TYPES:
        return None
    return CompatibilityReason(
        code="CHALLENGING_ROAD_SURFACE",
        severity="warning",
        message="Bu noktaya giden yol toprak/taşlık zeminli - lastik ve yer tutuşuna dikkat edin.",
    )


def _count_unknown_dimensions(dimension_reasons: list[CompatibilityReason]) -> int:
    return sum(1 for reason in dimension_reasons if reason.severity == "unknown")


def evaluate_compatibility(
    *,
    spot_id: uuid.UUID,
    passability: SpotPassability | None,
    vehicle: VehicleProfile,
) -> SpotCompatibilityResult:
    """
    Bir spot'un `SpotPassability`'si ile bir `VehicleProfile`'ı karşılaştırıp
    stabil `status`/`reasons` üretir. `passability` teorik olarak None
    olabilir (ör. veri bütünlüğü bozulmuşsa) - bu durumda 4 kritik boyutun
    TAMAMI "unknown" olur (spot_max=None), bu da doğal olarak
    `_INSUFFICIENT_DATA_MIN_UNKNOWN_DIMENSIONS` eşiğini aşıp
    `insufficient_data` üretir; çekiş/eğim/yüzey kontrolleri ise (hangi
    değeri karşılaştıracaklarını bilemedikleri için) sessizce atlanır.
    """
    length_max = float(passability.max_vehicle_length) if passability and passability.max_vehicle_length is not None else None
    width_max = float(passability.max_vehicle_width) if passability and passability.max_vehicle_width is not None else None
    height_max = float(passability.max_vehicle_height) if passability and passability.max_vehicle_height is not None else None
    weight_max = float(passability.max_vehicle_weight_kg) if passability and passability.max_vehicle_weight_kg is not None else None

    dimension_reasons = [
        _check_dimension(
            dimension="LENGTH",
            vehicle_value=float(vehicle.length_m),
            spot_max=length_max,
            unit="m",
            vehicle_required=True,
        ),
        _check_dimension(
            dimension="WIDTH",
            vehicle_value=float(vehicle.width_m) if vehicle.width_m is not None else None,
            spot_max=width_max,
            unit="m",
            vehicle_required=False,
        ),
        _check_dimension(
            dimension="HEIGHT",
            vehicle_value=float(vehicle.height_m) if vehicle.height_m is not None else None,
            spot_max=height_max,
            unit="m",
            vehicle_required=False,
        ),
        _check_dimension(
            dimension="WEIGHT",
            vehicle_value=float(vehicle.weight_kg) if vehicle.weight_kg is not None else None,
            spot_max=weight_max,
            unit="kg",
            vehicle_required=False,
        ),
    ]

    other_reasons: list[CompatibilityReason] = []
    if passability is not None:
        for reason in (
            _check_drivetrain(clearance_required=passability.clearance_required, drivetrain=vehicle.drivetrain),
            _check_steep_incline(steep_incline=passability.steep_incline),
            _check_road_surface(road_type=passability.road_type),
        ):
            if reason is not None:
                other_reasons.append(reason)

    all_reasons = dimension_reasons + other_reasons

    # --- Deterministik status kararı - bkz. modül docstring'indeki tablo. ---
    if any(r.severity == "blocking" for r in all_reasons):
        result_status: CompatibilityStatus = "not_compatible"
    elif any(r.severity == "warning" for r in all_reasons):
        result_status = "caution"
    elif _count_unknown_dimensions(dimension_reasons) >= _INSUFFICIENT_DATA_MIN_UNKNOWN_DIMENSIONS:
        result_status = "insufficient_data"
    else:
        result_status = "compatible"

    # Sunumda en kritik reason'lar en üstte olsun.
    all_reasons.sort(key=lambda r: _SEVERITY_PRIORITY.index(r.severity))

    return SpotCompatibilityResult(
        spot_id=spot_id,
        vehicle_profile_id=vehicle.id,
        status=result_status,
        summary=_SUMMARY_BY_STATUS[result_status],
        reasons=all_reasons,
        checked_at=datetime.now(UTC),
    )
