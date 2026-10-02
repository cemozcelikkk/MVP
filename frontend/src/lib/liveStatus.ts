/**
 * Süreli canlı saha durumları için ortak UI sözlüğü (ikon/renk/etiket).
 *
 * KARAR MANTIĞI BURADA DEĞİL: şiddet, güven düzeyi, erişim kararı ve rozet ihtiyacı
 * backend'de hesaplanır (`app/services/live_status.py`); burası yalnızca o KARARLI kodları
 * ikon + kısa metne çevirir. Renk tek iletişim kanalı değildir - her durumda ikon ve metin var.
 * Varsayılan süreler yalnızca formdaki ÖNERİdir (kullanıcı değiştirebilir); backend 6/12/24/48
 * dışını reddeder.
 */
import { AlertTriangle, OctagonAlert, Info, ShieldCheck, User, Users } from "lucide-react";
import type {
  LiveAccess,
  LiveDurationHours,
  LiveReportOutcome,
  LiveReportType,
  LiveSeverity,
  LiveTrustLevel,
  ReportModerationState,
} from "./api";

export const DURATION_OPTIONS: LiveDurationHours[] = [6, 12, 24, 48];

export interface LiveTypeOption {
  value: LiveReportType;
  /** Formda seçilen kısa ad (bildirim dili: "bildirilecek", resmî karar iddiası yok). */
  label: string;
  hint: string;
  defaultHours: LiveDurationHours;
  group: "access" | "night" | "service" | "capacity";
}

export const LIVE_TYPE_OPTIONS: LiveTypeOption[] = [
  { value: "road_closed", label: "Yol kapalı", hint: "Araçla ulaşılamıyor", defaultHours: 24, group: "access" },
  { value: "access_difficult", label: "Erişim zorlaştı", hint: "Yol zor geçiliyor", defaultHours: 12, group: "access" },
  { value: "mud_risk", label: "Çamur / batma riski", hint: "Zemin yumuşak veya çamurlu", defaultHours: 12, group: "access" },
  { value: "fire_or_flood_access_issue", label: "Yangın / sel erişim sorunu", hint: "Yangın, sel veya benzeri nedenle", defaultHours: 24, group: "access" },
  { value: "overnight_restriction", label: "Geceleme kısıtlaması", hint: "Konaklama kısıtlandığı söylendi", defaultHours: 24, group: "night" },
  { value: "official_warning", label: "Resmî uyarı", hint: "Zabıta/jandarma uyarısı", defaultHours: 24, group: "night" },
  { value: "fine_reported", label: "Ceza", hint: "Ceza kesildiği bildirildi", defaultHours: 24, group: "night" },
  { value: "fresh_water_unavailable", label: "Tatlı su kullanılamıyor", hint: "Su yok veya çalışmıyor", defaultHours: 12, group: "service" },
  { value: "electricity_unavailable", label: "Elektrik kullanılamıyor", hint: "Elektrik yok veya kesik", defaultHours: 12, group: "service" },
  { value: "grey_water_unavailable", label: "Gri su boşaltma kullanılamıyor", hint: "Boşaltma noktası çalışmıyor", defaultHours: 12, group: "service" },
  { value: "black_water_unavailable", label: "Siyah su boşaltma kullanılamıyor", hint: "Kaset boşaltma çalışmıyor", defaultHours: 12, group: "service" },
  { value: "full", label: "Alan dolu", hint: "Yer kalmadı", defaultHours: 6, group: "capacity" },
];

export const LIVE_TYPE_GROUP_LABEL: Record<LiveTypeOption["group"], string> = {
  access: "Yol ve erişim",
  night: "Geceleme ve resmî durum",
  service: "Hizmetler",
  capacity: "Doluluk",
};

/** Ciddi türler: formda "yanlışsa başkalarını yönlendirir" uyarısı gösterilir. */
export const SERIOUS_TYPES: ReadonlySet<LiveReportType> = new Set<LiveReportType>([
  "road_closed",
  "fire_or_flood_access_issue",
  "overnight_restriction",
  "fine_reported",
]);

export function labelOfType(type: LiveReportType): string {
  return LIVE_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type;
}

interface SeverityStyle {
  Icon: typeof AlertTriangle;
  /** Ekran okuyucu ve tooltip için metin - renk tek kanal değil. */
  label: string;
  text: string;
  border: string;
  bg: string;
}

export const SEVERITY_STYLE: Record<LiveSeverity, SeverityStyle> = {
  critical: { Icon: OctagonAlert, label: "Kritik", text: "text-accent-rust", border: "border-accent-rust", bg: "bg-accent-rust/10" },
  serious: { Icon: AlertTriangle, label: "Ciddi", text: "text-accent-rust", border: "border-accent-rust/70", bg: "bg-accent-rust/5" },
  caution: { Icon: AlertTriangle, label: "Dikkat", text: "text-accent-brass", border: "border-accent-brass/70", bg: "bg-accent-brass/5" },
  info: { Icon: Info, label: "Bilgi", text: "text-ink-muted", border: "border-border-muted", bg: "bg-slate-dark" },
};

export const ACCESS_STYLE: Record<Exclude<LiveAccess, "ok">, SeverityStyle & { headline: string }> = {
  not_recommended: { ...SEVERITY_STYLE.critical, headline: "Şu anda erişim önerilmiyor" },
  caution: { ...SEVERITY_STYLE.caution, headline: "Dikkatli erişim" },
};

export const TRUST_STYLE: Record<LiveTrustLevel, { Icon: typeof User; text: string }> = {
  moderator_confirmed: { Icon: ShieldCheck, text: "text-accent-green" },
  well_supported: { Icon: Users, text: "text-ink" },
  supported: { Icon: Users, text: "text-ink" },
  single_report: { Icon: User, text: "text-ink-muted" },
};

export const TRUST_SHORT_TEXT: Record<LiveTrustLevel, string> = {
  moderator_confirmed: "moderatör onayladı",
  well_supported: "birden fazla bağımsız bildirim",
  supported: "destekleniyor",
  single_report: "tek kişi bildirdi, doğrulanmadı",
};

export const OUTCOME_TEXT: Record<LiveReportOutcome, string> = {
  active: "Aktif",
  expired: "Süresi doldu",
  withdrawn: "Geri çekildi",
  rejected: "Reddedildi",
};

export const MODERATION_STATE_TEXT: Record<ReportModerationState, string> = {
  pending: "Moderatör incelemesi bekliyor",
  confirmed: "Moderatör onayladı",
  rejected: "Moderatör reddetti",
  withdrawn: "Geri çekildi",
};

/** ISO zamanından kalan süre: "3 sa 20 dk kaldı" / "Süresi doldu" (backend `remaining_text` ile aynı biçim). */
export function remainingFromIso(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 60000));
  if (minutes <= 0) return "Süresi doldu";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) return `${mins} dk kaldı`;
  if (mins === 0) return `${hours} saat kaldı`;
  return `${hours} sa ${mins} dk kaldı`;
}

/** "21 Eyl 10:30" - yerel saat. */
export function formatDateTimeTr(iso: string): string {
  return new Date(iso).toLocaleString("tr-TR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
