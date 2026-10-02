/**
 * Üst filtre çubuğunun durumu ve bunun `/spots/bbox` sorgu parametrelerine
 * çevrimi. Tek sorumluluk: hangi basmalı anahtarların aktif olduğunu tutmak
 * ve API'nin beklediği query param şekline dönüştürmek.
 */
import { create } from "zustand";

export type FilterToggleKey =
  | "hasToilet"
  | "hasTrashBins"
  | "freeOnly"
  | "campingAllowed"
  | "overnightAllowed"
  | "hasFreshWater"
  | "hasElectricity"
  | "no4x4Required"
  | "caravanOnly"
  | "onlyVerified"
  | "onlyFavorites"
  | "vehicleCompatibleOnly";

export interface FilterValues {
  hasToilet: boolean;
  hasTrashBins: boolean;
  freeOnly: boolean;
  campingAllowed: boolean;
  overnightAllowed: boolean;
  hasFreshWater: boolean;
  hasElectricity: boolean;
  no4x4Required: boolean;
  caravanOnly: boolean;
  onlyVerified: boolean;
  // Not: diğerlerinin aksine backend'e query param olarak gitmez - MapView
  // bunu bbox sonucunu `useFavoritesStore.favoriteIds`e göre istemci
  // tarafında eleyerek uyguluyor (backend `/bbox`'ta favori filtresi yok).
  onlyFavorites: boolean;
  /**
   * "Aracıma Uygun" - sadece aktif araç profili olan kullanıcılar için
   * `FilterBar`da görünür (bkz. o bileşendeki `hasActiveVehicle` kontrolü).
   * Backend'e `with_compatibility=true` olarak gider (her spot'a hafif bir
   * `compatibility.status` ekletir) AMA asıl göster/gizle/vurgula kararı
   * İSTEMCİ TARAFINDA verilir (bkz. `MapView.renderMarkers`) - backend
   * hiçbir spot'u bu bayrak yüzünden elemez, sadece veriyi ekler.
   */
  vehicleCompatibleOnly: boolean;
}

const INITIAL_VALUES: FilterValues = {
  hasToilet: false,
  hasTrashBins: false,
  freeOnly: false,
  campingAllowed: false,
  overnightAllowed: false,
  hasFreshWater: false,
  hasElectricity: false,
  no4x4Required: false,
  caravanOnly: false,
  onlyVerified: false,
  onlyFavorites: false,
  vehicleCompatibleOnly: false,
};

interface FilterState extends FilterValues {
  toggle: (key: FilterToggleKey) => void;
  /** "Filtreleri temizle" - Üst bar / Tüm Filtreler modalındaki ortak eylem. */
  reset: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  ...INITIAL_VALUES,
  toggle: (key) => set((state) => ({ [key]: !state[key] }) as Pick<FilterState, typeof key>),
  reset: () => set(INITIAL_VALUES),
}));

/** Aktif filtre sayısı - "Tüm Filtreler" butonundaki rozet için (bkz. AppTopBar). */
export function countActiveFilters(state: FilterValues): number {
  return Object.values(state).filter(Boolean).length;
}

/**
 * Aktif filtreleri `/spots/bbox` query param'larına çevirir. `onlyFavorites`
 * kasıtlı olarak parametre tipinde YOK - backend'e hiç gitmiyor, MapView
 * onu ayrıca (istemci tarafında) uyguluyor (bkz. `FilterValues` üzerindeki not).
 * `vehicleCompatibleOnly` ise (favorilerin aksine) GERÇEKTEN backend'e gider
 * (`with_compatibility=true`) - sadece göster/gizle kararı istemcide kalır.
 */
export function filtersToQueryParams(
  state: Omit<FilterValues, "onlyFavorites">,
): Record<string, boolean | string> {
  const params: Record<string, boolean | string> = {};
  if (state.hasFreshWater) params.has_fresh_water = true;
  if (state.hasElectricity) params.has_electricity = true;
  // Backend semantiği: requires_4x4=false -> sadece 4x4 gerektirenleri ele.
  // requires_4x4=true/undefined -> filtre uygulanmaz (bkz. spot_service.get_spots_in_bbox).
  if (state.no4x4Required) params.requires_4x4 = false;
  if (state.caravanOnly) params.caravan_type = "caravan";
  if (state.onlyVerified) params.only_verified = true;
  if (state.vehicleCompatibleOnly) params.with_compatibility = true;
  if (state.hasToilet) params.has_toilet = true;
  if (state.hasTrashBins) params.has_trash_bins = true;
  if (state.freeOnly) params.is_free = true;
  if (state.campingAllowed) params.camping_behavior_allowed = true;
  if (state.overnightAllowed) params.overnight_allowed = true;
  return params;
}
