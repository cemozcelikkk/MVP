/**
 * Haritanın son bbox sorgusunun sonucu - `MapView` yazar, `DiscoverPanel`
 * (Keşif modu listesi) ve harita durum rozeti aynı veriyi OKUR. Ayrı bir
 * liste API çağrısı YOK: hem pinler hem liste aynı `/spots/bbox` yanıtını
 * paylaşır (bkz. MapView'daki `loadSpotsForCurrentView`).
 *
 * `retryToken`: "Tekrar Dene" eylemi bunu artırır, MapView bir efektle
 * izleyip son bbox'ı yeniden sorgular - store, App.tsx üzerinden prop
 * geçirmeden panel/harita arasındaki bu tetiklemeyi taşır.
 */
import { create } from "zustand";
import type { ExternalStatus, ServicePointFeature, SpotFeature } from "../lib/api";

interface MapDataState {
  features: SpotFeature[];
  /** Aynı görünümdeki hizmet noktaları (restoran/sağlık/WC/duş) - `/service-points`. */
  servicePoints: ServicePointFeature[];
  /** Harici (OpenStreetMap) kaynağın son yanıttaki durumu; hizmet katmanı istenmediyse null. */
  externalStatus: ExternalStatus | null;
  /** Harici veri gösteriliyorsa zorunlu atıf metni (ODbL). */
  attribution: string | null;
  isLoading: boolean;
  errorMessage: string | null;
  retryToken: number;
  setResult: (
    features: SpotFeature[],
    servicePoints?: ServicePointFeature[],
    external?: { status: ExternalStatus | null; attribution: string | null },
  ) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (message: string | null) => void;
  retry: () => void;
}

export const useMapDataStore = create<MapDataState>((set) => ({
  features: [],
  servicePoints: [],
  externalStatus: null,
  attribution: null,
  isLoading: false,
  errorMessage: null,
  retryToken: 0,
  setResult: (features, servicePoints = [], external) =>
    set({
      features,
      servicePoints,
      externalStatus: external?.status ?? null,
      attribution: external?.attribution ?? null,
      errorMessage: null,
    }),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (errorMessage) => set({ errorMessage }),
  retry: () => set((state) => ({ retryToken: state.retryToken + 1 })),
}));
