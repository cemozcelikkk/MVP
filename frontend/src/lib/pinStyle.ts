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
  wild_camping: "Vahşi Kamp",
  farm_stay: "Çiftlik Konaklama",
  sanistation_only: "Sadece Sanistasyon",
  campsite: "Kamp Alanı",
  day_parking: "Gündüz Parkı",
};

interface CategoryPinStyle {
  /** Pin zemini (mat, koyu). */
  fill: string;
  /** Pin 1px kenarlığı. */
  border: string;
  /** İkon çizgi rengi. */
  icon: string;
}

/**
 * Pin zemin/kenarlık/ikon renk üçlüsü - kategoriye göre. `farm_stay` spekte
 * ayrı tanımlanmamıştı; "vahşi kamp"la aynı doğa/kırsal aile içinde
 * tutuluyor (yeşil zemin), ikon şekliyle ayrışıyor (çadır değil, ev).
 */
export const CATEGORY_PIN_STYLE: Record<SpotCategory, CategoryPinStyle> = {
  wild_camping: { fill: "#23382B", border: "#365743", icon: "#D8E6DC" },
  farm_stay: { fill: "#23382B", border: "#365743", icon: "#D8E6DC" },
  campsite: { fill: "#3D3528", border: "#594E3B", icon: "#EADBCA" },
  sanistation_only: { fill: "#253540", border: "#3A5263", icon: "#D0DFE8" },
  // Nötr kategori - yeni tasarım tokenlarındaki surface-dark-raised/border-dark ile birebir.
  day_parking: { fill: "#2D322E", border: "#3A403B", icon: "#C9CCC5" },
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
  wild_camping: { sky: "#EAF3E1", ground: "#D9EAC9", ridgeFar: "#AECB98", ridgeNear: "#87AD70", sun: "#F5D98B" },
  farm_stay: { sky: "#F1F3E1", ground: "#E6EAD0", ridgeFar: "#C4CB98", ridgeNear: "#A2AB77", sun: "#F5D98B" },
  campsite: { sky: "#FBF1E1", ground: "#F3E3C7", ridgeFar: "#D9BD8C", ridgeNear: "#BE9A63", sun: "#F0A85E" },
  sanistation_only: { sky: "#E8F2F5", ground: "#D5E9EF", ridgeFar: "#9CC2D1", ridgeNear: "#72A3B7", sun: "#F5D98B" },
  day_parking: { sky: "#EEF0EC", ground: "#E1E5DB", ridgeFar: "#B4BCAB", ridgeNear: "#939C87", sun: "#F0D9A0" },
};

/** Tabler ikon setinden alınan `<path>` gövdeleri (24x24 viewBox, stroke-width 2). */
const CATEGORY_ICON_PATHS: Record<SpotCategory, string> = {
  // Tabler "tent".
  wild_camping: `<path d="M11 14l4 6h6l-9 -16l-9 16h6l4 -6" />`,
  // Vahşi Kamp'la aynı aile (yeşil zemin) - Tabler "home" ile ayrışan siluet.
  farm_stay: `<path d="M5 12l-2 0l9 -9l9 9l-2 0" /><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7" /><path d="M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6" />`,
  // Tabler "caravan".
  campsite: `<path d="M5 18a2 2 0 1 0 4 0a2 2 0 0 0 -4 0" /><path d="M15 18a2 2 0 1 0 4 0a2 2 0 0 0 -4 0" /><path d="M5 18h-1a1 1 0 0 1 -1 -1v-11a2 2 0 0 1 2 -2h12a4 4 0 0 1 4 4h-18" /><path d="M9 18h6" /><path d="M19 18h1a1 1 0 0 0 1 -1v-4l-3 -5" /><path d="M21 13h-7" /><path d="M14 8v10" />`,
  // Tabler "droplet".
  sanistation_only: `<path d="M7.502 19.423c2.602 2.105 6.395 2.105 8.996 0c2.602 -2.105 3.262 -5.708 1.566 -8.546l-4.89 -7.26c-.42 -.625 -1.287 -.803 -1.936 -.397a1.376 1.376 0 0 0 -.41 .397l-4.893 7.26c-1.695 2.838 -1.035 6.441 1.567 8.546z" />`,
  // Tabler "square-letter-p" (kare çerçeveli 'P').
  day_parking: `<path d="M3 5a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v14a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-14z" /><path d="M10 16v-8h3.334c1.472 0 2.666 1.119 2.666 2.5a2.5 2.5 0 0 1 -2.666 2.5h-3.334" />`,
};

/** Bir spot'un pinine yerleştirilecek Tabler ikon markup'ı (18x18, 24x24 viewBox). */
export function categoryIconSvg(category: SpotCategory): string {
  const style = CATEGORY_PIN_STYLE[category] ?? CATEGORY_PIN_STYLE.day_parking;
  const paths = CATEGORY_ICON_PATHS[category] ?? CATEGORY_ICON_PATHS.day_parking;
  return `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${style.icon}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">${paths}</svg>`;
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
  const style = CATEGORY_PIN_STYLE[category] ?? CATEGORY_PIN_STYLE.day_parking;
  el.style.setProperty("--pin-fill", style.fill);
  el.style.setProperty("--pin-border", style.border);
}
