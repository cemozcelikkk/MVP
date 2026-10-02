"""
Domain enum'ları.

Bu enum'lar hem SQLAlchemy tarafında native PostgreSQL ENUM tipi olarak,
hem de Pydantic şemalarında doğrulama için kullanılır (app.schemas.*).
"""
import enum


class SpotCategory(str, enum.Enum):
    WILD_CAMPING = "wild_camping"          # Doğa/arazi kampı, resmi olmayan alan
    CAMPSITE = "campsite"                  # Ücretli/ücretsiz düzenlenmiş kamp alanı
    SANISTATION_ONLY = "sanistation_only"  # Sadece gri/siyah su boşaltma istasyonu
    DAY_PARKING = "day_parking"            # Sadece gündüz kullanımına uygun otopark
    FARM_STAY = "farm_stay"                # Çiftlik/bağ-bahçe konaklaması (HarvestHost tipi)


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
