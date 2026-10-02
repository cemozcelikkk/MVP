/**
 * Kullanıcının karavan/araç profilleri: "Araçlarım" modalının görünürlüğü,
 * profil listesi ve CRUD/aktifleştirme işlemleri.
 *
 * `SpotDetailSidebar`'daki `CompatibilityCard` (kardeş olmayan bir bileşen)
 * ile `AuthWidget`/`VehicleProfilesModal` arasında prop-drilling olmadan
 * paylaşılabilmesi için (bkz. `useFavoritesStore` ile aynı desen) bir
 * zustand store. `profiles` listesindeki `is_active` bayrağı, uyumluluk
 * kartının "hangi araç aktif" bilgisini AYRI bir istek atmadan okuyabilmesi
 * için tek doğruluk kaynağıdır.
 */
import { create } from "zustand";
import {
  activateVehicleProfile,
  createVehicleProfile,
  deleteVehicleProfile,
  listVehicleProfiles,
  updateVehicleProfile,
  type VehicleProfile,
  type VehicleProfilePayload,
  type VehicleProfileUpdatePayload,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";

interface VehicleProfileState {
  isModalOpen: boolean;
  /** Modal açılırken doğrudan ekleme formuyla mı başlasın (boş durumdaki "+ Araç Ekle" gibi). */
  startInAddMode: boolean;
  profiles: VehicleProfile[];
  isLoading: boolean;
  /** İlk fetch hiç yapılmadı mı? `CompatibilityCard`'ın gereksiz tekrar istek atmaması için. */
  hasFetched: boolean;
  error: string | null;

  openModal: (options?: { startInAddMode?: boolean }) => void;
  closeModal: () => void;
  fetchProfiles: () => Promise<void>;
  /**
   * Kullanıcıya özel TÜM state'i sıfırlar - `useAuthStore.logout()`
   * tarafından çağrılır ki bir sonraki kullanıcı önceki oturumun araç
   * listesini/aktif aracını asla görmesin (bkz. görev tanımı: "Login/logout
   * olduğunda kullanıcıya ait araç state'ini doğru temizle").
   */
  reset: () => void;
  /** Hatayı ÇAĞIRAN TARAFA fırlatır (formda satır içi Türkçe hata göstermek için) - burada yutulmaz. */
  addProfile: (payload: VehicleProfilePayload) => Promise<VehicleProfile>;
  editProfile: (profileId: string, payload: VehicleProfileUpdatePayload) => Promise<VehicleProfile>;
  removeProfile: (profileId: string) => Promise<void>;
  activateProfile: (profileId: string) => Promise<void>;
}

export const useVehicleProfileStore = create<VehicleProfileState>((set, get) => ({
  isModalOpen: false,
  startInAddMode: false,
  profiles: [],
  isLoading: false,
  hasFetched: false,
  error: null,

  openModal: (options) => {
    set({ isModalOpen: true, startInAddMode: !!options?.startInAddMode });
    get().fetchProfiles();
  },
  closeModal: () => set({ isModalOpen: false }),

  fetchProfiles: async () => {
    set({ isLoading: true, error: null });
    try {
      const profiles = await listVehicleProfiles();
      set({ profiles, isLoading: false, hasFetched: true });
    } catch (err) {
      set({
        isLoading: false,
        hasFetched: true,
        error: extractErrorMessage(err, "Araç profilleri yüklenemedi."),
      });
    }
  },

  addProfile: async (payload) => {
    const created = await createVehicleProfile(payload);
    set((state) => ({
      profiles: created.is_active
        ? [created, ...state.profiles.map((p) => ({ ...p, is_active: false }))]
        : [...state.profiles, created],
    }));
    return created;
  },

  editProfile: async (profileId, payload) => {
    const updated = await updateVehicleProfile(profileId, payload);
    set((state) => ({
      profiles: state.profiles.map((p) => {
        if (p.id === updated.id) return updated;
        return updated.is_active ? { ...p, is_active: false } : p;
      }),
    }));
    return updated;
  },

  removeProfile: async (profileId) => {
    await deleteVehicleProfile(profileId);
    set((state) => ({ profiles: state.profiles.filter((p) => p.id !== profileId) }));
  },

  activateProfile: async (profileId) => {
    const updated = await activateVehicleProfile(profileId);
    set((state) => ({
      profiles: state.profiles.map((p) => ({ ...p, is_active: p.id === updated.id })),
    }));
  },

  reset: () =>
    set({
      isModalOpen: false,
      startInAddMode: false,
      profiles: [],
      isLoading: false,
      hasFetched: false,
      error: null,
    }),
}));
