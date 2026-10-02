/**
 * Kullanıcının favorilediği spot'lar: çekmece görünürlüğü, liste ve hızlı
 * üyelik kontrolü için bir id kümesi (`favoriteIds` - MapView'daki
 * "Sadece Favorilerim" filtresi bunu kullanıyor).
 *
 * `MapView`/`FilterBar` gibi App.tsx'te kardeş olmayan bileşenlerin veriyi
 * prop-drilling olmadan paylaşabilmesi için (bkz. `useFilterStore`/
 * `useCreateSpotStore` ile aynı desen) bir zustand store.
 */
import { create } from "zustand";
import { getUserFavorites, toggleSpotFavorite, type SpotSummary } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";

interface FavoritesState {
  reset: () => void;
  requestVersion: number;
  isDrawerOpen: boolean;
  favorites: SpotSummary[];
  favoriteIds: Set<string>;
  isLoading: boolean;
  error: string | null;

  /** Çekmeceyi açar ve güncel listeyi çeker. */
  openDrawer: () => void;
  closeDrawer: () => void;
  fetchFavorites: () => Promise<void>;
  /** `[Kaldır]` - iyimser (optimistic) günceller, başarısız olursa geri alır. */
  removeFavorite: (spotId: string) => Promise<void>;
  /**
   * API çağrısı YAPMADAN listeden düşürür - spot'un kendisi silindiğinde
   * (`SpotDetailSidebar`daki `[Sil]`) kullanılır; o noktada zaten
   * `DELETE /spots/{id}` çağrılmış oluyor, ayrıca favori toggle'ı denemek
   * (spot artık yok) gereksiz bir 404'e yol açardı.
   */
  removeFavoriteLocally: (spotId: string) => void;
}

export const useFavoritesStore = create<FavoritesState>((set, get) => ({
  requestVersion: 0,
  reset: () => set(state=>({requestVersion:state.requestVersion+1,isDrawerOpen:false,favorites:[],favoriteIds:new Set(),isLoading:false,error:null})),
  isDrawerOpen: false,
  favorites: [],
  favoriteIds: new Set(),
  isLoading: false,
  error: null,

  openDrawer: () => {
    set({ isDrawerOpen: true });
    get().fetchFavorites();
  },
  closeDrawer: () => set({ isDrawerOpen: false }),

  fetchFavorites: async () => {
    const requestVersion = get().requestVersion;
    set({ isLoading: true, error: null });
    try {
      const favorites = await getUserFavorites();
      if(get().requestVersion !== requestVersion) return;
      set({ favorites, favoriteIds: new Set(favorites.map((f) => f.id)), isLoading: false });
    } catch (err) {
      if(get().requestVersion !== requestVersion) return;
      set({ isLoading: false, error: extractErrorMessage(err, "Favoriler yüklenemedi.") });
    }
  },

  removeFavorite: async (spotId) => {
    const { favorites,requestVersion } = get();
    const next = favorites.filter((f) => f.id !== spotId);
    set({ favorites: next, favoriteIds: new Set(next.map((f) => f.id)) });
    try {
      await toggleSpotFavorite(spotId);
    } catch (err) {
      if(get().requestVersion !== requestVersion) return;
      // Başarısızsa listeyi geri al - sessizce tutarsız kalmasın.
      set({ favorites, favoriteIds: new Set(favorites.map((f) => f.id)) });
      set({ error: extractErrorMessage(err, "Favori kaldırılamadı.") });
    }
  },

  removeFavoriteLocally: (spotId) => {
    const next = get().favorites.filter((f) => f.id !== spotId);
    set({ favorites: next, favoriteIds: new Set(next.map((f) => f.id)) });
  },
}));
