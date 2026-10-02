/**
 * Sol keşif panelinin açık/kapalı durumu - `AppTopBar` (aç/kapa düğmesi),
 * `MapView` (haritayı yeniden boyutlandırma / "Nokta Ekle" konumu) ve
 * `DiscoverPanel` arasında paylaşılan, App.tsx üzerinden prop geçirmeden
 * kullanılan cross-cutting UI durumu (bkz. `useFilterStore`/`useCreateSpotStore`
 * ile aynı desen).
 *
 * Panelin MODU (keşif/detay) ayrı bir alan DEĞİL - App.tsx'teki
 * `selectedSpot` durumundan türetilir (spot seçiliyse detay modu). Burada
 * yalnızca "panel görünür mü" tutuluyor ki kapalıyken harita tüm alanı
 * kaplasın ve tekrar açılışta kullanıcının kaldığı moda (liste ya da
 * seçili spot) doğal olarak dönülsün.
 */
import { create } from "zustand";

interface PanelState {
  isOpen: boolean;
  toggle: () => void;
  open: () => void;
  close: () => void;
}

// Masaüstünde panel varsayılan açık (birincil gezinme); dar ekranda panel bir
// drawer'a dönüştüğü için varsayılan kapalı - harita ilk açılışta tam ekran
// gelir, kullanıcı "Keşfet" ya da bir pine dokunarak açar (bkz. DiscoverPanel).
const DESKTOP_BREAKPOINT_PX = 1024;
const startsOpen = typeof window === "undefined" || window.innerWidth >= DESKTOP_BREAKPOINT_PX;

export const usePanelStore = create<PanelState>((set) => ({
  isOpen: startsOpen,
  toggle: () => set((state) => ({ isOpen: !state.isOpen })),
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
}));
