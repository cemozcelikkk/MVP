/**
 * "Saha bilgisi ne kadar güncel?" bölümü - `SpotDetailSidebar` içinde.
 *
 * Kendi verisini kendi çeker (bkz. `SpotReviewsSection`/`CompatibilityCard`: spotId al,
 * kendi istegini at). Güncellik/çelişki/güven kararları TAMAMEN backend'de
 * (`field_freshness.py`); burası yalnızca KARARLI kodları (`status`/`tone`/
 * `confidence`) ikon + kısa metinle gösterir - renk tek iletişim kanalı değildir.
 *
 * İlk bakışta yol/geceleme/su/elektrik; gri/siyah su açılır bölümde. Check-in yapmış
 * kullanıcıya "Saha bilgisini doğrula" akışı BURADA satır içi sunulur - kendiliğinden
 * açılan bir popup YOK (rahatsız etmeme kuralı).
 */
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Clock, HelpCircle, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import {
  fetchFieldFreshness,
  fetchMyVerifications,
  type FieldFreshness,
  type FreshnessStatus,
  type MyVerifications,
  type SpotFieldFreshness,
} from "../lib/api";
import { remainingFromIso, TRUST_SHORT_TEXT } from "../lib/liveStatus";
import { useAuthStore } from "../store/useAuthStore";
import VerifyFieldsModal from "./VerifyFieldsModal";

const STATUS_ICON: Record<FreshnessStatus, { Icon: typeof CheckCircle2; className: string; label: string }> = {
  recently_confirmed: { Icon: CheckCircle2, className: "text-accent-green", label: "Yakın zamanda destekleniyor" },
  service_issue_reported: { Icon: XCircle, className: "text-accent-rust", label: "Sorun bildirildi" },
  conflicting_reports: { Icon: AlertTriangle, className: "text-accent-brass", label: "Çelişkili bildirimler" },
  stale: { Icon: Clock, className: "text-ink-muted", label: "Bilgi eski" },
  unverified: { Icon: HelpCircle, className: "text-ink-muted", label: "Henüz doğrulanmadı" },
};

function formatDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("tr-TR", { day: "numeric", month: "long" });
}

function evidenceLine(f: FieldFreshness): string | null {
  if (f.participant_count === 0) return null;
  const parts: string[] = [];
  if (f.status === "conflicting_reports") {
    parts.push(`${f.participant_count} kişi çelişkili bildirdi`);
  } else if (f.participant_count === 1) {
    parts.push("tek kişi bildirdi");
  } else {
    parts.push(`${f.supporting_count} bağımsız kişi doğruladı`);
  }
  if (f.last_verified_on) parts.push(`son: ${formatDay(f.last_verified_on)}`);
  return parts.join(" · ");
}

function FreshnessRow({ item }: { item: FieldFreshness }) {
  const { Icon, className, label } = STATUS_ICON[item.status];
  const signals = item.live_signals?.length ? item.live_signals : item.live_signal ? [item.live_signal] : [];
  // Canlı bir sorun varken eski olumlu doğrulama yeşil/baskın DEĞİL: canlı sinyal önde, doğrulama ikincil.
  const overridden = item.live_overrides === true;
  const hasSignal = signals.length > 0;
  const topBlocking = signals[0]?.severity === "blocking";
  const ShownIcon = hasSignal ? (topBlocking ? XCircle : AlertTriangle) : Icon;
  const shownClass = hasSignal ? (topBlocking ? "text-accent-rust" : "text-accent-brass") : className;
  const shownLabel = hasSignal ? "Aktif geçici sorun bildirildi" : label;
  const evidence = evidenceLine(item);
  const verificationText = overridden ? `Önceki doğrulama: ${item.status_text}` : item.status_text;

  return (
    <div
      className="border-b border-border-muted/60 py-2.5"
      data-testid={`freshness-${item.field}`}
      data-status={item.status}
      data-live-overrides={overridden ? "true" : "false"}
    >
      <div className="flex items-start gap-2">
        <ShownIcon size={16} className={`mt-0.5 shrink-0 ${shownClass}`} aria-label={shownLabel} role="img" />
        <div className="min-w-0 flex-1">
          {signals.map((signal) => (
            <p
              key={signal.code}
              data-testid={`live-signal-${signal.code}`}
              className={[
                "mb-1 border px-2 py-1 text-sm leading-snug",
                signal.severity === "blocking"
                  ? "border-accent-rust text-accent-rust"
                  : "border-accent-brass text-accent-brass",
              ].join(" ")}
            >
              <span className="font-semibold">{signal.message}</span>
              <span className="block font-mono text-[11px] text-ink-muted">
                Süreli canlı bildirim
                {signal.trust_level ? ` · ${TRUST_SHORT_TEXT[signal.trust_level]}` : ""}
                {signal.expires_at ? ` · ${remainingFromIso(signal.expires_at)}` : ""}
              </span>
            </p>
          ))}
          <p className={hasSignal && overridden ? "text-xs leading-snug text-ink-muted" : "text-sm leading-snug text-ink"}>
            {verificationText}
          </p>
          {item.status === "conflicting_reports" ? (
            <p className="font-mono text-[11px] text-ink-muted">Kimse otomatik olarak &quot;doğru&quot; kabul edilmedi.</p>
          ) : null}
          {evidence ? <p className="font-mono text-[11px] text-ink-muted">{evidence}</p> : null}
          {item.reported_text ? (
            <p className="font-mono text-[11px] text-ink-muted">Bildirilen: {item.reported_text}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

interface Props {
  spotId: string;
  /** Artınca (canlı bildirim eklendi/geri çekildi) güncellik özeti yeniden yüklenir. */
  refreshKey?: number;
  /** Check-in başarılı olunca true olur - doğrulama hakkını (kendiliğinden popup AÇMADAN) tazeler. */
  checkInJustVerified?: boolean;
}

export default function FieldFreshnessSection({ spotId, checkInJustVerified, refreshKey = 0 }: Props) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);

  const [freshness, setFreshness] = useState<SpotFieldFreshness | null>(null);
  const [mineState, setMine] = useState<MyVerifications | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [justSent, setJustSent] = useState(false);
  // Çıkış yapıldıysa önceki oturumdan kalan hakkı GÖSTERME (state'i effect'te sıfırlamak yerine türet).
  const mine = isAuthenticated ? mineState : null;

  useEffect(() => {
    // Bileşen `SpotDetailSidebar`da spot başına yeniden mount edilir (key) - başlangıç
    // state'i (isLoading=true) yeterli, effect içinde tekrar set etmeye gerek yok.
    let cancelled = false;
    fetchFieldFreshness(spotId)
      .then((data) => !cancelled && setFreshness(data))
      .catch(() => !cancelled && setError("Saha bilgisi güncelliği yüklenemedi."))
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [spotId, refreshKey]);

  // Kullanıcının kendi doğrulama hakkı (check-in şartı) - oturum/check-in değişince tazelenir.
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    fetchMyVerifications(spotId)
      .then((data) => !cancelled && setMine(data))
      .catch(() => !cancelled && setMine(null));
    return () => {
      cancelled = true;
    };
  }, [spotId, isAuthenticated, checkInJustVerified]);

  function handleSubmitted(updated: SpotFieldFreshness) {
    setFreshness(updated);
    setIsModalOpen(false);
    setJustSent(true);
    fetchMyVerifications(spotId).then(setMine).catch(() => undefined);
  }

  return (
    <div className="border-b border-border-muted p-4" data-testid="field-freshness">
      <p className="mb-1 text-[13px] font-medium text-ink-muted">
        Saha bilgisi ne kadar güncel?
      </p>

      {isLoading ? (
        <p className="font-mono text-xs text-ink-muted">Yükleniyor…</p>
      ) : error || !freshness ? (
        <p className="font-mono text-xs text-accent-rust">{error ?? "Yüklenemedi."}</p>
      ) : (
        <>
          <div>
            {freshness.primary.map((item) => (
              <FreshnessRow key={item.field} item={item} />
            ))}
          </div>

          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            className="my-1 flex min-h-[40px] items-center gap-1 text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
          >
            {showAll ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Diğer bilgiler (gri / siyah su)
          </button>
          {showAll ? (
            <div className="border-t border-border-muted/60">
              {freshness.secondary.map((item) => (
                <FreshnessRow key={item.field} item={item} />
              ))}
            </div>
          ) : null}

          <p className="mt-2 font-mono text-[10px] leading-relaxed text-ink-muted/80">
            Kalıcı saha bilgisi ile süreli canlı bildirimler ayrı şeylerdir: canlı bildirimler kısa süre geçerlidir, önce
            gösterilir ve süre dolunca kalkar; doğrulamalar ise ziyaretçilerin yerinde gördüklerine dayanır ve kesin kanıt
            değildir.
          </p>

          {/* Ziyaret sonrası doğrulama - satır içi, popup yok */}
          <div className="mt-3">
            {justSent ? (
              <p className="font-mono text-xs text-accent-green" role="status">
                ✓ Doğrulamanız kaydedildi, teşekkürler. Cevabınızı sonraki ziyarette güncelleyebilirsiniz.
              </p>
            ) : null}
            {!isAuthenticated ? (
              <button
                type="button"
                onClick={openAuthModal}
                className="text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
              >
                Yerinde doğrulama için giriş yapın
              </button>
            ) : mine?.eligible ? (
              <div>
                {mine.has_pending_prompt && !justSent ? (
                  <p className="mb-1.5 font-mono text-[11px] text-ink-muted">
                    Bu ziyaret için henüz saha bilgisi doğrulamadınız.
                  </p>
                ) : null}
                <button
                  type="button"
                  data-testid="open-verify"
                  onClick={() => {
                    setJustSent(false);
                    setIsModalOpen(true);
                  }}
                  className="min-h-[44px] w-full rounded-full border border-accent-green px-3 py-2 text-sm font-semibold text-accent-green transition-colors hover:bg-accent-green/10"
                >
                  Saha bilgisini doğrula
                </button>
              </div>
            ) : mine ? (
              <p className="font-mono text-[11px] leading-relaxed text-ink-muted" data-testid="verify-not-eligible">
                {mine.eligibility_message} Genel düzeltme ve durum bildirimi seçenekleri her zaman açıktır.
              </p>
            ) : null}
          </div>
        </>
      )}

      {isModalOpen && mine ? (
        <VerifyFieldsModal
          spotId={spotId}
          mine={mine}
          onClose={() => setIsModalOpen(false)}
          onSubmitted={handleSubmitted}
        />
      ) : null}
    </div>
  );
}
