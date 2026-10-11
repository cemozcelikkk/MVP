"""
Domain enum'ları.

Bu enum'lar hem SQLAlchemy tarafında native PostgreSQL ENUM tipi olarak,
hem de Pydantic şemalarında doğrulama için kullanılır (app.schemas.*).
"""
import enum


class SpotCategory(str, enum.Enum):
    """Harita pin kategorisi (park4night tarzı çok-tipli POI haritası).

    Değerler API'de ve DB enum'unda BÜYÜK harfle taşınır; istemciler bu
    kodlara göre dallanmalı/ikon seçmelidir.
    """
    CAMPING = "CAMPING"                  # Kamp/karavan konaklama noktası (resmi alan veya doğa)
    FISH_RESTAURANT = "FISH_RESTAURANT"  # Balık restoranı
    MEAT_RESTAURANT = "MEAT_RESTAURANT"  # Et restoranı / mangal / kebap
    HOTEL_POOL = "HOTEL_POOL"            # Havuzu dışarıdan kullanılabilen otel
    HOSPITAL = "HOSPITAL"                # Hastane (acil servis)
    HEALTH_CENTER = "HEALTH_CENTER"      # Sağlık ocağı / aile sağlığı merkezi


# Yeni `spots` kaydı için kabul edilen kategoriler. `spots` artık yalnızca kamp/
# karavan konaklama noktalarını taşır: restoran ve sağlık kayıtları
# `service_points`'e taşındı (bkz. app.models.service_point), HOTEL_POOL ise
# yeni eklemeye kapalı - mevcut kayıtlar haritada salt okunur kalır. Eski enum
# değerleri DB'de (geçmiş satırlar/geri dönüş için) durur ama API onları kabul etmez.
CREATABLE_SPOT_CATEGORIES = frozenset({SpotCategory.CAMPING})


class ServicePointCategory(str, enum.Enum):
    """Çevresel hizmet/ihtiyaç noktası türü (bkz. app.models.service_point).

    Kamp alanı DEĞİLDİR: araç uyumluluğu, 7 boyutlu değerlendirme veya canlı
    saha bildirimi taşımaz. Değerler API'de ve DB enum'unda BÜYÜK harfle taşınır.
    """
    MEAT_RESTAURANT = "MEAT_RESTAURANT"    # Et restoranı / mangal / kebap
    FISH_RESTAURANT = "FISH_RESTAURANT"    # Balık restoranı
    OTHER_RESTAURANT = "OTHER_RESTAURANT"  # Diğer restoran / kafe
    HOSPITAL = "HOSPITAL"                  # Hastane
    HEALTH_CENTER = "HEALTH_CENTER"        # Sağlık ocağı / aile sağlığı merkezi
    WC = "WC"                              # Umumi tuvalet
    SHOWER = "SHOWER"                      # Duş


class ServicePointGroup(str, enum.Enum):
    """Ekleme akışının ve harita şeridinin ana grupları; DB'de saklanmaz, kategoriden türetilir."""
    FOOD = "food"      # Yeme & İçme - yıldız + yorum
    HEALTH = "health"  # Sağlık - puan/yorum YOK, sadece tür + konum
    BASIC = "basic"    # Temel ihtiyaçlar - ücret/kullanılabilirlik durumu


SERVICE_POINT_GROUP_CATEGORIES: dict[ServicePointGroup, tuple[ServicePointCategory, ...]] = {
    ServicePointGroup.FOOD: (
        ServicePointCategory.MEAT_RESTAURANT,
        ServicePointCategory.FISH_RESTAURANT,
        ServicePointCategory.OTHER_RESTAURANT,
    ),
    ServicePointGroup.HEALTH: (ServicePointCategory.HOSPITAL, ServicePointCategory.HEALTH_CENTER),
    ServicePointGroup.BASIC: (ServicePointCategory.WC, ServicePointCategory.SHOWER),
}


def service_point_group(category: ServicePointCategory) -> ServicePointGroup:
    for group, categories in SERVICE_POINT_GROUP_CATEGORIES.items():
        if category in categories:
            return group
    raise ValueError(category)  # pragma: no cover - her kategori bir gruba ait


class SpotSource(str, enum.Enum):
    """Spot verisinin nereden geldiği. Kullanıcı formundan gelenler her zaman
    USER_ADDED'dir; diğerleri toplu içe aktarma (import) betiklerince atanır."""
    USER_ADDED = "USER_ADDED"
    OVERPASS_OSM = "OVERPASS_OSM"
    GOOGLE_PLACES = "GOOGLE_PLACES"


class RoadType(str, enum.Enum):
    ASPHALT = "asphalt"
    GRAVEL = "gravel"
    DIRT = "dirt"
    ROCKY = "rocky"


class ClearanceRequired(str, enum.Enum):
    LOW = "low"
    STANDARD = "standard"
    HIGH_4X4 = "high_4x4"


class CaravanType(str, enum.Enum):
    """spot_passability.caravan_types_allowed dizisindeki olası değerler."""
    CAMPERVAN = "campervan"          # Panelvan / kamperli van
    CARAVAN = "caravan"              # Çekme karavan
    MOTORHOME = "motorhome"          # Motokaravan (A/B/C sınıfı)
    TENT_TRAILER = "tent_trailer"    # Katlanır çadır römork
    TRUCK_CAMPER = "truck_camper"    # Kamyonet üstü kabin


class GsmOperator(str, enum.Enum):
    """spot_amenities.gsm_signals JSONB alanındaki bilinen operatör anahtarları."""
    TURKCELL = "turkcell"
    VODAFONE = "vodafone"
    TURK_TELEKOM = "turk_telekom"


class SignalStrength(str, enum.Enum):
    NONE = "none"
    POOR = "poor"
    MEDIUM = "medium"
    GOOD = "good"


class PoliceInterventionStatus(str, enum.Enum):
    """Türkiye'ye özgü zabıta/jandarma müdahale durumu."""
    NONE = "none"              # Bilinen bir müdahale yok
    WARNING = "warning"        # Sözlü/yazılı uyarı verildi
    FINE = "fine"               # Para cezası kesildi
    BANNED = "banned"          # Bölgede konaklama tamamen yasaklandı
    UNKNOWN = "unknown"        # Belirsiz / doğrulanmamış bilgi


class CrowdLevel(str, enum.Enum):
    EMPTY = "empty"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    FULL = "full"


class LiveReportType(str, enum.Enum):
    """Süreli canlı saha bildirimi türleri (bkz. app.models.dynamic_status).

    Kararlı makine kodlarıdır - istemci mantığını bunlara dayandırmalı, Türkçe
    metinlere DEĞİL (metinler `app.services.live_status.REPORT_CONFIG`'te). Hepsi
    "bildirildi" niteliğindedir: resmî bir karar değil, topluluk bildirimidir.
    """
    OVERNIGHT_RESTRICTION = "overnight_restriction"          # Geceleme kısıtlaması bildirildi
    OFFICIAL_WARNING = "official_warning"                    # Resmî uyarı bildirildi
    FINE_REPORTED = "fine_reported"                          # Ceza bildirildi
    ROAD_CLOSED = "road_closed"                              # Yol kapalı bildirildi
    ACCESS_DIFFICULT = "access_difficult"                    # Erişim zorlaştı
    FULL = "full"                                            # Alan dolu
    FRESH_WATER_UNAVAILABLE = "fresh_water_unavailable"      # Tatlı su kullanılamıyor
    ELECTRICITY_UNAVAILABLE = "electricity_unavailable"      # Elektrik kullanılamıyor
    GREY_WATER_UNAVAILABLE = "grey_water_unavailable"        # Gri su boşaltma kullanılamıyor
    BLACK_WATER_UNAVAILABLE = "black_water_unavailable"      # Siyah su boşaltma kullanılamıyor
    MUD_RISK = "mud_risk"                                    # Çamur / batma riski
    FIRE_OR_FLOOD_ACCESS_ISSUE = "fire_or_flood_access_issue"  # Yangın/sel vb. nedenle erişim sorunu


class ReportModerationState(str, enum.Enum):
    """Canlı bildirimin moderasyon yaşam döngüsü. `pending` ve `confirmed` AKTİF
    sayılır (süresi dolmadıkça); `rejected` ve `withdrawn` aktif sonuçlardan düşer
    ama satır fiziksel olarak SİLİNMEZ."""
    PENDING = "pending"        # Henüz moderatör incelemesi yok (varsayılan; bildirim yine de görünür)
    CONFIRMED = "confirmed"    # Moderatör onayladı
    REJECTED = "rejected"      # Moderatör reddetti
    WITHDRAWN = "withdrawn"    # Bildiren (veya moderatör) geri çekti


class UserRole(str, enum.Enum):
    """Basit RBAC: sahiplik kontrolü ve moderasyon yetkilerinin dayandığı rol."""
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class VehicleType(str, enum.Enum):
    """Karavan Profili - araç gövde tipi (bkz. app.models.vehicle_profile)."""
    MOTORHOME = "motorhome"          # Motokaravan (A/B/C sınıfı, tek parça şasi)
    CAMPERVAN = "campervan"          # Panelvan / kamperli van
    TRAVEL_TRAILER = "travel_trailer"  # Çekme karavan
    OTHER = "other"


class Drivetrain(str, enum.Enum):
    """Karavan Profili - çekiş tipi. Uyumluluk motorunda `clearance_required`
    (bkz. SpotPassability) ile karşılaştırılır: HIGH_4X4 gerektiren bir
    noktada TWO_WHEEL_DRIVE bir araç "caution"/"not_compatible" üretir."""
    TWO_WHEEL_DRIVE = "4x2"
    FOUR_WHEEL_DRIVE = "4x4"
