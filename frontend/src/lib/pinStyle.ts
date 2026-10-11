/**
 * Harita pini görsel sözlüğü: kategori bazlı teknik piktogramlar (SVG) +
 * saha durumu (zabıta müdahalesi) uyarı rozeti.
 *
 * Tasarım kuralı: neon/parıltı/gölge/3D yok - mat zemin, 1px kenarlık,
 * tek renkli (monokrom) çizgi ikon. Askeri/topografik harita işaretçisi
 * hissiyatı hedefleniyor, "harita pini" değil "teknik aparat".
 */
import type { SpotCategory, SpotFeature } from "./api";

/** Kategori enum değerlerinin Türkçe etiketleri - rozet ve panel metinlerinde ortak kullanılır. */
export const CATEGORY_LABEL: Record<SpotCategory, string> = {
  CAMPING: "Kamp",
  FISH_RESTAURANT: "Balık Restoranı",
  MEAT_RESTAURANT: "Et Restoranı",
  HOTEL_POOL: "Otel / Havuz",
  HOSPITAL: "Hastane",
  HEALTH_CENTER: "Sağlık Ocağı",
};

/** Bilinmeyen (ör. eski önbellekten gelen) kategori değerlerinde düşülecek görsel. */
const FALLBACK_CATEGORY: SpotCategory = "CAMPING";

interface CategoryPinStyle {
  /** Pin zemini (mat, koyu). */
  fill: string;
  /** Pin 1px kenarlığı. */
  border: string;
  /** İkon çizgi rengi. */
  icon: string;
}

/**
 * Pin zemin/kenarlık/ikon renk üçlüsü - kategoriye göre. Her kategori ailesi
 * ayrı bir ton taşır (kamp yeşil, balık lacivert, et kahve, otel/havuz
 * camgöbeği, sağlık kırmızı); hastane ve sağlık ocağı aynı kırmızı ailede
 * kalır, ikon şekliyle (H tabelası / daire içi artı) ayrışır.
 */
export const CATEGORY_PIN_STYLE: Record<SpotCategory, CategoryPinStyle> = {
  CAMPING: { fill: "#23382B", border: "#365743", icon: "#D8E6DC" },
  FISH_RESTAURANT: { fill: "#1F3447", border: "#34536E", icon: "#CFE0EE" },
  MEAT_RESTAURANT: { fill: "#4D3020", border: "#70492F", icon: "#F3DCC8" },
  HOTEL_POOL: { fill: "#17414A", border: "#2C6470", icon: "#CDEBEF" },
  HOSPITAL: { fill: "#6B1F24", border: "#923238", icon: "#F7DADC" },
  HEALTH_CENTER: { fill: "#5A2A30", border: "#7E434B", icon: "#F4DDE0" },
};

interface CategoryLandscapeStyle {
  /** Gökyüzü - gradyanın üst tonu (açık). */
  sky: string;
  /** Gökyüzü - gradyanın alt tonu (zemine yakın). */
  ground: string;
  /** Uzak sırt silüeti. */
  ridgeFar: string;
  /** Yakın sırt silüeti. */
  ridgeNear: string;
  /** Güneş/ay dairesi. */
  sun: string;
}

/**
 * Fotoğrafsız noktalar için kart illüstrasyonu paleti - açık, doğal tonlar
 * (bkz. `CardLandscape` in ExploreList.tsx). `CATEGORY_PIN_STYLE`den BİLİNÇLİ
 * olarak ayrı: pin rengi haritanın koyu teknik aparatı için, bu ise kartın
 * AÇIK zemini için - aynı renkler ikisine de uymuyor.
 */
export const CATEGORY_LANDSCAPE_STYLE: Record<SpotCategory, CategoryLandscapeStyle> = {
  CAMPING: { sky: "#EAF3E1", ground: "#D9EAC9", ridgeFar: "#AECB98", ridgeNear: "#87AD70", sun: "#F5D98B" },
  FISH_RESTAURANT: { sky: "#E6F0F7", ground: "#D2E3EF", ridgeFar: "#9DBBD3", ridgeNear: "#7199BA", sun: "#F5D98B" },
  MEAT_RESTAURANT: { sky: "#FBF0E6", ground: "#F2DFCC", ridgeFar: "#D6B391", ridgeNear: "#B98D66", sun: "#F0A85E" },
  HOTEL_POOL: { sky: "#E5F4F5", ground: "#CFEAEC", ridgeFar: "#95CACF", ridgeNear: "#68AAB1", sun: "#F5D98B" },
  HOSPITAL: { sky: "#F8ECEC", ground: "#F0DADB", ridgeFar: "#D9A9AC", ridgeNear: "#BF8186", sun: "#F0D9A0" },
  HEALTH_CENTER: { sky: "#F7EEF0", ground: "#EEDFE2", ridgeFar: "#D3B1B8", ridgeNear: "#B58C95", sun: "#F0D9A0" },
};

/** 24x24 viewBox, stroke-width 2 `<path>` gövdeleri (çoğu Tabler ikon setinden). Hizmet noktaları da bunları paylaşır (bkz. servicePoints.ts). */
export const CATEGORY_ICON_PATHS: Record<SpotCategory, string> = {
  // Tabler "tent".
  CAMPING: `<path d="M11 14l4 6h6l-9 -16l-9 16h6l4 -6" />`,
  // Tabler "fish".
  FISH_RESTAURANT: `<path d="M16.69 7.44a6.973 6.973 0 0 0 -1.69 4.56c0 1.747 .64 3.345 1.699 4.571" /><path d="M2 9.504c7.715 8.647 14.75 10.265 20 2.498c-5.25 -7.761 -12.285 -6.142 -20 2.504" /><path d="M18 11v.01" /><path d="M11.5 10.5c-.667 1 -.667 2 0 3" />`,
  // Tabler "meat".
  MEAT_RESTAURANT: `<path d="M13.62 8.382l1.966 -1.967a2 2 0 1 1 3.414 -1.415a2 2 0 1 1 -1.413 3.414l-1.82 1.821" /><path d="M5.904 18.596c2.733 2.734 5.9 4 7.07 2.829c1.172 -1.172 -.094 -4.338 -2.828 -7.071c-2.733 -2.734 -5.9 -4 -7.07 -2.829c-1.172 1.172 .094 4.338 2.828 7.071z" /><path d="M7.5 16l1 1" /><path d="M12.975 21.425c3.905 -3.906 4.855 -9.288 2.121 -12.021c-2.733 -2.734 -8.115 -1.784 -12.02 2.121" />`,
  // Tabler "pool".
  HOTEL_POOL: `<path d="M2 20a2.4 2.4 0 0 0 2 1a2.4 2.4 0 0 0 2 -1a2.4 2.4 0 0 1 2 -1a2.4 2.4 0 0 1 2 1a2.4 2.4 0 0 0 2 1a2.4 2.4 0 0 0 2 -1a2.4 2.4 0 0 1 2 -1a2.4 2.4 0 0 1 2 1a2.4 2.4 0 0 0 2 1a2.4 2.4 0 0 0 2 -1" /><path d="M2 16a2.4 2.4 0 0 0 2 1a2.4 2.4 0 0 0 2 -1a2.4 2.4 0 0 1 2 -1a2.4 2.4 0 0 1 2 1a2.4 2.4 0 0 0 2 1a2.4 2.4 0 0 0 2 -1a2.4 2.4 0 0 1 2 -1a2.4 2.4 0 0 1 2 1a2.4 2.4 0 0 0 2 1a2.4 2.4 0 0 0 2 -1" /><path d="M15 12v-7.5a1.5 1.5 0 0 1 3 0" /><path d="M9 12v-7.5a1.5 1.5 0 0 0 -3 0" /><path d="M15 5h-6" /><path d="M9 10h6" />`,
  // Hastane tabelası: kare çerçeve içinde "H".
  HOSPITAL: `<path d="M3 5a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v14a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-14z" /><path d="M9 8v8" /><path d="M15 8v8" /><path d="M9 12h6" />`,
  // Sağlık ocağı: daire içinde artı.
  HEALTH_CENTER: `<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0" /><path d="M12 8v8" /><path d="M8 12h8" />`,
};

/** Bir spot'un pinine yerleştirilecek Tabler ikon markup'ı (18x18, 24x24 viewBox). */
export function categoryIconSvg(category: SpotCategory): string {
  const style = CATEGORY_PIN_STYLE[category] ?? CATEGORY_PIN_STYLE[FALLBACK_CATEGORY];
  const paths = CATEGORY_ICON_PATHS[category] ?? CATEGORY_ICON_PATHS[FALLBACK_CATEGORY];
  return lineIconSvg(paths, style.icon);
}

/** Tek renkli çizgi ikon (24x24 viewBox). `currentColor` dolgulu metin öğeleri de aynı rengi alır. */
export function lineIconSvg(paths: string, color: string): string {
  return `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" color="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">${paths}</svg>`;
}

/**
 * Saha uyarı rozeti gerekiyor mu? Karar backend'de (`live_status.badge`: şiddeti serious/critical
 * olan aktif süreli durum veya resmî uyarı) - bbox yanıtındaki hafif özet kullanılır, pin başına
 * ayrı istek YOK. Özet yoksa (eski önbellek/sync verisi) eski `latest_status` davranışına düşülür.
 */
export function hasActiveWarning(feature: SpotFeature): boolean {
  const live = feature.properties.live_status;
  if (live) return live.badge;
  const intervention = feature.properties.latest_status?.police_intervention;
  return intervention === "warning" || intervention === "fine";
}

/**
 * Bir marker DOM elemanının tam iç HTML'i: kategori ikonu + (varsa) uyarı
 * rozeti. `MapView` bunu `el.innerHTML`'e atar, kategori renk değişkenlerini
 * ayrıca CSS custom property olarak set eder (bkz. `applyCategoryPinVars`).
 */
export function pinInnerHtml(feature: SpotFeature): string {
  const icon = `<span class="spot-pin__icon">${categoryIconSvg(feature.properties.category)}</span>`;
  // Rozet SALT görsel bir işaretçidir (renk tek kanal) - asıl uyarı metni ve
  // ikonu spot seçilince `LiveStatusSection`da gösterilir; ekran okuyucu
  // kullanıcılar için pinin `aria-label`ına ayrıca "(aktif uyarı)" eklenir
  // (bkz. MapView `buildPointMarker`).
  const badge = hasActiveWarning(feature) ? `<span class="spot-pin__badge" aria-hidden="true"></span>` : "";
  return icon + badge;
}

/** Pin elemanına kategoriye göre zemin/kenarlık CSS değişkenlerini uygular. */
export function applyCategoryPinVars(el: HTMLElement, category: SpotCategory): void {
  const style = CATEGORY_PIN_STYLE[category] ?? CATEGORY_PIN_STYLE[FALLBACK_CATEGORY];
  el.style.setProperty("--pin-fill", style.fill);
  el.style.setProperty("--pin-border", style.border);
}
