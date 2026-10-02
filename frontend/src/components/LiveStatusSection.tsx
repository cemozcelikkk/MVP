/**
 * "Güncel Saha Durumu" - eski "Zabıta Uyarısı" bandının yerini alan bölüm (`SpotDetailSidebar` içinde).
 *
 * Aktif süreli bildirimler: en ciddi en üstte; her satırda tür, bağımsız bildiren sayısı,
 * yerinde bulunan kullanıcı desteği, kalan süre, moderasyon durumu ve (kendi bildirimin için)
 * geri çekme eylemi. Süresi geçmiş / geri çekilmiş / reddedilmiş bildirimler sayfalı
 * "Geçmiş bildirimler" altında.
 *
 * Karar mantığı (şiddet, güven, erişim kararı) backend'de; burası KARARLI kodları ikon + kısa
 * metinle gösterir. Kullanıcı notu React tarafından metin olarak kaçışlanır (HTML olarak
 * render EDİLMEZ).
 */
import { AlertTriangle, ChevronDown, ChevronUp, Clock, History, ShieldCheck, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  fetchLiveReportHistory,
  fetchLiveReports,
  withdrawLiveReport,
  type LiveReportGroup,
  type LiveReportHistoryItem,
  type SpotLiveReports,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import {
  ACCESS_STYLE,
  formatDateTimeTr,
  MODERATION_STATE_TEXT,
  OUTCOME_TEXT,
  SEVERITY_STYLE,
  TRUST_STYLE,
} from "../lib/liveStatus";

const HISTORY_PAGE_SIZE = 5;

interface Props {
  spotId: string;
  /** Artınca (bildirim eklendi/geri çekildi) yeniden yüklenir - sayfa yenilemesi gerekmez. */
  refreshKey: number;
  /** Her başarılı yüklemede/geri çekmede güncel durum üst bileşene bildirilir (pin/sidebar güncellensin). */
  onLive: (live: SpotLiveReports, options: { changedByUser: boolean }) => void;
  onReportClick: () => void;
}

function GroupCard({
  group,
  onWithdraw,
  isWithdrawing,
}: {
  group: LiveReportGroup;
  onWithdraw: (reportId: string) => void;
  isWithdrawing: boolean;
}) {
  const sev = SEVERITY_STYLE[group.severity];
  const trust = TRUST_STYLE[group.trust_level];
  const TrustIcon = trust.Icon;
  const SevIcon = sev.Icon;

  return (
    <li
      className={`border ${sev.border} ${sev.bg} p-3`}
      data-testid={`live-group-${group.report_type}`}
      data-severity={group.severity}
      data-trust={group.trust_level}
    >
      <div className={`flex items-start gap-2 ${sev.text}`}>
        <SevIcon size={16} className="mt-0.5 shrink-0" role="img" aria-label={sev.label} />
        <p className="text-sm font-semibold leading-snug text-ink">{group.label}</p>
      </div>

      <div className="mt-2 flex flex-col gap-1 pl-6 font-mono text-[11px] leading-snug">
        <p className={`flex items-start gap-1.5 ${trust.text}`}>
          <TrustIcon size={12} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            {group.evidence_text}
            <span className="text-ink-muted"> · {group.trust_text}</span>
          </span>
        </p>
        <p className="flex items-center gap-1.5 text-ink-muted">
          <Clock size={12} className="shrink-0" aria-hidden />
          {group.remaining_text}
        </p>
        <p className={`flex items-center gap-1.5 ${group.moderator_confirmed ? "text-accent-green" : "text-ink-muted"}`}>
          <ShieldCheck size={12} className="shrink-0" aria-hidden />
          {group.moderator_confirmed ? MODERATION_STATE_TEXT.confirmed : MODERATION_STATE_TEXT.pending}
        </p>
      </div>

      {group.notes.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1 pl-6">
          {group.notes.map((note, index) => (
            // Kullanıcı metni: JSX ile metin olarak yazılır (HTML olarak enjekte edilmez).
            <li key={index} className="border-l border-border-muted pl-2 text-xs text-ink-muted">
              “{note}”
            </li>
          ))}
        </ul>
      ) : null}

      {group.my_report_id ? (
        <div className="mt-2 pl-6">
          <button
            type="button"
            data-testid={`withdraw-${group.report_type}`}
            onClick={() => onWithdraw(group.my_report_id as string)}
            disabled={isWithdrawing}
            className="flex min-h-[40px] items-center gap-1.5 rounded-full border border-border-muted px-3 py-1.5 text-[13px] font-medium text-ink-muted transition-colors hover:border-accent-rust hover:text-accent-rust disabled:opacity-50"
          >
            <Undo2 size={13} aria-hidden />
            {isWithdrawing ? "Geri çekiliyor…" : "Bildirimimi geri çek"}
          </button>
        </div>
      ) : null}
    </li>
  );
}

function HistoryRow({ item }: { item: LiveReportHistoryItem }) {
  return (
    <li className="flex items-start justify-between gap-2 border-b border-border-muted/60 py-1.5 font-mono text-[11px]">
      <span className="text-ink">
        {item.label}
        {item.is_mine ? <span className="text-ink-muted"> · senin bildirimin</span> : null}
      </span>
      <span className="shrink-0 text-right text-ink-muted">
        {OUTCOME_TEXT[item.outcome]}
        <br />
        {formatDateTimeTr(item.starts_at)}
      </span>
    </li>
  );
}

export default function LiveStatusSection({ spotId, refreshKey, onLive, onReportClick }: Props) {
  const [live, setLive] = useState<SpotLiveReports | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<LiveReportHistoryItem[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Aktif bildirimler: mount'ta ve `refreshKey` değişince (bildirim/geri çekme sonrası).
  useEffect(() => {
    let cancelled = false;
    fetchLiveReports(spotId)
      .then((data) => {
        if (cancelled) return;
        setLive(data);
        setError(null);
        onLive(data, { changedByUser: false });
      })
      .catch(() => !cancelled && setError("Güncel saha durumu yüklenemedi."))
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
    // `onLive` her render'da yeni referans olabilir; yalnızca spot/refreshKey değişince yükle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spotId, refreshKey]);

  const loadHistory = useCallback(
    async (offset: number) => {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const page = await fetchLiveReportHistory(spotId, HISTORY_PAGE_SIZE, offset);
        setHistory((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setHistoryTotal(page.total);
      } catch {
        setHistoryError("Geçmiş bildirimler yüklenemedi.");
      } finally {
        setHistoryLoading(false);
      }
    },
    [spotId],
  );

  // Geçmiş açıkken bildirim/geri çekme sonrası (refreshKey) baştan yükle; kapalıyken hiç çağrılmaz.
  useEffect(() => {
    if (showHistory) void loadHistory(0);
  }, [showHistory, refreshKey, loadHistory]);

  async function handleWithdraw(reportId: string) {
    setWithdrawingId(reportId);
    setActionError(null);
    try {
      const response = await withdrawLiveReport(reportId);
      setLive(response.live);
      onLive(response.live, { changedByUser: true });
    } catch (err) {
      setActionError(extractErrorMessage(err, "Bildirim geri çekilemedi."));
    } finally {
      setWithdrawingId(null);
    }
  }

  const verdict = live && live.summary.access !== "ok" ? ACCESS_STYLE[live.summary.access] : null;
  const VerdictIcon = verdict?.Icon ?? AlertTriangle;
  const hasMoreHistory = history.length < historyTotal;

  return (
    <div className="border-b border-border-muted p-4" data-testid="live-status">
      <p className="mb-2 font-display text-[17px] font-medium text-text-primary">Güncel Saha Durumu</p>

      {isLoading ? (
        <p className="font-mono text-xs text-ink-muted">Yükleniyor…</p>
      ) : error || !live ? (
        <p className="font-mono text-xs text-accent-rust">{error ?? "Yüklenemedi."}</p>
      ) : (
        <>
          {verdict ? (
            <div
              className={`mb-3 flex items-center gap-2 border ${verdict.border} ${verdict.bg} px-3 py-2 ${verdict.text}`}
              data-testid="access-verdict"
              data-access={live.summary.access}
              role="status"
            >
              <VerdictIcon size={18} className="shrink-0" aria-hidden />
              <span className="text-sm font-semibold">{verdict.headline}</span>
            </div>
          ) : null}

          {live.groups.length === 0 ? (
            <p className="text-sm leading-relaxed text-ink-muted" data-testid="live-empty">
              Şu anda aktif bir saha bildirimi yok.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {live.groups.map((group) => (
                <GroupCard
                  key={group.report_type}
                  group={group}
                  onWithdraw={handleWithdraw}
                  isWithdrawing={withdrawingId === group.my_report_id}
                />
              ))}
            </ul>
          )}

          {actionError ? <p className="mt-2 font-mono text-[11px] text-accent-rust">{actionError}</p> : null}

          <p className="mt-3 font-mono text-[10px] leading-relaxed text-ink-muted/80">
            Bildirimler topluluk tarafından yapılır, resmî karar değildir ve süreli olarak geçerlidir; süre dolunca
            kendiliğinden kalkar. Noktanın kalıcı bilgileri değişmez.
          </p>

          <button
            type="button"
            onClick={onReportClick}
            className="mt-2 min-h-[44px] w-full rounded-full border border-border-muted px-3 py-2 text-sm font-semibold text-ink-muted transition-colors hover:border-accent-rust hover:text-accent-rust"
          >
            Durum bildir
          </button>

          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            aria-expanded={showHistory}
            data-testid="toggle-live-history"
            className="mt-1 flex min-h-[40px] items-center gap-1.5 text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
          >
            <History size={13} aria-hidden />
            Geçmiş bildirimler
            {showHistory ? <ChevronUp size={12} aria-hidden /> : <ChevronDown size={12} aria-hidden />}
          </button>

          {showHistory ? (
            <div data-testid="live-history">
              {history.length === 0 && !historyLoading && !historyError ? (
                <p className="font-mono text-[11px] text-ink-muted">Geçmiş bildirim yok.</p>
              ) : (
                <ul className="border-t border-border-muted/60">
                  {history.map((item) => (
                    <HistoryRow key={item.id} item={item} />
                  ))}
                </ul>
              )}
              {historyError ? <p className="font-mono text-[11px] text-accent-rust">{historyError}</p> : null}
              {hasMoreHistory ? (
                <button
                  type="button"
                  disabled={historyLoading}
                  onClick={() => void loadHistory(history.length)}
                  className="mt-1 min-h-[40px] text-[13px] font-medium text-accent-brass transition-colors hover:text-ink disabled:opacity-50"
                >
                  {historyLoading ? "Yükleniyor…" : `Daha fazla göster (${historyTotal - history.length})`}
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
