/**
 * Sol keşif paneli - iki modu tek kabukta barındırır: nokta seçili değilse
 * Keşif modu (`ExploreList`), seçiliyse Nokta Detay modu (`SpotDetailSidebar`
 * içeriği). Mod, App.tsx'teki `selectedSpot` durumundan TÜRETİLİR - ayrı bir
 * "mod" state'i yok (bkz. `usePanelStore` docstring'i).
 *
 * Masaüstünde (`lg:` ve üstü) haritanın YANINDA akışa dahil bir sütun -
 * kapanınca genişliği 0'a iner ve `MapView` `map.resize()` çağırarak
 * haritayı gerçekten büyütür (overlay/padding hilesi YOK, bkz. MapView).
 * Dar ekranda haritanın ÜZERİNDEN açılan tam yükseklikli bir drawer'a
 * dönüşür (scrim ile), harita düzeni etkilenmez.
 */
import type { SpotFeature } from "../lib/api";
import { usePanelStore } from "../store/usePanelStore";
import SpotSearch from "./SpotSearch";
import ExploreList from "./ExploreList";
import SpotDetailSidebar from "./SpotDetailSidebar";

interface Props {
  selectedSpot: SpotFeature | null;
  onSelectSpot: (feature: SpotFeature | null) => void;
  onSpotUpdated?: (feature: SpotFeature) => void;
}

export default function DiscoverPanel({ selectedSpot, onSelectSpot, onSpotUpdated }: Props) {
  const isOpen = usePanelStore((s) => s.isOpen);
  const closePanel = usePanelStore((s) => s.close);

  return (
    <>
      {/* Dar ekran scrim - panele dokunmadan dışına tıklayınca kapat. `lg:hidden` ile masaüstünde hiç render edilmiş gibi davranır. */}
      {isOpen ? (
        <div
          className="animate-overlay-fade-in fixed inset-0 top-14 z-10 bg-map-bg/50 lg:hidden"
          onClick={closePanel}
          aria-hidden
        />
      ) : null}

      <div
        data-testid="discover-panel"
        data-open={isOpen}
        className={[
          "z-20 flex shrink-0 flex-col overflow-hidden border-r border-border-light/70 bg-surface-primary shadow-panel",
          "fixed inset-y-0 left-0 top-14 w-[88vw] max-w-[380px] transition-transform duration-300 ease-in-out",
          "lg:static lg:top-auto lg:max-w-none lg:translate-x-0 lg:shadow-none lg:transition-[width] lg:duration-300 lg:ease-in-out",
          isOpen ? "translate-x-0 lg:w-[380px] xl:w-[400px]" : "-translate-x-full shadow-none lg:w-0 lg:border-r-0",
        ].join(" ")}
      >
        <div className="h-full w-[88vw] max-w-[380px] lg:w-[380px] xl:w-[400px]">
          {selectedSpot ? (
            <SpotDetailSidebar spot={selectedSpot} onClose={() => onSelectSpot(null)} onSpotUpdated={onSpotUpdated} />
          ) : (
            <div className="h-full overflow-y-auto"><SpotSearch onSelect={onSelectSpot} /><ExploreList onSelect={onSelectSpot} /></div>
          )}
        </div>
      </div>
    </>
  );
}
