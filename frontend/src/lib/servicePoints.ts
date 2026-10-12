/**
 * Hizmet noktaları (restoran / sağlık / WC / duş) için ortak görsel ve metin
 * sözlüğü: grup/tür etiketleri, pin renkleri, ikonlar ve durum metinleri.
 * Kamp noktalarının karşılığı `pinStyle.ts`; aynı "mat zemin + tek renk çizgi
 * ikon" dilini konuşur ama pin daha küçük ve yuvarlaktır (bkz. index.css `.service-pin`).
 */
import type {
  AvailabilityStatus,
  FeeStatus,
  ServicePointCategory,
  ServicePointGroup,
  ServicePointProperties,
  ServicePointReportReason,
} from "./api";
import { CATEGORY_ICON_PATHS, lineIconSvg } from "./pinStyle";

export const SERVICE_GROUPS: {
  group: ServicePointGroup;
  emoji: string;
  label: string;
  description: string;
  categories: ServicePointCategory[];
}[] = [
  {
    group: "food",
    emoji: "🍽️",
    label: "Yeme & İçme",
    description: "Et, balık restoranı veya kafe",
    categories: ["MEAT_RESTAURANT", "FISH_RESTAURANT", "OTHER_RESTAURANT"],
  },
  {
    group: "health",
    emoji: "🏥",
    label: "Sağlık Hizmetleri",
    description: "Hastane veya sağlık ocağı",
    categories: ["HOSPITAL", "HEALTH_CENTER"],
  },
  {
    group: "basic",
    emoji: "🚻",
    label: "Temel İhtiyaçlar",
    description: "WC veya duş",
    categories: ["WC", "SHOWER"],
  },
];

export const SERVICE_CATEGORY_LABEL: Record<ServicePointCategory, string> = {
  MEAT_RESTAURANT: "Et Restoranı",
  FISH_RESTAURANT: "Balık Restoranı",
  OTHER_RESTAURANT: "Restoran / Kafe",
  HOSPITAL: "Hastane",
  HEALTH_CENTER: "Sağlık Ocağı / ASM",
  WC: "WC",
  SHOWER: "Duş",
};

export const SERVICE_GROUP_LABEL: Record<ServicePointGroup, string> = {
  food: "Yeme & İçme",
  health: "Sağlık",
  basic: "Temel İhtiyaç",
};

/** Kayıtta ad yoksa (sağlık/WC/duşta opsiyonel) türün adı gösterilir. */
export function servicePointTitle(p: Pick<ServicePointProperties, "name" | "category">): string {
  return p.name?.trim() || SERVICE_CATEGORY_LABEL[p.category];
}

const SERVICE_PIN_STYLE: Record<ServicePointCategory, { fill: string; border: string; icon: string }> = {
  MEAT_RESTAURANT: { fill: "#4D3020", border: "#70492F", icon: "#F3DCC8" },
  FISH_RESTAURANT: { fill: "#1F3447", border: "#34536E", icon: "#CFE0EE" },
  OTHER_RESTAURANT: { fill: "#5B4A1E", border: "#7D6830", icon: "#F4E7C3" },
  HOSPITAL: { fill: "#6B1F24", border: "#923238", icon: "#F7DADC" },
  HEALTH_CENTER: { fill: "#5A2A30", border: "#7E434B", icon: "#F4DDE0" },
  WC: { fill: "#2E3F57", border: "#46597A", icon: "#DCE5F2" },
  SHOWER: { fill: "#17414A", border: "#2C6470", icon: "#CDEBEF" },
};

/** Harita şeridi ve "Yakınımdakiler" hizmet filtreleri (WC ve duş ayrı). */
export const PLACE_FILTER_META: Record<
  "food" | "health" | "wc" | "shower",
  { emoji: string; label: string; color: { fill: string; border: string }; category: ServicePointCategory }
> = {
  food: { emoji: "🍽️", label: "Yeme & İçme", color: SERVICE_PIN_STYLE.MEAT_RESTAURANT, category: "OTHER_RESTAURANT" },
  health: { emoji: "🏥", label: "Sağlık", color: SERVICE_PIN_STYLE.HOSPITAL, category: "HOSPITAL" },
  wc: { emoji: "🚻", label: "WC", color: SERVICE_PIN_STYLE.WC, category: "WC" },
  shower: { emoji: "🚿", label: "Duş", color: SERVICE_PIN_STYLE.SHOWER, category: "SHOWER" },
};

/** Bir hizmet noktası hangi filtreye düşer. */
export function placeFilterOf(category: ServicePointCategory): "food" | "health" | "wc" | "shower" {
  if (category === "WC") return "wc";
  if (category === "SHOWER") return "shower";
  if (category === "HOSPITAL" || category === "HEALTH_CENTER") return "health";
  return "food";
}

/** "350 m" / "2,4 km" */
export function formatDistance(meters: number): string {
  if (meters < 1000) return `${Math.max(10, Math.round(meters / 10) * 10)} m`;
  return `${(meters / 1000).toLocaleString("tr-TR", { maximumFractionDigits: meters < 10_000 ? 1 : 0 })} km`;
}

const SERVICE_ICON_PATHS: Record<ServicePointCategory, string> = {
  MEAT_RESTAURANT: CATEGORY_ICON_PATHS.MEAT_RESTAURANT,
  FISH_RESTAURANT: CATEGORY_ICON_PATHS.FISH_RESTAURANT,
  // Tabler "tools-kitchen-2".
  OTHER_RESTAURANT: `<path d="M19 3v12h-5c-.023 -3.681 .184 -7.406 5 -12zm0 12v6h-1v-3m-10 -14v17m-3 -17v3a3 3 0 1 0 6 0v-3" />`,
  HOSPITAL: CATEGORY_ICON_PATHS.HOSPITAL,
  HEALTH_CENTER: CATEGORY_ICON_PATHS.HEALTH_CENTER,
  WC: `<text x="12" y="16.2" text-anchor="middle" font-size="10.5" font-weight="800" font-family="system-ui, sans-serif" fill="currentColor" stroke="none">WC</text>`,
  // Duş başlığı + su damlaları.
  SHOWER: `<path d="M12 3v3" /><path d="M6 12a6 6 0 0 1 12 0z" /><path d="M8 16v1" /><path d="M12 16v2" /><path d="M16 16v1" /><path d="M10 20v1" /><path d="M14 20v1" />`,
};

export function serviceIconSvg(category: ServicePointCategory, color?: string): string {
  return lineIconSvg(SERVICE_ICON_PATHS[category], color ?? SERVICE_PIN_STYLE[category].icon);
}

export function servicePinColors(category: ServicePointCategory) {
  return SERVICE_PIN_STYLE[category];
}

export const FEE_LABEL: Record<FeeStatus, string> = { free: "Ücretsiz", paid: "Ücretli", unknown: "Bilinmiyor" };
export const AVAILABILITY_LABEL: Record<AvailabilityStatus, string> = {
  available: "Kullanılabilir",
  unavailable: "Kullanılamıyor",
  unknown: "Bilinmiyor",
};

export const REPORT_REASON_LABEL: Record<ServicePointReportReason, string> = {
  wrong_location: "Konum hatalı",
  closed: "Kapanmış / artık yok",
  duplicate: "Mükerrer kayıt",
  wrong_info: "Bilgi yanlış",
  other: "Diğer",
};

/** WC/duş bilgisi bu kadar günden eskiyse "güncelliğini yitirmiş olabilir" uyarısı gösterilir. */
export const STATUS_STALE_DAYS = 30;

/**
 * Harici kaynak (OpenStreetMap) henüz hazır değilken yeniden sorma takvimi.
 * - `partial`: bölge arka planda çekiliyor - önce hızlı (1,5 sn → 20 sn), sonra 30 sn arayla.
 * - `unavailable`: kamu Overpass sunucuları şu an yanıt vermiyor; sunucudaki yenileyici
 *   1, 2, 4 ... dk arayla kendisi deniyor - istemci 30 sn arayla sonucu kontrol eder.
 * Toplam ~5 dakika sonra durur (sekme açık unutulsa da sonsuza kadar sormaz). Başka bir
 * durumda `null` - yeniden sorulmaz.
 */
const FAST_RETRY_MS = [1500, 3000, 5000, 8000, 12000, 20000];
const SLOW_RETRY_MS = 30_000;
const MAX_EXTERNAL_RETRIES = 14;

export function externalRetryDelay(status: string | null | undefined, attempt: number): number | null {
  if (attempt >= MAX_EXTERNAL_RETRIES) return null;
  if (status === "partial") return FAST_RETRY_MS[attempt] ?? SLOW_RETRY_MS;
  if (status === "unavailable") return SLOW_RETRY_MS;
  return null;
}
