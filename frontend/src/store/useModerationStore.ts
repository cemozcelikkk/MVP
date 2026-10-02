/**
 * Moderasyon ekranının görünürlüğü ve "doğrulama denetimi" sekmesine gönderilecek nokta.
 * `AuthWidget` (buton) ve `ModerationPanel` (ekran) App.tsx'te kardeş olduğu için zustand
 * (bkz. `useFavoritesStore` ile aynı desen).
 */
import { create } from "zustand";

interface ModerationState {
  isOpen: boolean;
  /** Bir bildirim satırındaki "Doğrulama kayıtları" kısayolu için ön dolu nokta kimliği. */
  auditSpotId: string | null;
  open: () => void;
  close: () => void;
  openAudit: (spotId: string) => void;
}

export const useModerationStore = create<ModerationState>((set) => ({
  isOpen: false,
  auditSpotId: null,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false, auditSpotId: null }),
  openAudit: (spotId) => set({ isOpen: true, auditSpotId: spotId }),
}));
