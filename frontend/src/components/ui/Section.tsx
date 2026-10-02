/**
 * Nokta detay panelindeki bölüm başlıkları için ortak birincil/ikincil
 * görsel ağırlık sistemi (bkz. görev tanımı: "tüm bölümleri aynı görsel
 * ağırlıkta gösterme"). `Section` her zaman açık, kritik bilgi için;
 * `CollapsibleSection` daha az kritik ayrıntıları `<details>` ile katlar -
 * native `<details>` klavye/erişilebilirlik davranışını ücretsiz sağlar.
 */
import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

export function Section({
  title,
  action,
  children,
  testId,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="border-b border-border-light/70 px-5 py-5" data-testid={testId}>
      {title ? (
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="font-display text-[17px] font-medium text-text-primary">{title}</h3>
          {action}
        </div>
      ) : null}
      {children}
    </div>
  );
}

export function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = false,
  children,
  testId,
}: {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <details className="group border-b border-border-light/70" data-testid={testId} open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-4 text-text-primary marker:content-none">
        <span className="flex items-baseline gap-2">
          <span className="font-display text-[17px] font-medium">{title}</span>
          {subtitle ? <span className="text-xs text-text-secondary">{subtitle}</span> : null}
        </span>
        <ChevronDown size={16} className="shrink-0 text-text-secondary transition-transform group-open:rotate-180" />
      </summary>
      <div className="px-5 pb-5">{children}</div>
    </details>
  );
}
