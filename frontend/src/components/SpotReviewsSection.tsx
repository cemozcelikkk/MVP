import ContentReportButton from "./ContentReportButton";
/**
 * "Saha Değerlendirmesi" bölümü - `SpotDetailSidebar` içinde, genel puanın
 * yanında gösterilir. Kendi verisini kendi çeker (bkz. `CompatibilityCard`
 * ile aynı "self-contained, spotId al, DB'ye kendi git" deseni):
 * `fetchSpotById` boyut özetini + genel puanı, `fetchSpotReviews` yorum
 * listesini getirir. `dimension_ratings` bbox'ta YOK (backend performans
 * kararı), bu yüzden burada AYRICA tekil detay çekilir.
 */
import { BadgeCheck, ChevronDown, ChevronUp, Pencil, Star } from "lucide-react";
import { useEffect, useState } from "react";
import {
  fetchMyReview,
  fetchSpotById,
  fetchSpotReviews,
  type DimensionRatingStat,
  type DimensionRatings,
  type Review,
  type SpotDimensionRatings,
} from "../lib/api";
import { formatDecimalTr } from "../lib/format";
import { VEHICLE_TYPE_LABEL } from "../lib/vehicleLabels";
import { useAuthStore } from "../store/useAuthStore";
import ReviewFormModal from "./ReviewFormModal";

// İlk üçü "en yararlı" olarak öne çıkar (görev tanımı); geri kalanı "Tüm
// değerlendirmeler" altında. `ReviewFormModal`daki sırayla BİREBİR aynı.
const TOP_DIMENSIONS: { key: keyof DimensionRatings; label: string }[] = [
  { key: "safety", label: "Güvenlik" },
  { key: "quietness", label: "Sessizlik" },
  { key: "road_access", label: "Yol Erişimi" },
];
const OTHER_DIMENSIONS: { key: keyof DimensionRatings; label: string }[] = [
  { key: "ground_suitability", label: "Zemin Uygunluğu" },
  { key: "cleanliness", label: "Temizlik" },
  { key: "view", label: "Manzara" },
  { key: "signal", label: "İnternet/Telefon Çekimi" },
];

function DimensionRow({ label, stat }: { label: string; stat: DimensionRatingStat }) {
  return (
    <div className="flex items-center justify-between border-b border-border-muted/60 py-1.5 font-mono text-xs">
      <span className="text-ink-muted">{label}</span>
      {stat.count > 0 ? (
        <span className="text-ink">
          {formatDecimalTr(stat.average ?? 0)} / 5 · {stat.count} değerlendirme
        </span>
      ) : (
        <span className="text-ink-muted">Henüz değerlendirilmedi</span>
      )}
    </div>
  );
}

function formatReviewDate(iso: string): string {
  return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" });
}

function ReviewCard({
  review,
  canEdit,
  onEdit,
}: {
  review: Review;
  canEdit: boolean;
  onEdit: () => void;
}) {
  return (
    <div className="border-b border-border-muted p-4">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 font-mono text-xs text-accent-brass">
          <Star size={12} fill="currentColor" />
          {review.rating} / 5
        </span>
        <span className="font-mono text-[11px] text-ink-muted">{formatReviewDate(review.created_at)}</span>
      </div>

      <ContentReportButton spotId={review.spot_id} targetId={review.id} targetKind="review" label="Yorumu bildir" />
      {review.comment ? <p className="mb-2 text-sm leading-relaxed text-ink">{review.comment}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
        {review.vehicle_snapshot ? (
          <span className="rounded-full border border-border-muted px-2 py-0.5 text-[12px] font-medium text-ink-muted">
            {VEHICLE_TYPE_LABEL[review.vehicle_snapshot.vehicle_type]} ·{" "}
            {formatDecimalTr(review.vehicle_snapshot.length_m)} m
          </span>
        ) : null}
        {review.is_verified_checkin ? (
          <span
            className="flex items-center gap-1 rounded-full border border-accent-green px-2 py-0.5 text-[12px] font-medium text-accent-green"
            title="Yorumu yazan kullanıcı bu noktada bir check-in kaydı bırakmış. Bu, kesin bir GPS kanıtı değil, bir topluluk sinyalidir."
          >
            <BadgeCheck size={11} />
            Yerinde doğrulandı
          </span>
        ) : null}
        {canEdit ? (
          <button
            type="button"
            data-testid="review-edit-button"
            onClick={onEdit}
            className="ml-auto flex items-center gap-1 text-[12px] font-medium text-ink-muted transition-colors hover:text-ink"
          >
            <Pencil size={11} />
            Düzenle
          </button>
        ) : null}
      </div>
    </div>
  );
}

interface Props {
  spotId: string;
  /**
   * Check-in ve yorumlar birbirinden bağımsız bileşenlerdir (bu bileşen
   * kendi verisini kendi çeker) - `SpotDetailSidebar` check-in başarılı
   * olduğunda bunu `true` yapar ki "Yerinde doğrulandı" rozeti bir SONRAKİ
   * manuel yenilemeyi beklemeden hemen görünsün.
   */
  checkInJustVerified?: boolean;
}

export default function SpotReviewsSection({ spotId, checkInJustVerified }: Props) {
  const authUser = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);

  const [dimensionRatings, setDimensionRatings] = useState<SpotDimensionRatings | null>(null);
  const [averageRating, setAverageRating] = useState<number | null>(null);
  const [reviewCount, setReviewCount] = useState(0);
  const [reviews, setReviews] = useState<Review[]>([]);
  // Kullanıcı+nokta başına TEK aktif değerlendirme: varsa "yaz" yerine "düzenle" sunulur.
  const [myReview, setMyReview] = useState<Review | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAllDimensions, setShowAllDimensions] = useState(false);
  const [formState, setFormState] = useState<{ open: boolean; editingReview: Review | null }>({
    open: false,
    editingReview: null,
  });

  async function refresh() {
    setIsLoading(true);
    setError(null);
    try {
      const [spot, reviewList, mine] = await Promise.all([
        fetchSpotById(spotId),
        fetchSpotReviews(spotId),
        isAuthenticated ? fetchMyReview(spotId).catch(() => null) : Promise.resolve(null),
      ]);
      setMyReview(mine);
      setDimensionRatings(spot.properties.dimension_ratings ?? null);
      setAverageRating(spot.properties.average_rating);
      setReviewCount(spot.properties.review_count);
      setReviews(reviewList);
    } catch {
      setError("Değerlendirmeler yüklenemedi.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spotId, checkInJustVerified, isAuthenticated]);

  function handleWriteClick() {
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    // Zaten aktif bir değerlendirmesi varsa yeni yazmak yerine mevcut olanı düzenlet (backend ikinciyi 409 ile reddeder).
    setFormState({ open: true, editingReview: myReview });
  }

  function handleSaved() {
    setFormState({ open: false, editingReview: null });
    refresh();
  }

  const canEditReview = (review: Review) =>
    !!authUser && (authUser.id === review.user_id || authUser.role === "moderator" || authUser.role === "admin");

  return (
    <div className="border-b border-border-muted p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="font-display text-[17px] font-medium text-text-primary">Saha Değerlendirmesi</p>
        <button
          type="button"
          onClick={handleWriteClick}
          className="text-[13px] font-medium text-accent-brass transition-colors hover:text-ink"
        >
          {myReview ? "Değerlendirmemi Düzenle" : "+ Değerlendirme Yaz"}
        </button>
      </div>

      {/* Genel puan - mevcut alan korunuyor, sadece ilk kez burada gösteriliyor. */}
      <div className="mb-3 flex items-center gap-1.5 font-mono text-sm">
        <Star size={14} className="text-accent-brass" fill={averageRating != null ? "currentColor" : "none"} />
        {averageRating != null ? (
          <span className="text-ink">
            {formatDecimalTr(averageRating)} / 5 <span className="text-ink-muted">· {reviewCount} değerlendirme</span>
          </span>
        ) : (
          <span className="text-ink-muted">Henüz değerlendirilmedi</span>
        )}
      </div>

      {isLoading ? (
        <p className="font-mono text-xs text-ink-muted">Yükleniyor…</p>
      ) : error ? (
        <p className="font-mono text-xs text-accent-rust">{error}</p>
      ) : (
        <>
          <div className="mb-1">
            {TOP_DIMENSIONS.map(({ key, label }) => (
              <DimensionRow
                key={key}
                label={label}
                stat={dimensionRatings?.[key] ?? { average: null, count: 0 }}
              />
            ))}
          </div>

          <button
            type="button"
            onClick={() => setShowAllDimensions((v) => !v)}
            className="mb-2 mt-1 flex items-center gap-1 text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
          >
            {showAllDimensions ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Tüm Değerlendirmeler
          </button>

          {showAllDimensions ? (
            <div className="mb-2 border-t border-border-muted/60 pt-1">
              {OTHER_DIMENSIONS.map(({ key, label }) => (
                <DimensionRow
                  key={key}
                  label={label}
                  stat={dimensionRatings?.[key] ?? { average: null, count: 0 }}
                />
              ))}
            </div>
          ) : null}

          {/* --- Yorum listesi --- */}
          {reviews.length > 0 ? (
            <div className="-mx-4 mt-2 border-t border-border-muted">
              {reviews.map((review) => (
                <ReviewCard
                  key={review.id}
                  review={review}
                  canEdit={canEditReview(review)}
                  onEdit={() => setFormState({ open: true, editingReview: review })}
                />
              ))}
            </div>
          ) : (
            <p className="mt-2 font-mono text-xs text-ink-muted">Henüz yorum yapılmamış.</p>
          )}
        </>
      )}

      {formState.open ? (
        <ReviewFormModal
          spotId={spotId}
          editingReview={formState.editingReview}
          onClose={() => setFormState({ open: false, editingReview: null })}
          onSaved={handleSaved}
        />
      ) : null}
    </div>
  );
}
