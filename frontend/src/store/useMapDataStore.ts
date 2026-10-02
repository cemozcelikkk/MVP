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
import type { SpotFeature } from "../lib/api";

interface MapDataState {
  features: SpotFeature[];
  isLoading: boolean;
  errorMessage: string | null;
  retryToken: number;
  setResult: (features: SpotFeature[]) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (message: string | null) => void;
  retry: () => void;
}

export const useMapDataStore = create<MapDataState>((set) => ({
  features: [],
  isLoading: false,
  errorMessage: null,
  retryToken: 0,
  setResult: (features) => set({ features, errorMessage: null }),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (errorMessage) => set({ errorMessage }),
  retry: () => set((state) => ({ retryToken: state.retryToken + 1 })),
}));
