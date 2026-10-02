/**
 * "Karavan Profili ve Otomatik Nokta Uyumluluğu" - `SpotDetailSidebar`da
 * başlık/aktif saha uyarısından hemen sonra gösterilen uyumluluk kartı.
 *
 * Karar mantığının TAMAMI backend'de (`compatibility_service`) - burası
 * sadece `status`/`reasons`i gösteriyor, hiçbir eşik/kural burada tekrar
 * edilmiyor (bkz. görev tanımı: "Eşik değerlerini React bileşenlerine
 * dağıtma").
 */
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  LogIn,
  Plus,
  Repeat,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  fetchSpotCompatibility,
  type CompatibilityReasonSeverity,
  type CompatibilityStatus,
  type SpotCompatibilityResult,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { ACCESS_STYLE } from "../lib/liveStatus";
import { useAuthStore } from "../store/useAuthStore";
import { useVehicleProfileStore } from "../store/useVehicleProfileStore";

const STATUS_CONFIG: Record<
  CompatibilityStatus,
  { label: string; icon: typeof CheckCircle2; border: string; bg: string; text: string }
> = {
  // Uygun: mat yeşil.
  compatible: {
    label: "Uygun",
    icon: CheckCircle2,
    border: "border-accent-green",
    bg: "bg-accent-green/10",
    text: "text-accent-green",
  },
  // Dikkatli Giriş: mat pirinç sarısı.
  caution: {
    label: "Dikkatli Giriş",
    icon: AlertTriangle,
    border: "border-accent-brass",
    bg: "bg-accent-brass/10",
    text: "text-accent-brass",
  },
  // Uygun Değil: pas kiremiti.
  not_compatible: {
    label: "Uygun Değil",
    icon: XCircle,
    border: "border-accent-rust",
    bg: "bg-accent-rust/10",
    text: "text-accent-rust",
  },
  // Veri Yetersiz: nötr gri.
  insufficient_data: {
    label: "Veri Yetersiz",
    icon: HelpCircle,
    border: "border-border-muted",
    bg: "bg-surface-secondary",
    text: "text-ink-muted",
  },
};

const SEVERITY_DOT_COLOR: Record<CompatibilityReasonSeverity, string> = {
  blocking: "bg-accent-rust",
  warning: "bg-accent-brass",
  unknown: "bg-ink-muted",
  info: "bg-accent-green",
};

function CardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-b border-border-muted p-4">
      <p className="mb-2 font-display text-[17px] font-medium text-text-primary">
        Araç uyumluluğu
      </p>
      {children}
    </div>
  );
}

export default function CompatibilityCard({ spotId, refreshKey = 0 }: { spotId: string; refreshKey?: number }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const profiles = useVehicleProfileStore((s) => s.profiles);
  const hasFetchedProfiles = useVehicleProfileStore((s) => s.hasFetched);
  const fetchProfiles = useVehicleProfileStore((s) => s.fetchProfiles);
  const openVehicleModal = useVehicleProfileStore((s) => s.openModal);

  const activeProfile = profiles.find((p) => p.is_active) ?? null;

  // Araç listesi henüz hiç çekilmemişse (kullanıcı sayfayı yeni açtı, hiç
  // "Araçlarım"a girmedi) burada lazy olarak çek - AuthWidget'taki buton
  // gibi başka bir tetikleyiciye bağımlı olmasın.
  useEffect(() => {
    if (isAuthenticated && !hasFetchedProfiles) fetchProfiles();
  }, [isAuthenticated, hasFetchedProfiles, fetchProfiles]);

  const [result, setResult] = useState<SpotCompatibilityResult | null>(null);
  const [isLoadingResult, setIsLoadingResult] = useState(false);
  const [resultError, setResultError] = useState<string | null>(null);
  const [showAllReasons, setShowAllReasons] = useState(false);

  useEffect(() => {
    setShowAllReasons(false);
    setResult(null);
    setResultError(null);
    if (!isAuthenticated || !activeProfile) return;

    let cancelled = false;
    setIsLoadingResult(true);
    fetchSpotCompatibility(spotId, activeProfile.id)
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch((err) => {
        if (!cancelled) setResultError(extractErrorMessage(err, "Uyumluluk hesaplanamadı."));
      })
      .finally(() => {
        if (!cancelled) setIsLoadingResult(false);
      });
    return () => {
      cancelled = true;
    };
    // activeProfile.id string olarak karşılaştırılıyor - referans her
    // fetchProfiles'ta değişse bile id aynıysa gereksiz yeniden istek atılmaz.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spotId, isAuthenticated, activeProfile?.id, refreshKey]);

  if (!isAuthenticated) {
    return (
      <CardShell>
        <p className="mb-3 text-sm leading-relaxed text-ink-muted">
          Bu noktanın aracınıza uygunluğunu görmek için giriş yapın.
        </p>
        <button
          type="button"
          onClick={openAuthModal}
          className="flex items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary px-3 py-1.5 text-[13px] font-medium text-ink transition-colors hover:border-ink-muted"
        >
          <LogIn size={13} />
          Giriş Yap
        </button>
      </CardShell>
    );
  }

  if (!activeProfile) {
    return (
      <CardShell>
        <p className="mb-3 text-sm leading-relaxed text-ink-muted">
          Aracınızı ekleyerek bu noktanın size uygun olup olmadığını otomatik görebilirsiniz.
        </p>
        <button
          type="button"
          onClick={() => openVehicleModal({ startInAddMode: true })}
          className="flex items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary px-3 py-1.5 text-[13px] font-medium text-ink transition-colors hover:border-accent-green hover:text-accent-green"
        >
          <Plus size={13} />
          Araç Profili Ekle
        </button>
      </CardShell>
    );
  }

  if (isLoadingResult) {
    return (
      <CardShell>
        <p className="font-mono text-xs text-ink-muted">Uyumluluk hesaplanıyor…</p>
      </CardShell>
    );
  }

  if (resultError) {
    return (
      <CardShell>
        <p className="font-mono text-xs text-accent-rust">{resultError}</p>
      </CardShell>
    );
  }

  if (!result) return null;

  const liveAccess = result.live_access && result.live_access.status !== "ok" ? result.live_access : null;
  const liveStyle = liveAccess ? ACCESS_STYLE[liveAccess.status as "caution" | "not_recommended"] : null;
  const LiveIcon = liveStyle?.Icon;
  const config = STATUS_CONFIG[result.status];
  const StatusIcon = config.icon;
  const nonInfoReasons = result.reasons.filter((r) => r.severity !== "info");
  const highlightReasons = nonInfoReasons.length > 0 ? nonInfoReasons.slice(0, 2) : result.reasons.slice(0, 1);
  const hasMoreReasons = result.reasons.length > highlightReasons.length;

  return (
    <CardShell>
      <div className={`border ${config.border} ${config.bg} p-3`}>
        <p className="mb-1 text-[12px] font-medium text-ink-muted">Fiziksel uygunluk</p>
        <div className={`mb-1.5 flex items-center gap-2 ${config.text}`}>
          <StatusIcon size={16} aria-hidden />
          <span
            data-testid="compatibility-status"
            data-status={result.status}
            className="text-sm font-semibold"
          >
            {config.label}
          </span>
        </div>

        <p className="mb-2 text-sm leading-relaxed text-ink">{result.summary}</p>

        {/* Şu anki erişim (aktif süreli bildirimler) - fiziksel uygunluktan AYRI; o karar değişmez. */}
        {liveAccess && liveStyle && LiveIcon ? (
          <div
            data-testid="live-access"
            data-access={liveAccess.status}
            className={`mb-2 border ${liveStyle.border} ${liveStyle.bg} p-2.5`}
          >
            <p className="mb-1 text-xs leading-relaxed text-ink">{liveAccess.physical_text}.</p>
            {liveAccess.live_text ? (
              <p className={`mb-1.5 text-xs font-semibold leading-relaxed ${liveStyle.text}`}>
                {liveAccess.live_text}.
              </p>
            ) : null}
            <p className={`flex items-center gap-1.5 text-[13px] font-semibold ${liveStyle.text}`}>
              <LiveIcon size={14} aria-hidden />
              {liveAccess.headline}
            </p>
          </div>
        ) : null}

        <p className="mb-2 font-mono text-[11px] text-ink-muted">
          Aktif araç: <span className="text-ink">{activeProfile.name}</span>
        </p>

        {highlightReasons.length > 0 ? (
          <ul className="mb-2 flex flex-col gap-1">
            {highlightReasons.map((reason) => (
              <li key={reason.code} className="flex items-start gap-1.5 text-xs text-ink-muted">
                <span
                  className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${SEVERITY_DOT_COLOR[reason.severity]}`}
                  aria-hidden
                />
                {reason.message}
              </li>
            ))}
          </ul>
        ) : null}

        {hasMoreReasons ? (
          <button
            type="button"
            onClick={() => setShowAllReasons((v) => !v)}
            className="mb-2 flex items-center gap-1 text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
          >
            {showAllReasons ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Tüm Detayları Göster
          </button>
        ) : null}

        {showAllReasons ? (
          <ul className="mb-2 flex flex-col gap-1 border-t border-border-muted/60 pt-2">
            {result.reasons.map((reason) => (
              <li key={reason.code} className="flex items-start gap-1.5 text-xs text-ink-muted">
                <span
                  className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${SEVERITY_DOT_COLOR[reason.severity]}`}
                  aria-hidden
                />
                {reason.message}
              </li>
            ))}
          </ul>
        ) : null}

        <button
          type="button"
          onClick={() => openVehicleModal()}
          className="mb-2 flex items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary px-2.5 py-1.5 text-[13px] font-medium text-ink-muted transition-colors hover:border-ink-muted hover:text-ink"
        >
          <Repeat size={12} />
          Aracımı Değiştir
        </button>

        <p className="font-mono text-[10px] leading-relaxed text-ink-muted/80">
          Uyumluluk sonucu topluluk tarafından bildirilen verilere dayanır. Yol ve saha koşulları
          değişebilir.
        </p>
      </div>
    </CardShell>
  );
}
