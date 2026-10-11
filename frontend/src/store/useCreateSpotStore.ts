/**
 * Yeni spot ekleme akışının durumu (konum seçim modu, haritaya bırakılan
 * geçici pin, form modalının görünürlüğü) ARTI haritanın tepki vermesi
 * gereken diğer spot yaşam döngüsü sinyalleri (`focusedSpot`/`deletedSpotId`)
 * - isim tarihsel olarak "oluşturma"dan geliyor ama artık Favoriler
 * çekmecesindeki [Haritada Göster] ve detay panelindeki [Sil] de aynı
 * mekanizmaları paylaşıyor.
 *
 * `MapView` bu store'u doğrudan okuyup yazıyor (bkz. `useFilterStore`'un
 * zaten aynı şekilde kullanıldığı yer) - böylece "+ Nokta Ekle" butonu,
 * harita tıklaması/sağ tıklaması ve form modalı App.tsx üzerinden prop
 * geçirmeden aynı durumu paylaşabiliyor.
 */
import { create } from "zustand";
import type { ServicePointCategory, ServicePointFeature, SpotFeature } from "../lib/api";
import type { PlaceGroup } from "./filters";
import { useAuthStore } from "./useAuthStore";

interface CreateSpotState {
  /**
   * "Ne eklemek istiyorsunuz?" tür seçim penceresi (bkz. AddPlaceChooser). Ekleme
   * akışı her zaman burada başlar: önce tür, sonra konum, en son türe özgü kısa form.
   */
  isChooserOpen: boolean;
  /** Seçilen ana grup - hangi formun açılacağını belirler (kamp detaylı, diğerleri kısa). */
  addGroup: PlaceGroup | null;
  /** Hizmet noktalarında seçilen alt tür (ör. HEALTH_CENTER); kampta null. */
  addCategory: ServicePointCategory | null;
  isPickingLocation: boolean;
  /** [boylam, enlem] - haritada bırakılan geçici (pirinç sarısı) pin. */
  pendingCoordinates: [number, number] | null;
  isModalOpen: boolean;
  /** true ise GPS konumu alınıyor (spinner göster). */
  isLocating: boolean;
  /** GPS veya izin hatası mesajı - toast olarak gösterilir. */
  geoError: string | null;
  /**
   * Haritanın "uçup" seçili hale getirmesi gereken spot - sadece yeni
   * oluşturmadan sonra değil, Favoriler çekmecesindeki `[Haritada Göster]`
   * gibi başka akışlar da aynı mekanizmayı (`focusSpot`) kullanır; `MapView`
   * bunu izleyip `flyTo` tetikler.
   */
  focusedSpot: SpotFeature | null;
  focusedLocation: [number, number] | null;
  focusLocation: (coordinates: [number, number]) => void;
  /** Az önce silinen spot'un id'si - `MapView` bunu izleyip pinini haritadan kaldırır. */
  deletedSpotId: string | null;
  /**
   * Az önce düzenlenmiş VEYA yeni durum bildirimi almış spot - `MapView`
   * bunu izleyip ilgili pinin piktogramını/uyarı rozetini bir sonraki
   * bbox yenilemesini beklemeden yerinde günceller (bkz. `pinStyle.ts`).
   */
  updatedSpot: SpotFeature | null;

  /** "+ Nokta Ekle" / haritada sağ tık. Oturum yoksa giriş modalını açar. Koordinat verilirse konum adımı atlanır. */
  openChooser: (coordinates?: [number, number]) => void;
  closeChooser: () => void;
  /** Tür seçildi: konum zaten varsa forma geçer, yoksa seçim penceresi konum adımına ilerler. */
  chooseType: (group: PlaceGroup, category: ServicePointCategory | null) => void;
  /** Hizmet noktası oluşturuldu: harita oraya uçar (bkz. MapView). */
  focusedServicePoint: ServicePointFeature | null;
  focusServicePoint: (feature: ServicePointFeature) => void;
  /** Tür seçildikten sonra "Haritadan Seç". */
  startPicking: () => void;
  cancelPicking: () => void;
  /** Haritaya tıklanınca (picking modundayken) ya da sağ tıklanınca çağrılır. */
  locationPicked: (coordinates: [number, number]) => void;
  /** Tarayıcının Geolocation API'si ile mevcut GPS konumunu alır. */
  useCurrentLocation: () => void;
  /** GPS hata mesajını temizler (toast kapandığında). */
  clearGeoError: () => void;
  /** Formu iptal/kapat - geçici pini de kaldırır. */
  closeModal: () => void;
  /** Formu kapatır (varsa) ve haritanın bu spota uçmasını tetikler. */
  focusSpot: (feature: SpotFeature) => void;
  /** `[Sil]` başarılı olduğunda çağrılır - haritadaki pin'i temizler. */
  spotDeleted: (spotId: string) => void;
  /** Düzenleme kaydı veya durum bildirimi başarılı olduğunda çağrılır. */
  spotUpdated: (feature: SpotFeature) => void;
}

function requireAuth(): boolean {
  if (useAuthStore.getState().isAuthenticated) return true;
  useAuthStore.getState().openAuthModal();
  return false;
}

const RESET_FLOW = {
  isChooserOpen: false,
  isPickingLocation: false,
  isModalOpen: false,
  pendingCoordinates: null,
  addGroup: null,
  addCategory: null,
} as const;

export const useCreateSpotStore = create<CreateSpotState>((set, get) => ({
  isChooserOpen: false,
  addGroup: null,
  addCategory: null,
  focusedServicePoint: null,
  isPickingLocation: false,
  pendingCoordinates: null,
  isModalOpen: false,
  isLocating: false,
  geoError: null,
  focusedSpot: null,
  focusedLocation: null,
  focusLocation: (coordinates) => set({ focusedLocation: coordinates }),
  deletedSpotId: null,
  updatedSpot: null,

  openChooser: (coordinates) => {
    if (!requireAuth()) return;
    set({ ...RESET_FLOW, isChooserOpen: true, pendingCoordinates: coordinates ?? null, geoError: null });
  },

  closeChooser: () => set({ ...RESET_FLOW }),

  chooseType: (group, category) => {
    const hasLocation = get().pendingCoordinates !== null;
    set({ addGroup: group, addCategory: category, isChooserOpen: !hasLocation, isModalOpen: hasLocation });
  },

  focusServicePoint: (feature) => set({ ...RESET_FLOW, focusedServicePoint: feature }),

  startPicking: () => {
    if (!requireAuth()) return;
    set({ isChooserOpen: false, isPickingLocation: true, geoError: null });
  },

  cancelPicking: () => set({ ...RESET_FLOW }),

  locationPicked: (coordinates) => {
    if (!requireAuth()) return;
    // Tür henüz seçilmediyse (ör. haritada sağ tık) önce "ne eklemek istiyorsunuz?".
    if (get().addGroup === null) {
      set({ ...RESET_FLOW, isChooserOpen: true, pendingCoordinates: coordinates });
      return;
    }
    set({ pendingCoordinates: coordinates, isPickingLocation: false, isChooserOpen: false, isModalOpen: true });
  },

  useCurrentLocation: () => {
    if (!requireAuth()) return;
    if (!navigator.geolocation) {
      set({ geoError: "Tarayıcınız konum hizmetlerini desteklemiyor." });
      return;
    }
    set({ isLocating: true, geoError: null });
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coords: [number, number] = [position.coords.longitude, position.coords.latitude];
        const hasType = get().addGroup !== null;
        set({
          pendingCoordinates: coords,
          isPickingLocation: false,
          isChooserOpen: !hasType,
          isModalOpen: hasType,
          isLocating: false,
        });
      },
      (error) => {
        let message = "Konum alınamadı. Lütfen haritadan manuel seçim yapın.";
        if (error.code === error.PERMISSION_DENIED) {
          message = "Konum izni reddedildi. Lütfen tarayıcı ayarlarından izin verin veya haritadan seçin.";
        } else if (error.code === error.TIMEOUT) {
          message = "Konum alınırken zaman aşımına uğradı. Haritadan manuel seçim yapabilirsiniz.";
        }
        set({ isLocating: false, geoError: message });
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  },

  clearGeoError: () => set({ geoError: null }),

  closeModal: () => set({ ...RESET_FLOW }),

  focusSpot: (feature) => set({ ...RESET_FLOW, focusedSpot: feature }),

  spotDeleted: (spotId) => set({ deletedSpotId: spotId }),

  spotUpdated: (feature) => set({ updatedSpot: feature }),
}));
