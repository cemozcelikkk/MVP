import { useFavoritesStore } from "./useFavoritesStore";
import { useTripStore } from "./useTripStore";
/**
 * Kimlik doğrulama durumu ve giriş/kayıt/çıkış akışları.
 *
 * Modal görünürlüğü de kasıtlı olarak burada tutuluyor (`isAuthModalOpen`) -
 * `SpotDetailSidebar` gibi App.tsx'te kardeş olmayan bileşenlerin modalı
 * prop-drilling olmadan açabilmesi gerekiyor (bkz. `FilterBar`/`useFilterStore`
 * ile aynı "cross-cutting UI state -> zustand store" deseni).
 */
import { create } from "zustand";
import {
  AUTH_TOKEN_STORAGE_KEY,
  fetchCurrentUser,
  loginRequest,
  registerRequest,
  type User,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { useVehicleProfileStore } from "./useVehicleProfileStore";

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  isAuthModalOpen: boolean;

  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => void;
  /** Sayfa açılışında localStorage'daki token'ı `/auth/me` ile doğrular. */
  restoreSession: () => Promise<void>;
  openAuthModal: () => void;
  closeAuthModal: () => void;
  /**
   * Başarılı bir check-in sonrası çağrılır - backend `trust_score`'u zaten
   * +1 artırdı (bkz. `checkin_service.add_check_in`), burada sadece
   * istemci state'ini iyimser (optimistic) biçimde aynı hizaya getiriyoruz
   * ki kullanıcı rozetindeki güven puanı anında güncellensin.
   */
  incrementTrustScore: () => void;
}

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch {
    // localStorage kullanılamıyor - token sadece bellekte (store state'inde) kalır.
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: readStoredToken(),
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,
  isAuthModalOpen: false,

  login: async (email, password) => {
    set({ isLoading: true, error: null });
    try {
      const { access_token } = await loginRequest(email, password);
      persistToken(access_token);
      const user = await fetchCurrentUser();
      set({ token: access_token, user, isAuthenticated: true, isLoading: false });
      // Yeni kullanıcının araç profillerini yükle - bir önceki (varsa
      // çıkış yapılmış) kullanıcının verisi `logout()`ta zaten sıfırlanmıştı,
      // burada bu kullanıcı için baştan çekiyoruz (bkz. görev tanımı).
      void useVehicleProfileStore.getState().fetchProfiles();
    } catch (err) {
      const message = extractErrorMessage(err, "E-posta veya şifre hatalı.");
      set({ isLoading: false, error: message });
      throw new Error(message);
    }
  },

  register: async (email, username, password) => {
    set({ isLoading: true, error: null });
    try {
      await registerRequest({ email, username, password });
      // Backend register'da token dönmüyor - kayıt sonrası otomatik giriş yap.
      const { access_token } = await loginRequest(email, password);
      persistToken(access_token);
      const user = await fetchCurrentUser();
      set({ token: access_token, user, isAuthenticated: true, isLoading: false });
      // Yeni kayıt olan kullanıcının (muhtemelen boş) araç listesini yükle -
      // bkz. login()'deki aynı gerekçe.
      void useVehicleProfileStore.getState().fetchProfiles();
    } catch (err) {
      const message = extractErrorMessage(err, "Kayıt oluşturulamadı.");
      set({ isLoading: false, error: message });
      throw new Error(message);
    }
  },

  logout: () => {
    persistToken(null);
    set({ token: null, user: null, isAuthenticated: false, error: null });
    // Kullanıcıya özel TÜM cross-cutting store'lar burada temizlenmeli ki
    // bir sonraki kullanıcı (aynı tarayıcı sekmesinde) önceki oturumun araç
    // listesini/aktif aracını görmesin (bkz. görev tanımı). Favoriler şu an
    // bu temizliği YAPMIYOR - bu, bu görevin kapsamı dışında, bilinen ayrı
    // bir eksiklik (bkz. `useFavoritesStore`).
    useFavoritesStore.getState().reset();
    useTripStore.getState().reset();
    useVehicleProfileStore.getState().reset();
  },

  restoreSession: async () => {
    const token = readStoredToken();
    if (!token) return;

    set({ isLoading: true });
    try {
      const user = await fetchCurrentUser();
      set({ token, user, isAuthenticated: true, isLoading: false });
      // Sayfa yenilendiğinde de (login() akışından geçmeden) araç listesi
      // yüklenmeli - CompatibilityCard/FilterBar ilk render'da doğru veriyi görsün.
      void useVehicleProfileStore.getState().fetchProfiles();
    } catch {
      // Token süresi dolmuş/geçersiz - sessizce temizle, kullanıcıyı hatayla karşılama.
      persistToken(null);
      set({ token: null, user: null, isAuthenticated: false, isLoading: false });
      useFavoritesStore.getState().reset();
    useTripStore.getState().reset();
    useVehicleProfileStore.getState().reset();
    }
  },

  openAuthModal: () => set({ error: null, isAuthModalOpen: true }),
  closeAuthModal: () => set({ isAuthModalOpen: false }),

  incrementTrustScore: () => {
    const { user } = get();
    if (user) set({ user: { ...user, trust_score: user.trust_score + 1 } });
  },
}));
