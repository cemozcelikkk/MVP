import { useTripStore } from "../store/useTripStore";
import EntrancePhotoUpload from "./EntrancePhotoUpload";
/**
 * Nokta detay içeriği - Keşif Panelinin "detay modu" (bkz. `DiscoverPanel`).
 * Kendi dış kabuğunu/konumlandırmasını TAŞIMAZ (`DiscoverPanel` sağlar) -
 * yalnızca kaydırılabilir bir içerik sütunudur, böylece panel genişliği/
 * mobil drawer davranışı tek yerde yönetilir.
 *
 * Bilgi hiyerarşisi (görev tanımındaki sıralama):
 *  1. Başlık, kategori, genel puan, son güncellik
 *  2. Güncel ciddi saha durumu (LiveStatusSection)
 *  3. Aktif araç için uyumluluk (CompatibilityCard)
 *  4. Ana eylemler: Rotayı Aç / Kaydet / Check-in
 *  5. Fotoğraf özeti
 *  6. Yol ve araç limitleri
 *  7. Olanaklar
 *  8. Saha bilgisinin güncelliği (FieldFreshnessSection)
 *  9. Çok boyutlu değerlendirmeler ve yorumlar (SpotReviewsSection)
 *  10. Durum bildir / düzenle / yönetim eylemleri
 * Kritik olmayan ayrıntılar (6-7) `CollapsibleSection` ile katlanır ki uzun
 * içerikte tüm bölümler aynı görsel ağırlıkta görünmesin.
 */
import axios from "axios";
import {
  ArrowLeft,
  Gauge,
  MapPin,
  Megaphone,
  Navigation,
  Pencil,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useState } from "react";
import {
  checkInSpot,
  deleteSpot,
  resolveMediaUrl,
  toggleSpotFavorite,
  type RoadType,
  type SpotFeature,
  type SpotLiveReports,
  type SpotLiveSummary,
  type LiveReportActionResponse,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { googleMapsDirectionsUrl } from "../lib/format";
import { relativeTimeTr } from "../lib/relativeTime";
import { CATEGORY_LABEL } from "../lib/pinStyle";
import { useAuthStore } from "../store/useAuthStore";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useFavoritesStore } from "../store/useFavoritesStore";
import CompatibilityCard from "./CompatibilityCard";
import ContentReportButton from "./ContentReportButton";
import EditSpotModal from "./EditSpotModal";
import FieldFreshnessSection from "./FieldFreshnessSection";
import LiveStatusSection from "./LiveStatusSection";
import ReportStatusModal from "./ReportStatusModal";
import SpotReviewsSection from "./SpotReviewsSection";
import Button from "./ui/Button";
import { CollapsibleSection, Section } from "./ui/Section";

const ROAD_TYPE_LABEL: Record<RoadType, string> = {
  asphalt: "Asfalt",
  gravel: "Çakıllı",
  dirt: "Toprak",
  rocky: "Taşlık",
};

type CheckInState = "idle" | "locating" | "submitting" | "success";

/** Pin/panel gereksiz yere yeniden çizilmesin diye özet karşılaştırması (`expires_at` hariç). */
function sameLiveSummary(a: SpotLiveSummary | null | undefined, b: SpotLiveSummary): boolean {
  return (
    !!a &&
    a.access === b.access &&
    a.severity === b.severity &&
    a.active_count === b.active_count &&
    a.top_type === b.top_type &&
    a.badge === b.badge &&
    a.types.join(",") === b.types.join(",")
  );
}

// `GeolocationPositionError.code` sabitleri (1/2/3) tüm tarayıcılarda aynı.
const GEO_ERROR_MESSAGES: Record<number, string> = {
  1: "Tarayıcı konum izni verilmedi.",
  2: "Konum bilgisi alınamadı.",
  3: "Konum alma zaman aşımına uğradı.",
};

interface Props {
  spot: SpotFeature | null;
  /** Listeye dön (görev tanımı: "Üstte geri butonu") - spot seçimini temizler, panel açık kalır. */
  onClose: () => void;
  /** Durum bildirimi gibi spot'u yerinde güncelleyen işlemlerden sonra çağrılır. */
  onSpotUpdated?: (feature: SpotFeature) => void;
}

/**
 * Dış kabuk: sadece `spot` var/yok kararını verir. Asıl içerik `SpotDetailPanel`de -
 * `key={spot.properties.id}` ile her yeni spotta yeniden mount edilir, böylece
 * lightbox/favori gibi geçici UI durumu bir efekt gerekmeden sıfırlanmış olur.
 */
export default function SpotDetailSidebar({ spot, onClose, onSpotUpdated }: Props) {
  if (!spot) return null;
  return (
    <SpotDetailPanel key={spot.properties.id} spot={spot} onClose={onClose} onSpotUpdated={onSpotUpdated} />
  );
}

function SpotDetailPanel({
  spot,
  onClose,
  onSpotUpdated,
}: {
  spot: SpotFeature;
  onClose: () => void;
  onSpotUpdated?: (feature: SpotFeature) => void;
}) {
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [isFavorited, setIsFavorited] = useState(false);
  const [favoritePending, setFavoritePending] = useState(false);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [checkInState, setCheckInState] = useState<CheckInState>("idle");
  const [checkInError, setCheckInError] = useState<string | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  // Canlı durum: bildirim/geri çekme sonrası artar -> saha güncelliği ve uyumluluk kartı da yeniden yüklenir.
  const [liveVersion, setLiveVersion] = useState(0);
  const [liveReports, setLiveReports] = useState<SpotLiveReports | null>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const authUser = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const incrementTrustScore = useAuthStore((s) => s.incrementTrustScore);
  const spotDeleted = useCreateSpotStore((s) => s.spotDeleted);
  const spotUpdated = useCreateSpotStore((s) => s.spotUpdated);
  const removeFavoriteLocally = useFavoritesStore((s) => s.removeFavoriteLocally);

  const { properties, geometry } = spot;
  const { passability, amenities } = properties;
  const [lon, lat] = geometry.coordinates;

  // Sahiplik: spot'u oluşturan kullanıcı YA DA moderator/admin düzenleyebilir/silebilir
  // (bkz. backend `spot_service._check_owner_or_privileged` - aynı kural).
  const canManageSpot =
    !!authUser &&
    (authUser.id === properties.created_by ||
      authUser.role === "moderator" ||
      authUser.role === "admin");

  async function handleToggleFavorite() {
    if (favoritePending) return;
    // Oturum yoksa API'ye boşuna 401 attırmak yerine doğrudan giriş modalını aç.
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    setFavoritePending(true);
    setFavoriteError(null);
    try {
      const result = await toggleSpotFavorite(properties.id);
      setIsFavorited(result.is_favorited);
    } catch (err) {
      setFavoriteError(
        axios.isAxiosError(err) && err.response?.status === 401
          ? "Favori için giriş yapmalısın."
          : "Favori güncellenemedi.",
      );
    } finally {
      setFavoritePending(false);
    }
  }

  const routeUrl = googleMapsDirectionsUrl(properties.entry_latitude ?? lat, properties.entry_longitude ?? lon);

  function handleReportClick() {
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    setIsReportModalOpen(true);
  }

  /**
   * Güncel canlı durumu panel + harita pinine yansıtır (sayfa yenilemesi olmadan).
   * `changedByUser`: bildirim/geri çekme sonrası true -> saha güncelliği ve uyumluluk yeniden yüklenir.
   */
  const applyLive = useCallback(
    (live: SpotLiveReports, { changedByUser }: { changedByUser: boolean }) => {
      setLiveReports(live);
      if (changedByUser) setLiveVersion((v) => v + 1);
      if (changedByUser || !sameLiveSummary(spot.properties.live_status, live.summary)) {
        const updated: SpotFeature = {
          ...spot,
          properties: { ...spot.properties, live_status: live.summary },
        };
        onSpotUpdated?.(updated);
        // Rozet, bir sonraki bbox yenilemesini (pan/zoom) beklemeden haritadaki pine anında yansısın.
        spotUpdated(updated);
      }
    },
    [spot, onSpotUpdated, spotUpdated],
  );

  function handleStatusReported(response: LiveReportActionResponse) {
    setIsReportModalOpen(false);
    applyLive(response.live, { changedByUser: true });
  }

  function handleCheckIn() {
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    if (checkInState !== "idle") return;

    if (!("geolocation" in navigator)) {
      setCheckInError("Tarayıcın konum özelliğini desteklemiyor.");
      return;
    }

    setCheckInError(null);
    setCheckInState("locating");
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        setCheckInState("submitting");
        try {
          await checkInSpot(properties.id, position.coords.latitude, position.coords.longitude);
          incrementTrustScore();
          setCheckInState("success");
        } catch (err) {
          setCheckInError(extractErrorMessage(err, "Check-in yapılamadı."));
          setCheckInState("idle");
        }
      },
      (geoError) => {
        setCheckInError(GEO_ERROR_MESSAGES[geoError.code] ?? "Konum alınamadı.");
        setCheckInState("idle");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
  }

  async function handleConfirmDelete() {
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteSpot(properties.id);
      spotDeleted(properties.id); // MapView pinini haritadan kaldırır.
      removeFavoriteLocally(properties.id); // Favorilerdeyse listeden düşür.
      onClose();
    } catch (err) {
      setDeleteError(extractErrorMessage(err, "Nokta silinemedi."));
      setIsDeleting(false);
    }
  }

  function handleUpdated(updated: SpotFeature) {
    setIsEditModalOpen(false);
    onSpotUpdated?.(updated);
    // Kategori değişmiş olabilir - pinin piktogramı haritada anında güncellensin.
    spotUpdated(updated);
  }

  return (
    <>
      <div className="flex h-full flex-col overflow-y-auto">
        {/* --- 0) Geri --- */}
        <button
          type="button"
          onClick={onClose}
          data-testid="back-to-list"
          className="flex min-h-touch shrink-0 items-center gap-1.5 border-b border-border-light px-4 text-sm font-medium text-text-secondary transition-colors hover:text-text-primary"
        >
          <ArrowLeft size={16} />
          Listeye Dön
        </button>

        {/* --- 1) Başlık, kategori, genel puan, son güncellik --- */}
        <Section>
          <h2 className="mb-1.5 font-display text-[28px] font-medium leading-[1.1] text-text-primary">{properties.title}</h2>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="rounded-md bg-surface-secondary px-2 py-0.5 text-xs font-semibold text-text-secondary">
              {CATEGORY_LABEL[properties.category]}
            </span>
            {properties.average_rating != null ? (
              <span className="flex items-center gap-1 text-sm font-semibold text-accent-brass">
                <Star size={13} fill="currentColor" />
                {properties.average_rating.toFixed(1)}
                <span className="font-normal text-text-secondary">({properties.review_count})</span>
              </span>
            ) : (
              <span className="text-xs text-text-secondary">Henüz değerlendirme yok</span>
            )}
            <span className="text-xs text-text-secondary">{relativeTimeTr(properties.updated_at)}</span>
          </div>
          <div className="mt-2 flex items-center gap-3 font-mono text-xs text-text-secondary">
            <span className="flex items-center gap-1">
              <Gauge size={12} />
              {properties.altitude != null ? `${Math.round(properties.altitude)}m` : "—"}
            </span>
            <span>
              {lat.toFixed(4)}, {lon.toFixed(4)}
            </span>
          </div>
        </Section>

        {/* --- 2) Güncel ciddi saha durumu --- */}
        <LiveStatusSection
          spotId={properties.id}
          refreshKey={liveVersion}
          onLive={applyLive}
          onReportClick={handleReportClick}
        />

        {/* --- 3) Aktif araç için uyumluluk --- */}
        <CompatibilityCard spotId={properties.id} refreshKey={liveVersion} />

        {/* --- 4) Ana eylemler --- */}
        <Section>
          {favoriteError ? <p className="mb-2 text-xs text-warning-rust">{favoriteError}</p> : null}
          {checkInError ? <p className="mb-2 text-xs text-warning-rust">{checkInError}</p> : null}
          <a
            href={routeUrl}
            target="_blank"
            rel="noreferrer"
            title="Google Haritalar'da Aç"
            className="flex min-h-touch w-full items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-border-light bg-surface-primary px-4 text-sm font-medium text-text-primary transition-colors hover:bg-surface-secondary"
          >
            <Navigation size={15} />
            Google Haritalar'da Aç
          </a>
          <Button
            variant="secondary"
            className={`mt-2 w-full ${isFavorited ? "!border-accent-brass !bg-accent-brass/10 !text-accent-brass" : ""}`}
            onClick={handleToggleFavorite}
            disabled={favoritePending}
            aria-pressed={isFavorited}
          >
            <Star size={15} fill={isFavorited ? "currentColor" : "none"} />
            {isFavorited ? "Favoride" : "Kaydet"}
          </Button>
          <Button
            variant="secondary"
            className={`mt-2 w-full ${
              checkInState === "success"
                ? "!border-accent-green !bg-accent-green/10 !text-accent-green"
                : checkInState === "locating" || checkInState === "submitting"
                  ? "!border-accent-brass !bg-accent-brass/10 !text-accent-brass"
                  : ""
            }`}
            data-testid="checkin-button"
            onClick={handleCheckIn}
            disabled={checkInState !== "idle"}
          >
            <MapPin size={15} />
            {checkInState === "success"
              ? "✓ Check-in Yapıldı (+1 Güven)"
              : checkInState === "locating"
                ? "Konum Alınıyor…"
                : checkInState === "submitting"
                  ? "Gönderiliyor…"
                  : "Buradayım / Check-in"}
          </Button>
        </Section>

        {/* --- 5) Fotoğraf özeti --- */}
        {properties.photos.length > 0 ? (
          <Section title="Fotoğraflar">
            <div className="flex gap-2 overflow-x-auto">
              {properties.photos.map((photo) => (
                <div key={photo.id} className="shrink-0"><button
                  key={photo.id}
                  type="button"
                  onClick={() => setLightboxUrl(resolveMediaUrl(photo.storage_url))}
                  className="h-20 w-20 shrink-0 overflow-hidden rounded-md border border-border-light"
                >
                  <img
                    src={resolveMediaUrl(photo.thumbnail_url ?? photo.storage_url)}
                    alt={photo.caption ?? properties.title}
                    className="h-full w-full object-cover"
                  />
                </button>{photo.photo_kind==="entrance"&&<p className="text-[10px] text-text-secondary">Giriş / Yaklaşım</p>}<ContentReportButton spotId={properties.id} targetId={photo.id} targetKind="photo" label="Fotoğrafı bildir" /></div>
              ))}
            </div>
          </Section>
        ) : null}

        {/* --- 6) Yol ve araç limitleri --- */}
        <Section title="Yol ve Araç Limitleri">
          <div className="grid grid-cols-2 gap-x-4">
            <SpecItem label="Yol Durumu" value={passability ? ROAD_TYPE_LABEL[passability.road_type] : "—"} />
            <SpecItem
              label="Max Araç Boyu"
              value={passability?.max_vehicle_length != null ? `${passability.max_vehicle_length}m` : "Limitsiz"}
            />
            <SpecItem
              label="4x4 Şartı"
              value={passability?.clearance_required === "high_4x4" ? "Evet" : "Hayır"}
              dotActive={passability?.clearance_required === "high_4x4"}
            />
            <SpecItem
              label="Eğim"
              value={passability?.steep_incline ? "Var" : "Düz"}
              dotActive={!!passability?.steep_incline}
            />
          </div>
        </Section>

        {/* --- 7) Olanaklar --- */}
        <Section title="Olanaklar">
          <div className="grid grid-cols-2 gap-x-4">
            <SpecItem label="Tatlı Su" value={amenities?.fresh_water_thread ? "Var" : "Yok"} dotActive={!!amenities?.fresh_water_thread} />
            <SpecItem label="Siyah Su" value={amenities?.black_water ? "Var" : "Yok"} dotActive={!!amenities?.black_water} />
            <SpecItem label="Gri Su" value={amenities?.grey_water ? "Var" : "Yok"} dotActive={!!amenities?.grey_water} />
            <SpecItem label="Tuvalet (WC)" value={amenities?.has_toilet ? "Var" : "Yok"} dotActive={!!amenities?.has_toilet} />
            <SpecItem label="Çöp Kutusu" value={amenities?.has_trash_bins ? "Var" : "Yok"} dotActive={!!amenities?.has_trash_bins} />
            <SpecItem label="220V Elektrik" value={amenities?.electricity_220v ? "Var" : "Yok"} dotActive={!!amenities?.electricity_220v} />
          </div>
        </Section>
        <Section><Button onClick={()=>{if(!isAuthenticated){openAuthModal();return;}useTripStore.getState().open(spot);}}>Seyahat Planına Ekle</Button></Section>
        <Section><ContentReportButton spotId={properties.id} targetId={properties.id} /></Section>
        <Section title="Geceleme ve Giriş">
          <SpecItem label="Geceleme" value={{allowed:"İzin veriliyor (bildirildi)",not_allowed:"İzin verilmiyor (bildirildi)",unknown:"Bilinmiyor"}[properties.overnight_status ?? "unknown"]} />
          <SpecItem label="Maksimum kalış" value={properties.max_stay_nights ? `${properties.max_stay_nights} gece` : "Bilinmiyor"} />
          <SpecItem label="Özel mülk izni" value={{required:"İzin gerekli",not_required:"İzin gerekmiyor",unknown:"Bilinmiyor"}[properties.private_property_permission ?? "unknown"]} />
          {properties.rule_description && <p className="mt-2 text-sm">{properties.rule_description}</p>}
          {properties.rule_source && <p className="mt-2 text-xs text-text-secondary">Kaynak: {properties.rule_source}</p>}
          {properties.rule_checked_on && <p className="mt-1 text-xs text-text-secondary">Kontrol: {properties.rule_checked_on}</p>}
          {properties.entry_latitude != null && properties.entry_longitude != null && <p className="mt-2 text-xs text-text-secondary">Giriş: {properties.entry_latitude.toFixed(5)}, {properties.entry_longitude.toFixed(5)}</p>}
          {properties.approach_description && <p className="mt-2 whitespace-pre-wrap text-sm">{properties.approach_description}</p>}
          {properties.access_season && <p className="mt-2 text-sm">Mevsimsel erişim: {properties.access_season}</p>}
          <EntrancePhotoUpload spotId={properties.id} onUpdated={updated=>{spotUpdated(updated);onSpotUpdated?.(updated);}} />
          <p className="mt-2 text-xs text-text-secondary">Araç uygunluğu nokta bilgisine dayanır; güzergâhın tamamını değerlendirmez.</p>
        </Section>
        <Section title="Kurallar ve Ücret">
          <SpecItem label="Ücret" value={amenities?.rule_information_known ? (amenities.is_free ? "Ücretsiz (bildirildi)" : "Ücretli (bildirildi)") : "Bilinmiyor"} />
          {amenities?.rule_information_known && !amenities.is_free && amenities.price_description && <p className="mt-2 text-sm text-text-primary">{amenities.price_description}</p>}
          <SpecItem label="Kamp Davranışı" value={amenities?.rule_information_known ? (amenities.camping_behavior_allowed ? "Serbest (bildirildi)" : "İzin verilmiyor (bildirildi)") : "Bilinmiyor"} />
          <p className="mt-2 text-xs text-text-secondary">Tente açma, masa/sandalye dışarı koyma izni.</p>
        </Section>

        {/* --- 8) Saha bilgisinin güncelliği --- */}
        <FieldFreshnessSection
          spotId={properties.id}
          refreshKey={liveVersion}
          checkInJustVerified={checkInState === "success"}
        />

        {/* --- 9) Çok boyutlu değerlendirmeler ve yorumlar --- */}
        <SpotReviewsSection spotId={properties.id} checkInJustVerified={checkInState === "success"} />

        {/* --- 10) Durum bildir / düzenle / yönetim --- */}
        <CollapsibleSection title="Yönetim" subtitle="Durum bildir, düzenle" defaultOpen>
          {deleteError ? <p className="mb-2 text-xs text-warning-rust">{deleteError}</p> : null}
          <div className="flex flex-col gap-2">
            <Button variant="secondary" className="w-full" onClick={handleReportClick}>
              <Megaphone size={15} />
              Durum Bildir
            </Button>

            {canManageSpot ? (
              isConfirmingDelete ? (
                <div className="rounded-md border border-warning-rust p-3">
                  <p className="mb-2 text-sm text-text-primary">Bu noktayı haritadan silmek istediğinize emin misiniz?</p>
                  <div className="flex gap-2">
                    <Button variant="danger-solid" className="flex-1" onClick={handleConfirmDelete} disabled={isDeleting}>
                      {isDeleting ? "Siliniyor…" : "Evet, Sil"}
                    </Button>
                    <Button variant="secondary" className="flex-1" onClick={() => setIsConfirmingDelete(false)} disabled={isDeleting}>
                      Vazgeç
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Button variant="secondary" className="flex-1" onClick={() => setIsEditModalOpen(true)}>
                    <Pencil size={15} />
                    Düzenle
                  </Button>
                  <Button variant="danger" className="flex-1" onClick={() => setIsConfirmingDelete(true)}>
                    <Trash2 size={15} />
                    Sil
                  </Button>
                </div>
              )
            ) : null}
          </div>
        </CollapsibleSection>
      </div>

      {isReportModalOpen ? (
        <ReportStatusModal
          spotId={properties.id}
          myActiveTypes={liveReports?.groups.filter((g) => g.my_report_id).map((g) => g.report_type) ?? []}
          onClose={() => setIsReportModalOpen(false)}
          onReported={handleStatusReported}
        />
      ) : null}

      {isEditModalOpen ? (
        <EditSpotModal spot={spot} onClose={() => setIsEditModalOpen(false)} onUpdated={handleUpdated} />
      ) : null}

      {lightboxUrl ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/85 p-8"
          onClick={() => setLightboxUrl(null)}
        >
          <img src={lightboxUrl} alt={properties.title} className="max-h-full max-w-full object-contain" />
          <button
            type="button"
            onClick={() => setLightboxUrl(null)}
            aria-label="Büyütülmüş görseli kapat"
            className="absolute right-6 top-6 rounded-md border border-border-light bg-surface-primary p-1.5 text-text-primary"
          >
            <X size={18} />
          </button>
        </div>
      ) : null}
    </>
  );
}

function SpecItem({ label, value, dotActive }: { label: string; value: string; dotActive?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-border-light/60 py-1.5 text-sm">
      <span className="text-text-secondary">{label}</span>
      <span className="flex items-center gap-1.5 font-medium text-text-primary">
        {dotActive !== undefined ? (
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${dotActive ? "bg-accent-green" : "bg-neutral-grey/40"}`} aria-hidden />
        ) : null}
        {value}
      </span>
    </div>
  );
}
