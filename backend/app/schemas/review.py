"""
`reviews` Pydantic şemaları.

`DimensionRatings`in alan adları `app.models.review.DIMENSION_KEYS` ile
BİREBİR eşleşir (sütun adı `<key>_rating`, API alan adı `<key>`) - ikisi
arasındaki dönüşüm `review_service`de tek bir döngüyle yapılır, burada
tekrar edilmez.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import VehicleType


class DimensionRatings(BaseModel):
    """
    Yedi sabit ölçüt, hepsi opsiyonel (1-5 veya boş/None - "Değerlendirmedim").
    İlk üçü ("en yararlı üç ölçüt") kasıtlı olarak en üstte tanımlı;
    frontend'in "öne çıkan 3" gösterimiyle aynı sırayı yansıtır.
    """

    safety: int | None = Field(default=None, ge=1, le=5, description="Geceleme güvenliği")
    quietness: int | None = Field(default=None, ge=1, le=5, description="Sessizlik")
    road_access: int | None = Field(default=None, ge=1, le=5, description="Yol erişimi")
    ground_suitability: int | None = Field(default=None, ge=1, le=5, description="Zemin uygunluğu")
    cleanliness: int | None = Field(default=None, ge=1, le=5, description="Temizlik")
    view: int | None = Field(default=None, ge=1, le=5, description="Manzara")
    signal: int | None = Field(default=None, ge=1, le=5, description="İnternet/telefon çekimi")


class DimensionRatingStat(BaseModel):
    """Bir ölçütün spot genelindeki özeti - `average`, TEK kişi puanlamış olsa bile
    çok sayıda kişinin ortalamasıyla aynı biçimde sunulmaz; `count` bunu ayırt eder
    (bkz. `SpotDimensionRatings` ve frontend'deki gösterim kuralı)."""

    average: float | None = None
    count: int = 0


class SpotDimensionRatings(BaseModel):
    """`GET /spots/{id}` yanıtındaki spot-geneli boyut özeti - bkz. `review_service.get_spot_dimension_ratings`."""

    safety: DimensionRatingStat
    quietness: DimensionRatingStat
    road_access: DimensionRatingStat
    ground_suitability: DimensionRatingStat
    cleanliness: DimensionRatingStat
    view: DimensionRatingStat
    signal: DimensionRatingStat


class ReviewVehicleSnapshot(BaseModel):
    """
    Yorumun yazıldığı ANDAKİ araç türü/uzunluğu - bkz. `app.models.review`
    docstring'i. Kasıtlı olarak SADECE bunlar: araç adı, plaka, profil ID'si
    YOK (gizlilik).
    """

    vehicle_type: VehicleType
    length_m: float


class ReviewBase(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewCreate(ReviewBase):
    dimension_ratings: DimensionRatings | None = None


class ReviewUpdate(BaseModel):
    """
    PATCH gövdesi - `rating`/`comment` PATCH semantiğinde (None = değiştirme,
    bkz. `SpotUpdate`ile aynı kural). `dimension_ratings` FARKLI davranır:
    gönderilen (JSON'da GERÇEKTEN yer alan) her alt-alan - `null` dahil -
    uygulanır, böylece bir ölçüt "Değerlendirmedim"e geri döndürülebilir;
    hiç bahsedilmeyen alt-alanlar dokunulmadan kalır (bkz.
    `review_service._apply_dimension_ratings_update`, `exclude_unset` kullanır).
    """

    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    dimension_ratings: DimensionRatings | None = None


class ReviewRead(ReviewBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    spot_id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    dimension_ratings: DimensionRatings
    vehicle_snapshot: ReviewVehicleSnapshot | None = None
    # Yorumun yazarının bu spot'ta GEÇERLİ bir check-in kaydı var mı -
    # DİNAMİK hesaplanır (review'a snapshot edilmez), bkz.
    # `review_service.get_reviews_for_spot` ve endpoint docstring'i:
    # kesin GPS kanıtı DEĞİLDİR, sadece bir topluluk sinyalidir.
    is_verified_checkin: bool = False
