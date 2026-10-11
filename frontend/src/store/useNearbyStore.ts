/**
 * "Yakınımdakiler" - hizmet noktalarının hangi merkeze göre listeleneceği.
 *
 * - `viewport` (varsayılan): haritanın görünür alanı; harita kaydırıldıkça güncellenir.
 * - `me`: kullanıcının GPS konumu çevresi (`radiusM`), yakından uzağa sıralı.
 * - `spot`: seçili kamp noktasının çevresi - "bu kamp alanındayken yakında ne var?".
 *
 * `MapView` bu durumu okuyup hizmet katmanını `/service-points` (bbox) veya
 * `/service-points/nearby` (merkez + yarıçap) ile doldurur ve merkez modunda
 * yarıçap dairesini çizer; Keşif paneli aynı sonucu mesafeleriyle listeler.
 */
import { create } from "zustand";

export type NearbyMode = "viewport" | "me" | "spot";

export const NEARBY_RADIUS_OPTIONS = [2000, 5000, 10000, 20000] as const;

interface NearbyState {
  mode: NearbyMode;
  /** [boylam, enlem] - `me`/`spot` modunda merkez. */
  center: [number, number] | null;
  /** Merkezin kısa adı (ör. kamp noktası başlığı) - arayüzde "X çevresi". */
  centerLabel: string | null;
  radiusM: number;
  isLocating: boolean;
  error: string | null;
  /** Merkez her değiştiğinde artar - harita bir kez o daireye sığdırılır. */
  fitToken: number;

  showViewport: () => void;
  locateMe: () => void;
  aroundSpot: (center: [number, number], label: string) => void;
  setRadius: (radiusM: number) => void;
  clearError: () => void;
}

export const useNearbyStore = create<NearbyState>((set) => ({
  mode: "viewport",
  center: null,
  centerLabel: null,
  radiusM: 5000,
  isLocating: false,
  error: null,
  fitToken: 0,

  showViewport: () => set({ mode: "viewport", center: null, centerLabel: null, error: null }),

  locateMe: () => {
    if (!navigator.geolocation) {
      set({ error: "Tarayıcınız konum hizmetlerini desteklemiyor." });
      return;
    }
    set({ isLocating: true, error: null });
    navigator.geolocation.getCurrentPosition(
      (position) =>
        set((state) => ({
          mode: "me",
          center: [position.coords.longitude, position.coords.latitude],
          centerLabel: "Konumunuz",
          isLocating: false,
          fitToken: state.fitToken + 1,
        })),
      (error) =>
        set({
          isLocating: false,
          error:
            error.code === error.PERMISSION_DENIED
              ? "Konum izni verilmedi. Harita alanındaki noktalar gösteriliyor."
              : "Konum alınamadı. Harita alanındaki noktalar gösteriliyor.",
        }),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  },

  aroundSpot: (center, label) =>
    set((state) => ({ mode: "spot", center, centerLabel: label, error: null, fitToken: state.fitToken + 1 })),

  setRadius: (radiusM) => set((state) => ({ radiusM, fitToken: state.fitToken + 1 })),

  clearError: () => set({ error: null }),
}));
