import TripPlannerModal from "./components/TripPlannerModal";
import { useEffect, useState } from "react";
import AppTopBar from "./components/AppTopBar";
import AccountLinkHandler from "./components/AccountLinkHandler";
import AuthModal from "./components/AuthModal";
import CreateSpotModal from "./components/CreateSpotModal";
import DiscoverPanel from "./components/DiscoverPanel";
import ExploreHero from "./components/ExploreHero";
import FavoritesDrawer from "./components/FavoritesDrawer";
import MapView from "./components/MapView";
import ModerationPanel from "./components/ModerationPanel";
import VehicleProfilesModal from "./components/VehicleProfilesModal";
import type { SpotFeature } from "./lib/api";
import { useAuthStore } from "./store/useAuthStore";
import { useCreateSpotStore } from "./store/useCreateSpotStore";
import { usePanelStore } from "./store/usePanelStore";

// Aynı sekmede hero bir kez gösterilir; yenilemede kullanıcı doğrudan
// haritaya döner. Depolama erişilemezse (gizli pencere vb.) hero yine görünür.
const HERO_SEEN_KEY = "karavantr_hero_seen";

function readHeroSeen(): boolean {
  try {
    return sessionStorage.getItem(HERO_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function App() {
  const [isHeroVisible, setIsHeroVisible] = useState(() => !readHeroSeen() && !window.location.hash.includes("account_action"));
  const [selectedSpot, setSelectedSpot] = useState<SpotFeature | null>(null);
  const restoreSession = useAuthStore((s) => s.restoreSession);
  const isPickingLocation = useCreateSpotStore((s) => s.isPickingLocation);

  // Sayfa açılışında localStorage'daki token varsa `/auth/me` ile doğrula.
  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  // Konum seçim modundayken Escape ile iptal.
  useEffect(() => {
    if (!isPickingLocation) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") useCreateSpotStore.getState().cancelPicking();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPickingLocation]);

  /**
   * Bir nokta seçilince (pin tıklaması, liste satırı, favoriden "Haritada
   * Göster", yeni oluşturma) keşif panelini de açar - panel kapalıyken
   * (özellikle dar ekranda varsayılan durum) seçim sessizce görünmez
   * kalmasın diye. `null` (listeye dönüş/kapatma) paneli KAPATMAZ.
   */
  function handleSelectSpot(feature: SpotFeature | null) {
    setSelectedSpot(feature);
    if (feature) usePanelStore.getState().open();
  }

  function handleEnterMap() {
    setIsHeroVisible(false);
    try {
      sessionStorage.setItem(HERO_SEEN_KEY, "1");
    } catch {
      // Depolama yoksa hero bir sonraki açılışta yeniden görünür - sorun değil.
    }
  }

  return (
    <>
      {/* Hero açıkken arkadaki uygulama kurulur (harita/bbox beklemez) ama odak ve tıklama almaz. */}
      <div
        inert={isHeroVisible}
        className="flex h-screen w-screen flex-col overflow-hidden bg-surface-primary font-sans text-text-primary"
      >
        <AppTopBar />
        <div className="relative flex flex-1 overflow-hidden">
          <DiscoverPanel selectedSpot={selectedSpot} onSelectSpot={handleSelectSpot} onSpotUpdated={setSelectedSpot} />
          <MapView onSelectSpot={handleSelectSpot} selectedSpotId={selectedSpot?.properties.id ?? null} />
        </div>

        <AccountLinkHandler />
        <AuthModal />
        <CreateSpotModal onCreated={handleSelectSpot} />
        <FavoritesDrawer onShowOnMap={handleSelectSpot} />
        <VehicleProfilesModal />
        <TripPlannerModal />
        <ModerationPanel />
      </div>
      {isHeroVisible ? <ExploreHero onEnter={handleEnterMap} /> : null}
    </>
  );
}

export default App;
