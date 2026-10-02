import ContentModerationTab from "./ContentModerationTab";
/**
 * Moderasyon ekranı (yalnızca moderatör/admin): canlı bildirimleri incele, onayla / reddet /
 * geri çek, işlem geçmişini gör ve önceki adımdaki saha doğrulama denetimine (`verifications/audit`)
 * eriş. Yetki backend'de zorlanır (`require_moderator`); buradaki rol kontrolü yalnızca arayüzü gizler.
 *
 * Kendi dialog kabuğunu taşır (ortak `Modal` yerine) ki sekme çubuğu içerik
 * kayarken SABİT kalsın - uzun bekleyen listelerde sekmeler her zaman erişilir.
 * Kullanıcı metinleri (not, ad) JSX ile metin olarak yazılır - HTML olarak render EDİLMEZ.
 */
import { ChevronLeft, ChevronRight, ClipboardList, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  fetchModerationEvents,
  fetchModerationReports,
  fetchVerificationAudit,
  moderateLiveReport,
  type ModerationAction,
  type ModerationEvent,
  type ModerationReportRow,
  type ModerationView,
  type VerificationAuditRow,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { formatDateTimeTr, MODERATION_STATE_TEXT, OUTCOME_TEXT, SEVERITY_STYLE } from "../lib/liveStatus";
import { useAuthStore } from "../store/useAuthStore";
import { useModerationStore } from "../store/useModerationStore";
import Button from "./ui/Button";
import { INPUT_CLASS } from "./FormControls";

const PAGE_SIZE = 10;

type Tab = ModerationView | "audit" | "content";

const TABS: { value: Tab; label: string }[] = [
  { value: "content", label: "İçerik Bildirimleri" },
  { value: "pending", label: "Bekleyen" },
  { value: "active", label: "Aktif" },
  { value: "closed", label: "Reddedilen / Geri çekilen" },
  { value: "expired", label: "Süresi dolan" },
  { value: "audit", label: "Doğrulama denetimi" },
];

const ACTION_LABEL: Record<ModerationAction, string> = {
  confirm: "Onayla",
  reject: "Reddet",
  withdraw: "Geri çek",
};

const ROLE_TEXT = { user: "kullanıcı", moderator: "moderatör", admin: "yönetici" } as const;

function EventLine({ event }: { event: ModerationEvent }) {
  return (
    <li className="border-b border-border-light/60 py-1 text-xs text-text-secondary">
      <span className="font-medium text-text-primary">{event.actor_name ?? "Silinmiş kullanıcı"}</span> (
      {ROLE_TEXT[event.actor_role]}) · {MODERATION_STATE_TEXT[event.from_state]} → {MODERATION_STATE_TEXT[event.to_state]} ·{" "}
      {formatDateTimeTr(event.created_at)}
      {event.note ? <span> · “{event.note}”</span> : null}
    </li>
  );
}

function ReportRow({
  row,
  onChanged,
  onAudit,
}: {
  row: ModerationReportRow;
  onChanged: () => void;
  onAudit: (spotId: string) => void;
}) {
  const sev = SEVERITY_STYLE[row.severity];
  const SevIcon = sev.Icon;
  const [pending, setPending] = useState<ModerationAction | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ModerationEvent[] | null>(null);
  const [showEvents, setShowEvents] = useState(false);

  // Pending/active satırlarda onay-red-geri çek; terminal (reddedilmiş/geri çekilmiş) satırlarda işlem yok.
  const canAct = row.moderation_state === "pending" || row.moderation_state === "confirmed";
  const available: ModerationAction[] = canAct
    ? row.moderation_state === "pending"
      ? ["confirm", "reject", "withdraw"]
      : ["reject", "withdraw"]
    : [];

  async function confirmAction() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await moderateLiveReport(row.id, pending, note.trim() || null);
      setPending(null);
      setNote("");
      onChanged();
    } catch (err) {
      setError(extractErrorMessage(err, "İşlem uygulanamadı."));
    } finally {
      setBusy(false);
    }
  }

  async function toggleEvents() {
    const next = !showEvents;
    setShowEvents(next);
    if (next && events === null) {
      try {
        setEvents(await fetchModerationEvents(row.id));
      } catch {
        setError("İşlem geçmişi yüklenemedi.");
      }
    }
  }

  return (
    <li className={`rounded-md border ${sev.border} ${sev.bg} p-3`} data-testid={`mod-row-${row.id}`}>
      <div className={`flex items-start gap-2 ${sev.text}`}>
        <SevIcon size={16} className="mt-0.5 shrink-0" role="img" aria-label={sev.label} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text-primary">{row.label}</p>
          <p className="text-xs text-text-secondary">{row.spot_title}</p>
        </div>
        <span className="shrink-0 text-xs font-medium text-text-secondary">{OUTCOME_TEXT[row.outcome]}</span>
      </div>

      <div className="mt-2 flex flex-col gap-0.5 pl-6 text-xs text-text-secondary">
        <p>
          Bildiren: <span className="font-medium text-text-primary">{row.reporter_name ?? "silinmiş kullanıcı"}</span>
          {row.reporter_on_site ? " · bildirim anında yerinde (son 72 sa check-in)" : " · yerinde olduğu doğrulanmadı"}
        </p>
        <p className="font-mono">
          {formatDateTimeTr(row.starts_at)} → {formatDateTimeTr(row.expires_at)}
          {row.duration_hours ? ` (${row.duration_hours} saat)` : ""}
          {row.is_legacy ? " · eski kayıt" : ""}
        </p>
        <p>Durum: {MODERATION_STATE_TEXT[row.moderation_state]}</p>
        {row.note ? <p className="text-text-primary">“{row.note}”</p> : null}
        {row.last_event ? (
          <p>
            Son işlem: <span className="font-medium text-text-primary">{row.last_event.actor_name ?? "silinmiş kullanıcı"}</span> (
            {ROLE_TEXT[row.last_event.actor_role]}) · {formatDateTimeTr(row.last_event.created_at)}
          </p>
        ) : null}
      </div>

      {pending ? (
        <div className="mt-2 pl-6">
          <input
            type="text"
            value={note}
            maxLength={280}
            onChange={(event) => setNote(event.target.value)}
            placeholder={`${ACTION_LABEL[pending]} notu (isteğe bağlı)`}
            className={`mb-1.5 ${INPUT_CLASS}`}
          />
          <div className="flex gap-2">
            <Button variant="danger-solid" size="sm" disabled={busy} onClick={confirmAction} data-testid="mod-confirm-action">
              {busy ? "…" : `${ACTION_LABEL[pending]} — Onayla`}
            </Button>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => setPending(null)}>
              Vazgeç
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
          {available.map((action) => (
            <Button
              key={action}
              variant={action === "confirm" ? "secondary" : "secondary"}
              size="sm"
              data-testid={`mod-${action}`}
              onClick={() => setPending(action)}
              className={action === "confirm" ? "!border-accent-green !text-accent-green" : "!text-warning-rust"}
            >
              {ACTION_LABEL[action]}
            </Button>
          ))}
          <Button variant="ghost" size="sm" onClick={toggleEvents} aria-expanded={showEvents}>
            İşlem geçmişi
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onAudit(row.spot_id)}>
            Doğrulama kayıtları
          </Button>
        </div>
      )}

      {showEvents ? (
        <div className="mt-2 pl-6">
          {events === null ? (
            <p className="text-xs text-text-secondary">Yükleniyor…</p>
          ) : events.length === 0 ? (
            <p className="text-xs text-text-secondary">Henüz işlem yok.</p>
          ) : (
            <ul>
              {events.map((event) => (
                <EventLine key={event.id} event={event} />
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {error ? <p className="mt-2 pl-6 text-xs text-warning-rust">{error}</p> : null}
    </li>
  );
}

function AuditTab({ initialSpotId }: { initialSpotId: string | null }) {
  const [spotId, setSpotId] = useState(initialSpotId ?? "");
  const [rows, setRows] = useState<VerificationAuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const load = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      setRows(await fetchVerificationAudit(id.trim()));
    } catch (err) {
      setRows(null);
      setError(extractErrorMessage(err, "Doğrulama kayıtları yüklenemedi."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Bir bildirim satırından gelindiyse otomatik yükle.
  useEffect(() => {
    if (initialSpotId) void load(initialSpotId);
  }, [initialSpotId, load]);

  return (
    <div>
      <form
        className="mb-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (spotId.trim()) void load(spotId);
        }}
      >
        <input
          type="text"
          value={spotId}
          onChange={(event) => setSpotId(event.target.value)}
          placeholder="Nokta kimliği (UUID)"
          aria-label="Nokta kimliği"
          className={`flex-1 font-mono ${INPUT_CLASS}`}
        />
        <Button type="submit" variant="primary" disabled={isLoading || !spotId.trim()}>
          Getir
        </Button>
      </form>
      {error ? <p className="text-xs text-warning-rust">{error}</p> : null}
      {isLoading ? <p className="text-xs text-text-secondary">Yükleniyor…</p> : null}
      {rows && !isLoading ? (
        rows.length === 0 ? (
          <p className="text-xs text-text-secondary">Bu nokta için doğrulama kaydı yok.</p>
        ) : (
          <ul data-testid="audit-rows">
            {rows.map((row) => (
              <li key={row.id} className="border-b border-border-light/60 py-1.5 text-xs text-text-secondary">
                <span className="font-medium text-text-primary">{row.field}</span> →{" "}
                <span className="font-medium text-text-primary">{row.answer}</span> · {formatDateTimeTr(row.created_at)} ·{" "}
                {row.is_current ? "güncel" : "geçmiş"} · kullanıcı {row.user_id.slice(0, 8)}…
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}

export default function ModerationPanel() {
  const isOpen = useModerationStore((s) => s.isOpen);
  const auditSpotId = useModerationStore((s) => s.auditSpotId);
  const close = useModerationStore((s) => s.close);
  const openAudit = useModerationStore((s) => s.openAudit);
  const role = useAuthStore((s) => s.user?.role);
  const isStaff = role === "moderator" || role === "admin";

  const [tab, setTab] = useState<Tab>("pending");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<ModerationReportRow[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (view: ModerationView, off: number) => {
    setIsLoading(true);
    setError(null);
    try {
      const page = await fetchModerationReports(view, PAGE_SIZE, off);
      setItems(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(extractErrorMessage(err, "Bildirimler yüklenemedi."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Denetim kısayolundan gelindiyse o sekmeyi aç.
  useEffect(() => {
    if (isOpen && auditSpotId) setTab("audit");
  }, [isOpen, auditSpotId]);

  useEffect(() => {
    if (isOpen && isStaff && tab !== "audit" && tab !== "content") void load(tab, offset);
  }, [isOpen, isStaff, tab, offset, load]);

  if (!isOpen || !isStaff) return null;

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="animate-overlay-fade-in fixed inset-0 z-40 flex items-end justify-center bg-text-primary/50 sm:items-center sm:p-4" onClick={close}>
      <div
        className="animate-sheet-rise-in flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-lg bg-surface-primary text-text-primary shadow-modal sm:max-w-2xl sm:rounded-lg"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Moderasyon"
        data-testid="moderation-panel"
      >
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border-light px-5 py-4">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-accent-green" aria-hidden />
            <div>
              <h2 className="text-lg font-semibold text-text-primary">Moderasyon</h2>
              <p className="text-xs text-text-secondary">Canlı saha bildirimleri ve doğrulama denetimi</p>
            </div>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="Kapat"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-border-light p-3" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.value}
              type="button"
              role="tab"
              aria-selected={tab === t.value}
              data-testid={`mod-tab-${t.value}`}
              onClick={() => {
                setTab(t.value);
                setOffset(0);
              }}
              className={[
                "min-h-touch rounded-md border px-3 text-xs font-semibold transition-colors",
                tab === t.value
                  ? "border-accent-green bg-accent-green/10 text-accent-green"
                  : "border-border-light text-text-secondary hover:text-text-primary",
              ].join(" ")}
            >
              {t.value === "audit" ? (
                <span className="flex items-center gap-1.5">
                  <ClipboardList size={12} aria-hidden />
                  {t.label}
                </span>
              ) : (
                t.label
              )}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {tab === "content" ? <ContentModerationTab /> : tab === "audit" ? (
            <AuditTab key={auditSpotId ?? "manual"} initialSpotId={auditSpotId} />
          ) : (
            <>
              {error ? <p className="mb-2 text-xs text-warning-rust">{error}</p> : null}
              {isLoading && items.length === 0 ? (
                <p className="text-xs text-text-secondary">Yükleniyor…</p>
              ) : items.length === 0 ? (
                <p className="text-xs text-text-secondary" data-testid="mod-empty">
                  Bu görünümde bildirim yok.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {items.map((row) => (
                    <ReportRow key={row.id} row={row} onChanged={() => void load(tab, offset)} onAudit={openAudit} />
                  ))}
                </ul>
              )}
              {total > PAGE_SIZE ? (
                <div className="mt-3 flex items-center justify-between text-xs text-text-secondary">
                  <button
                    type="button"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                    aria-label="Önceki sayfa"
                    className="flex min-h-touch items-center gap-1 rounded-md border border-border-light px-3 disabled:opacity-40"
                  >
                    <ChevronLeft size={14} aria-hidden />
                    Önceki
                  </button>
                  <span>
                    {page}/{pageCount} · toplam {total}
                  </span>
                  <button
                    type="button"
                    disabled={offset + PAGE_SIZE >= total}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                    aria-label="Sonraki sayfa"
                    className="flex min-h-touch items-center gap-1 rounded-md border border-border-light px-3 disabled:opacity-40"
                  >
                    Sonraki
                    <ChevronRight size={14} aria-hidden />
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
