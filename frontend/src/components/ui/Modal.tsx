/**
 * Tüm modallar için ortak görsel/etkileşim kabuğu (Auth, Araç Profili, Yeni
 * Nokta, Nokta Düzenle, Değerlendirme, Saha Doğrulama, Durum Bildir,
 * Moderasyon). Tek yerde: başlık düzeni, kapatma butonu, scroll edilen içerik
 * bölgesi, opsiyonel yapışkan alt eylem çubuğu, focus trap, Escape ile
 * kapanma, açılışta ilk alana odaklanma.
 *
 * Masaüstünde ortalanmış kart; `sm` altında (mobil) tam ekran alt sayfaya
 * dönüşür - görev tanımındaki "mobilde tam ekran/bottom sheet" kuralı.
 */
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

const MAX_WIDTH: Record<NonNullable<ModalProps["maxWidth"]>, string> = {
  sm: "sm:max-w-sm",
  md: "sm:max-w-md",
  lg: "sm:max-w-lg",
  xl: "sm:max-w-2xl",
};

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface ModalProps {
  title: string;
  icon?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Yapışkan alt eylem çubuğu - uzun formlarda (bkz. görev tanımı). */
  footer?: ReactNode;
  /** Başlığın yanında ek kontrol (ör. AuthModal'daki giriş/kayıt sekmesi). */
  headerExtra?: ReactNode;
  maxWidth?: "sm" | "md" | "lg" | "xl";
  /** Test kancası - E2E senaryoları modalı ayırt edebilsin. */
  testId?: string;
}

export default function Modal({
  title,
  icon,
  onClose,
  children,
  footer,
  headerExtra,
  maxWidth = "md",
  testId,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();

  // Escape ile kapanma + Tab focus trap - dialog dışına odak kaçmasın.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    // Açılışta: ilk form alanına odaklan (yoksa kapatma butonuna).
    const first = focusables()[0];
    first?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    }

    dialog.addEventListener("keydown", handleKeyDown);
    return () => dialog.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="animate-overlay-fade-in fixed inset-0 z-40 flex items-end justify-center bg-map-bg/60 backdrop-blur-[2px] sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
        onClick={(event) => event.stopPropagation()}
        className={[
          "animate-sheet-rise-in flex max-h-[92vh] w-full flex-col overflow-hidden bg-surface-primary text-text-primary shadow-modal",
          "rounded-t-2xl sm:rounded-2xl",
          MAX_WIDTH[maxWidth],
        ].join(" ")}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border-light px-5 py-4">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {icon ? <span className="shrink-0 text-accent-green">{icon}</span> : null}
            <h2 id={titleId} className="truncate font-display text-[22px] font-medium text-text-primary">
              {title}
            </h2>
          </div>
          {headerExtra}
          <button
            type="button"
            onClick={onClose}
            aria-label="Kapat"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer ? (
          <div className="shrink-0 border-t border-border-light bg-surface-primary px-5 py-3">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}
