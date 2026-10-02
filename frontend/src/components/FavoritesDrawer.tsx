/**
 * Sağdan açılan "Kaydedilenler / Seyahat Defteri" çekmecesi.
 *
 * Kasıtlı olarak tam ekran bir backdrop YOK (masaüstünde): sol taraftaki
 * Keşif Paneli ile aynı anda açık kalabilmeli - görünmez bir backdrop, aynı
 * z katmanındaki panelin tıklamalarını da yutardı. Dar ekranda (`sm:` altı)
 * tam genişlik alır ve bir scrim eklenir (aksi halde haritayı tamamen kaplar).
 */
import { Star, X } from "lucide-react";
import { fetchSpotById, type SpotFeature, type SpotSummary } from "../lib/api";
import { CATEGORY_LABEL } from "../lib/pinStyle";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useFavoritesStore } from "../store/useFavoritesStore";
import Button from "./ui/Button";

interface Props {
  /** `[Haritada Göster]` sonrası - App.tsx bunu `setSelectedSpot`e bağlar. */
  onShowOnMap?: (feature: SpotFeature) => void;
}

export default function FavoritesDrawer({ onShowOnMap }: Props) {
  const isDrawerOpen = useFavoritesStore((s) => s.isDrawerOpen);
  const favorites = useFavoritesStore((s) => s.favorites);
  const isLoading = useFavoritesStore((s) => s.isLoading);
  const error = useFavoritesStore((s) => s.error);
  const closeDrawer = useFavoritesStore((s) => s.closeDrawer);
  const removeFavorite = useFavoritesStore((s) => s.removeFavorite);
  const focusSpot = useCreateSpotStore((s) => s.focusSpot);

  if (!isDrawerOpen) return null;

  async function handleShowOnMap(spotId: string) {
    closeDrawer();
    try {
      // Favori listesi sadece `SpotSummary` (hafif) taşıyor - detay paneli
      // passability/amenities/photos/latest_status beklediği için tam
      // `SpotFeature`'ı ayrıca çekiyoruz (bkz. CreateSpotModal'daki aynı desen).
      const feature = await fetchSpotById(spotId);
      focusSpot(feature);
      onShowOnMap?.(feature);
    } catch {
      // Spot muhtemelen silinmiş - sessizce yut, çekmece zaten kapandı.
    }
  }

  return (
    <>
      <div className="animate-overlay-fade-in fixed inset-0 z-20 bg-text-primary/40 sm:hidden" onClick={closeDrawer} aria-hidden />
      <aside className="animate-sheet-rise-in fixed inset-y-0 right-0 z-30 flex w-[88vw] max-w-[380px] flex-col border-l border-border-light bg-surface-primary text-text-primary shadow-panel sm:absolute">
        <div className="flex shrink-0 items-center justify-between border-b border-border-light p-4">
          <p className="text-sm font-semibold text-text-primary">Kaydedilenler</p>
          <button
            type="button"
            onClick={closeDrawer}
            aria-label="Kapat"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary"
          >
            <X size={17} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <p className="p-4 text-sm text-text-secondary">Yükleniyor…</p>
          ) : error ? (
            <p className="p-4 text-sm text-warning-rust">{error}</p>
          ) : favorites.length === 0 ? (
            <p className="p-4 text-sm leading-relaxed text-text-secondary">
              Henüz kaydedilmiş bir nokta yok. Sahada beğendiğiniz yerleri detay panelinden favorilere ekleyebilirsiniz.
            </p>
          ) : (
            favorites.map((spot) => (
              <FavoriteCard key={spot.id} spot={spot} onShowOnMap={() => handleShowOnMap(spot.id)} onRemove={() => removeFavorite(spot.id)} />
            ))
          )}
        </div>
      </aside>
    </>
  );
}

function FavoriteCard({ spot, onShowOnMap, onRemove }: { spot: SpotSummary; onShowOnMap: () => void; onRemove: () => void }) {
  return (
    <div className="border-b border-border-light p-4">
      <p className="mb-1.5 text-sm font-semibold text-text-primary">{spot.title}</p>

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-surface-secondary px-2 py-0.5 text-xs font-semibold text-text-secondary">
          {CATEGORY_LABEL[spot.category]}
        </span>
        {spot.average_rating != null ? (
          <span className="flex items-center gap-1 text-xs font-semibold text-accent-brass">
            <Star size={12} fill="currentColor" />
            {spot.average_rating.toFixed(1)}
          </span>
        ) : null}
      </div>

      <p className="mb-3 font-mono text-xs text-text-secondary">
        {spot.latitude.toFixed(4)}, {spot.longitude.toFixed(4)}
      </p>

      <div className="flex gap-2">
        <Button variant="secondary" size="sm" className="flex-1" onClick={onShowOnMap}>
          Haritada Göster
        </Button>
        <Button variant="secondary" size="sm" className="!text-warning-rust" onClick={onRemove}>
          Kaldır
        </Button>
      </div>
    </div>
  );
}
