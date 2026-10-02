"""
`compatibility_service.evaluate_compatibility` için birim testleri.

Bilerek DB oturumu/fixture'ı KULLANMIYOR - `evaluate_compatibility` saf bir
fonksiyondur, `SpotPassability`/`VehicleProfile` ORM sınıfları burada
sadece düz Python nesneleri olarak (constructor'la, hiç flush/commit
edilmeden) kuruluyor. Bu hem testleri hızlı/izole tutar hem de servisin
gerçekten "saf fonksiyona yakın" tasarlandığını doğrular (bkz. görev
tanımı: "Eşik değerlerini React bileşenlerine dağıtma" - tüm karar eşikleri
burada, tek bir yerde yaşıyor ve bu dosyada test ediliyor).
"""
import uuid

import pytest

from app.models.enums import ClearanceRequired, Drivetrain, RoadType, VehicleType
from app.models.spot_passability import SpotPassability
from app.models.vehicle_profile import VehicleProfile
from app.services.compatibility_service import evaluate_compatibility

SPOT_ID = uuid.uuid4()


def make_vehicle(**overrides) -> VehicleProfile:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "name": "Test Aracı",
        "vehicle_type": VehicleType.MOTORHOME,
        "length_m": 6.0,
        "width_m": 2.2,
        "height_m": 2.9,
        "weight_kg": 3500,
        "drivetrain": Drivetrain.TWO_WHEEL_DRIVE,
    }
    defaults.update(overrides)
    return VehicleProfile(**defaults)


def make_passability(**overrides) -> SpotPassability:
    defaults = {
        "road_type": RoadType.ASPHALT,
        "max_vehicle_length": 7.0,
        "max_vehicle_width": 2.5,
        "max_vehicle_height": 3.5,
        "max_vehicle_weight_kg": 5000,
        "clearance_required": ClearanceRequired.STANDARD,
        "steep_incline": False,
    }
    defaults.update(overrides)
    return SpotPassability(**defaults)


def reason_codes(result) -> set[str]:
    return {r.code for r in result.reasons}


# --- Temel "her şey uyuyor" durumu -----------------------------------------


def test_compatible_when_all_known_and_within_limits():
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=make_passability(), vehicle=make_vehicle())
    assert result.status == "compatible"
    assert reason_codes(result) == {"LENGTH_OK", "WIDTH_OK", "HEIGHT_OK", "WEIGHT_OK"}
    assert all(r.severity == "info" for r in result.reasons)


def test_spot_id_and_vehicle_profile_id_propagate_to_result():
    vehicle = make_vehicle()
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=make_passability(), vehicle=vehicle)
    assert result.spot_id == SPOT_ID
    assert result.vehicle_profile_id == vehicle.id


def test_is_a_pure_function_same_input_same_output():
    """Aynı girdi -> aynı status/reasons (checked_at hariç) - yan etkisiz, deterministik."""
    passability = make_passability()
    vehicle = make_vehicle()
    r1 = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    r2 = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert r1.status == r2.status
    assert [(r.code, r.severity) for r in r1.reasons] == [(r.code, r.severity) for r in r2.reasons]


# --- Kural 1-4: her ölçü ekseni, biliniyorsa ve aşılıyorsa -> not_compatible ---


@pytest.mark.parametrize(
    "field,vehicle_kwargs,spot_kwargs,expected_code",
    [
        ("length", {"length_m": 6.5}, {"max_vehicle_length": 6.0}, "LENGTH_EXCEEDS_LIMIT"),
        ("width", {"width_m": 2.6}, {"max_vehicle_width": 2.5}, "WIDTH_EXCEEDS_LIMIT"),
        ("height", {"height_m": 3.6}, {"max_vehicle_height": 3.5}, "HEIGHT_EXCEEDS_LIMIT"),
        ("weight", {"weight_kg": 5500}, {"max_vehicle_weight_kg": 5000}, "WEIGHT_EXCEEDS_LIMIT"),
    ],
)
def test_not_compatible_when_dimension_exceeds_known_limit(field, vehicle_kwargs, spot_kwargs, expected_code):
    vehicle = make_vehicle(**vehicle_kwargs)
    passability = make_passability(**spot_kwargs)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "not_compatible"
    assert expected_code in reason_codes(result)
    reason = next(r for r in result.reasons if r.code == expected_code)
    assert reason.severity == "blocking"


@pytest.mark.parametrize(
    "vehicle_field,spot_field,expected_code",
    [
        ("width_m", "max_vehicle_width", "WIDTH_VEHICLE_UNKNOWN"),
        ("height_m", "max_vehicle_height", "HEIGHT_VEHICLE_UNKNOWN"),
        ("weight_kg", "max_vehicle_weight_kg", "WEIGHT_VEHICLE_UNKNOWN"),
    ],
)
def test_dimension_not_checked_when_vehicle_side_unknown_even_if_spot_limit_would_be_exceeded(
    vehicle_field, spot_field, expected_code
):
    """
    Genişlik/yükseklik/ağırlık İSTEĞE BAĞLIDIR (VehicleProfile'da nullable).
    Görev tanımı: "genişliği BİLİNİYOR ve aşıyorsa" -> blocking. Araç
    tarafı bilinmiyorsa karşılaştırma YAPILAMAZ, bu yüzden blocking değil
    "unknown" üretilmeli - spot limiti teorik olarak aşılacak (çok küçük)
    olsa bile.
    """
    vehicle = make_vehicle(**{vehicle_field: None})
    # Spot limitini kasten çok düşük tutuyoruz - eğer motor yanlışlıkla
    # "bilinmiyor -> 0 kabul et, aşıyor" derse bu blocking üretirdi.
    passability = make_passability(**{spot_field: 0.5})
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert expected_code in reason_codes(result)
    reason = next(r for r in result.reasons if r.code == expected_code)
    assert reason.severity == "unknown"
    assert not any(r.severity == "blocking" for r in result.reasons)


# --- Kural 5: 4x4 - mevcut veri modelinde HIGH_4X4 bir gereksinimdir --------


def test_not_compatible_when_high_4x4_required_and_vehicle_is_two_wheel_drive():
    vehicle = make_vehicle(drivetrain=Drivetrain.TWO_WHEEL_DRIVE)
    passability = make_passability(clearance_required=ClearanceRequired.HIGH_4X4)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "not_compatible"
    reason = next(r for r in result.reasons if r.code == "FOUR_WHEEL_DRIVE_REQUIRED")
    assert reason.severity == "blocking"


def test_compatible_when_high_4x4_required_and_vehicle_is_four_wheel_drive():
    vehicle = make_vehicle(drivetrain=Drivetrain.FOUR_WHEEL_DRIVE)
    passability = make_passability(clearance_required=ClearanceRequired.HIGH_4X4)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "compatible"
    reason = next(r for r in result.reasons if r.code == "FOUR_WHEEL_DRIVE_OK")
    assert reason.severity == "info"


@pytest.mark.parametrize("clearance", [ClearanceRequired.LOW, ClearanceRequired.STANDARD])
def test_no_drivetrain_reason_when_high_clearance_not_required(clearance):
    """LOW/STANDARD için hiçbir DRIVETRAIN reason'ı üretilmemeli (alakasız gürültü yok)."""
    vehicle = make_vehicle(drivetrain=Drivetrain.TWO_WHEEL_DRIVE)
    passability = make_passability(clearance_required=clearance)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert not any(r.code.startswith("FOUR_WHEEL_DRIVE") for r in result.reasons)


# --- Kural 6: zorlayıcı yol tipi / dik eğim -> caution ----------------------


def test_caution_on_steep_incline_only():
    passability = make_passability(steep_incline=True)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=make_vehicle())
    assert result.status == "caution"
    reason = next(r for r in result.reasons if r.code == "STEEP_INCLINE_CAUTION")
    assert reason.severity == "warning"


@pytest.mark.parametrize("road_type", [RoadType.DIRT, RoadType.ROCKY])
def test_caution_on_challenging_road_surface(road_type):
    passability = make_passability(road_type=road_type)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=make_vehicle())
    assert result.status == "caution"
    reason = next(r for r in result.reasons if r.code == "CHALLENGING_ROAD_SURFACE")
    assert reason.severity == "warning"


@pytest.mark.parametrize("road_type", [RoadType.ASPHALT, RoadType.GRAVEL])
def test_no_caution_on_normal_road_surface(road_type):
    passability = make_passability(road_type=road_type)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=make_vehicle())
    assert result.status == "compatible"


# --- Öncelik sırası: not_compatible > caution > insufficient_data > compatible ---


def test_not_compatible_always_wins_over_warning_and_unknown():
    vehicle = make_vehicle(length_m=8.0, width_m=None)  # blocking + unknown birlikte
    passability = make_passability(max_vehicle_length=6.0, steep_incline=True)  # + warning
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "not_compatible"


def test_caution_wins_over_insufficient_data():
    """Çoğunluk (3/4) boyut bilinmese BİLE, bir 'warning' varsa sonuç caution olmalı - insufficient_data değil."""
    vehicle = make_vehicle(width_m=None, height_m=None, weight_kg=None)
    passability = make_passability(steep_incline=True)
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "caution"


# --- "Veri yetersiz" kararı: ÇOĞUNLUK (>=3/4) kritik alan bilinmiyorsa ------


def test_insufficient_data_when_majority_of_dimensions_unknown():
    """3/4 kritik boyut (width/height/weight) bilinmiyor, blocking/warning yok -> insufficient_data."""
    vehicle = make_vehicle(width_m=None, height_m=None, weight_kg=None)
    passability = make_passability()
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "insufficient_data"
    unknown_codes = {r.code for r in result.reasons if r.severity == "unknown"}
    assert unknown_codes == {"WIDTH_VEHICLE_UNKNOWN", "HEIGHT_VEHICLE_UNKNOWN", "WEIGHT_VEHICLE_UNKNOWN"}


def test_insufficient_data_when_all_four_dimensions_unknown():
    vehicle = make_vehicle(width_m=None, height_m=None, weight_kg=None)
    passability = make_passability(
        max_vehicle_length=None, max_vehicle_width=None, max_vehicle_height=None, max_vehicle_weight_kg=None
    )
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "insufficient_data"


def test_minority_unknown_dimensions_still_compatible():
    """
    SADECE 2/4 (azınlık, %50 - çoğunluk DEĞİL) kritik boyut bilinmiyor,
    bilinenlerin hepsi limit içinde, hiçbir engel/uyarı yok -> sonuç YİNE DE
    `compatible` olmalı (görev tanımı: "bilinmeyen her alan nedeniyle uygun
    bir noktayı otomatik olarak tehlikeli/uygunsuz sayma"). Bilinmeyen
    alanlar yine de ayrı "unknown" reason olarak listede kalmalı - sadece
    genel kararı domine etmiyor.
    """
    vehicle = make_vehicle(height_m=None, weight_kg=None)
    passability = make_passability()
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "compatible"
    unknown_codes = {r.code for r in result.reasons if r.severity == "unknown"}
    assert unknown_codes == {"HEIGHT_VEHICLE_UNKNOWN", "WEIGHT_VEHICLE_UNKNOWN"}
    assert {"LENGTH_OK", "WIDTH_OK"}.issubset(reason_codes(result))


def test_exactly_half_unknown_is_not_majority():
    """
    Sınır durum: 4 kritik alanın tam yarısı (2/4) bilinmiyor. "Çoğunluk"
    kesin olarak %50'den FAZLA demek olduğu için bu ÇOĞUNLUK SAYILMAZ ->
    insufficient_data DEĞİL, compatible dönmeli (bkz. modüldeki
    `_INSUFFICIENT_DATA_MIN_UNKNOWN_DIMENSIONS = len(_CRITICAL_DIMENSIONS) // 2 + 1`).
    """
    vehicle = make_vehicle(width_m=None, weight_kg=None)
    passability = make_passability()
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=passability, vehicle=vehicle)
    assert result.status == "compatible"


def test_passability_entirely_missing_yields_insufficient_data():
    """
    `passability=None` (teorik veri bütünlüğü bozulması) - 4 kritik boyutun
    TAMAMI karşılaştırılamaz hale gelir, bu da doğal olarak çoğunluk
    eşiğini aşıp insufficient_data üretir; çekiş/eğim/yüzey kontrolleri
    sessizce atlanır (yanlış bir varsayımda bulunmaz).
    """
    result = evaluate_compatibility(spot_id=SPOT_ID, passability=None, vehicle=make_vehicle())
    assert result.status == "insufficient_data"
    assert not any(r.code.startswith("FOUR_WHEEL_DRIVE") for r in result.reasons)
    assert not any(r.code in ("STEEP_INCLINE_CAUTION", "CHALLENGING_ROAD_SURFACE") for r in result.reasons)
