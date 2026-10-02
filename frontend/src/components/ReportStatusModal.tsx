/**
 * Süreli saha durumu bildirimi - 4 adımlı akış: (1) sorun türü, (2) kısa açıklama,
 * (3) süre (6/12/24/48 saat), (4) önizleme ve gönderim.
 *
 * `SpotDetailSidebar` "Durum Bildir" ile açar; oturum kontrolü çağıran tarafta. Süre
 * ve bitiş zamanı KESİN olarak backend'de UTC hesaplanır - burada gösterilen bitiş yalnızca
 * önizleme tahminidir. Açıklama isteğe bağlı, en fazla 280 karakter ve düz metindir
 * (HTML olarak render EDİLMEZ). Metinler bildirim dilindedir: resmî karar iddiası yok.
 */
import { ArrowLeft, ArrowRight } from "lucide-react";
import { useState } from "react";
import {
  createLiveReport,
  type LiveDurationHours,
  type LiveReportActionResponse,
  type LiveReportType,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import {
  DURATION_OPTIONS,
  formatDateTimeTr,
  LIVE_TYPE_GROUP_LABEL,
  LIVE_TYPE_OPTIONS,
  SERIOUS_TYPES,
  type LiveTypeOption,
} from "../lib/liveStatus";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

const NOTE_MAX = 280;
const STEP_TITLES = ["Sorun türü", "Kısa açıklama", "Geçerlilik süresi", "Önizle ve gönder"];

interface Props {
  spotId: string;
  /** Kullanıcının bu noktada zaten aktif bildirimi olan türler (tekrar gönderim engellenir). */
  myActiveTypes: LiveReportType[];
  onClose: () => void;
  onReported: (response: LiveReportActionResponse) => void;
}

const GROUP_ORDER: LiveTypeOption["group"][] = ["access", "night", "service", "capacity"];

export default function ReportStatusModal({ spotId, myActiveTypes, onClose, onReported }: Props) {
  const [step, setStep] = useState(0);
  const [reportType, setReportType] = useState<LiveReportType | null>(null);
  const [note, setNote] = useState("");
  const [hours, setHours] = useState<LiveDurationHours>(12);
  const [hoursTouched, setHoursTouched] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const selected = LIVE_TYPE_OPTIONS.find((o) => o.value === reportType) ?? null;
  const trimmedNote = note.trim();
  // Bitiş: yalnızca tahmin (kesin değer backend'de UTC hesaplanır).
  const estimatedEnd = new Date(Date.now() + hours * 3600 * 1000).toISOString();

  function chooseType(option: LiveTypeOption) {
    setReportType(option.value);
    // Kullanıcı süreyi elle değiştirmediyse türün önerilen süresi uygulanır.
    if (!hoursTouched) setHours(option.defaultHours);
    setStep(1);
  }

  async function handleSubmit() {
    if (!reportType) return;
    setFormError(null);
    setIsSubmitting(true);
    try {
      const response = await createLiveReport(spotId, {
        report_type: reportType,
        duration_hours: hours,
        note: trimmedNote || null,
      });
      onReported(response);
    } catch (err) {
      setFormError(extractErrorMessage(err, "Durum bildirilemedi."));
      setIsSubmitting(false);
    }
  }

  return (
    <Modal
      title="Durum Bildir"
      onClose={onClose}
      maxWidth="md"
      testId="report-status-modal"
      footer={
        step > 0 ? (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setStep(step - 1)} disabled={isSubmitting}>
              <ArrowLeft size={15} />
              Geri
            </Button>
            {step < 3 ? (
              <Button variant="primary" data-testid="next-step" className="flex-1" onClick={() => setStep(step + 1)}>
                {step === 1 && !trimmedNote ? "Açıklamasız devam et" : "Devam"}
                <ArrowRight size={15} />
              </Button>
            ) : (
              <Button
                variant="danger-solid"
                data-testid="submit-report"
                className="flex-1"
                onClick={handleSubmit}
                disabled={isSubmitting}
              >
                {isSubmitting ? "Gönderiliyor…" : "Bildirimi Gönder"}
              </Button>
            )}
          </div>
        ) : undefined
      }
    >
      <p className="mb-4 text-xs font-medium text-text-secondary" data-testid="report-step">
        Adım {step + 1}/4 · {STEP_TITLES[step]}
      </p>

      {/* --- 1) Tür --- */}
      {step === 0 ? (
        <div className="flex flex-col gap-4">
          {GROUP_ORDER.map((group) => (
            <div key={group}>
              <p className="mb-1.5 text-xs font-semibold text-text-secondary">
                {LIVE_TYPE_GROUP_LABEL[group]}
              </p>
              <div className="flex flex-col gap-1.5">
                {LIVE_TYPE_OPTIONS.filter((o) => o.group === group).map((option) => {
                  const alreadyMine = myActiveTypes.includes(option.value);
                  return (
                    <button
                      key={option.value}
                      type="button"
                      data-testid={`type-${option.value}`}
                      disabled={alreadyMine}
                      onClick={() => chooseType(option)}
                      className="flex min-h-touch items-center justify-between gap-2 rounded-md border border-border-light px-3 py-2 text-left transition-colors hover:border-neutral-grey disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span>
                        <span className="block text-sm font-medium text-text-primary">{option.label}</span>
                        <span className="block text-xs text-text-secondary">
                          {alreadyMine ? "Bu tür için zaten aktif bildiriminiz var" : option.hint}
                        </span>
                      </span>
                      <ArrowRight size={14} className="shrink-0 text-text-secondary" aria-hidden />
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* --- 2) Açıklama --- */}
      {step === 1 && selected ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-text-primary">
            Seçilen: <span className="font-semibold">{selected.label}</span>
          </p>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-text-primary">Kısa açıklama (isteğe bağlı)</span>
            <textarea
              value={note}
              maxLength={NOTE_MAX}
              rows={3}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Örn. köprüde çalışma var, giriş kapatılmış"
              className="min-h-touch w-full resize-none rounded-md border border-border-light bg-surface-secondary px-3 py-2.5 text-sm text-text-primary outline-none focus:border-accent-green"
            />
            <span className="mt-1 block text-right text-xs text-text-secondary">
              {note.length}/{NOTE_MAX}
            </span>
          </label>
          <p className="text-xs leading-relaxed text-text-secondary">
            Açıklama herkese görünür. Kişisel bilgi (telefon, plaka vb.) yazmayın.
          </p>
        </div>
      ) : null}

      {/* --- 3) Süre --- */}
      {step === 2 && selected ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-text-primary">Bu bildirim ne kadar süre geçerli olsun? Süre dolunca kendiliğinden kalkar.</p>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Geçerlilik süresi">
            {DURATION_OPTIONS.map((option) => {
              const isActive = hours === option;
              return (
                <button
                  key={option}
                  type="button"
                  data-testid={`duration-${option}`}
                  aria-pressed={isActive}
                  onClick={() => {
                    setHours(option);
                    setHoursTouched(true);
                  }}
                  className={[
                    "min-h-touch min-w-[76px] rounded-md border text-sm font-medium transition-colors",
                    isActive
                      ? "border-accent-green bg-accent-green/10 text-accent-green"
                      : "border-border-light text-text-secondary hover:border-neutral-grey hover:text-text-primary",
                  ].join(" ")}
                >
                  {option} saat
                </button>
              );
            })}
          </div>
          <p className="text-xs text-text-secondary">Bu tür için önerilen süre: {selected.defaultHours} saat.</p>
        </div>
      ) : null}

      {/* --- 4) Önizle + gönder --- */}
      {step === 3 && selected ? (
        <div className="flex flex-col gap-3" data-testid="report-preview">
          <div className="rounded-md border border-border-light bg-surface-secondary p-3">
            <p className="mb-1 text-xs font-semibold text-text-secondary">Topluluğa görünecek bildirim</p>
            <p className="text-sm font-semibold text-text-primary">{selected.label} bildirildi</p>
            <p className="mt-1 font-mono text-xs text-text-secondary">
              Süre: {hours} saat · tahmini bitiş {formatDateTimeTr(estimatedEnd)}
            </p>
            <p className="mt-1 text-xs text-text-secondary">{trimmedNote ? <>Açıklama: “{trimmedNote}”</> : "Açıklama eklenmedi."}</p>
          </div>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-xs leading-relaxed text-text-secondary">
            <li>Kimliğiniz ve konumunuz gösterilmez; yalnızca bildiren kişi sayısı görünür.</li>
            <li>
              Son 72 saatte bu noktada check-in yaptıysanız bildiriminiz “yerinde bulunan kullanıcı” olarak işaretlenir;
              yapmadıysanız daha düşük güven düzeyinde görünür.
            </li>
            <li>Aynı türü tekrar göndermek destek sayısını artırmaz. İstediğiniz an geri çekebilirsiniz.</li>
            {SERIOUS_TYPES.has(selected.value) ? (
              <li className="font-medium text-accent-brass">
                Bu tür başkalarının güzergâhını etkileyebilir; yalnızca gördüğünüzü veya öğrendiğinizi bildirin.
              </li>
            ) : null}
          </ul>
          {formError ? (
            <p className="text-xs text-warning-rust" role="alert">
              {formError}
            </p>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}
