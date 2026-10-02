/**
 * Tüm form modalları (Auth, Araç Profili, Yeni Nokta, Nokta Düzenle,
 * Değerlendirme, Saha Doğrulama, Durum Bildir) arasında paylaşılan yapı
 * taşları - ortak alan yüksekliği/renk/tipografi burada tek yerde yaşar.
 *
 * Tipografi kuralı: etiket/açıklama/buton METNİ okunaklı sans-serif'tir;
 * SADECE gerçekten teknik bir ölçü birimi (m/kg gibi) mono kalır (bkz.
 * `NumberField`'daki birim rozeti) - "teknik verilerde monospace" kuralı
 * tüm forma değil, yalnızca o tek rakam/birim ikilisine uygulanır.
 */
import { useEffect, useState, type ReactNode } from "react";

/** Tüm `<input>`/`<textarea>`/`<select>` elemanlarının ortak zemin/kenarlık/odak stili. */
export const INPUT_CLASS =
  "min-h-touch w-full rounded-md border border-border-light bg-surface-secondary px-3 py-2.5 text-sm text-text-primary outline-none transition-colors placeholder:text-text-secondary/60 focus:border-accent-green disabled:opacity-40";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-text-primary">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-text-secondary">{hint}</span> : null}
    </label>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** "danger" - seçili olmasa bile pas kiremiti vurgusuyla öne çıkar (örn. ceza). */
  tone?: "default" | "danger";
}

export function SegmentedGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const isActive = value === opt.value;
        const isDanger = opt.tone === "danger";
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            aria-pressed={isActive}
            className={[
              "min-h-touch rounded-md border px-3 text-sm font-medium transition-colors",
              isActive
                ? isDanger
                  ? "border-warning-rust bg-warning-rust text-white"
                  : "border-accent-green bg-accent-green/10 text-accent-green"
                : isDanger
                  ? "border-warning-rust/40 text-warning-rust hover:border-warning-rust hover:bg-warning-rust/10"
                  : "border-border-light text-text-secondary hover:border-neutral-grey hover:text-text-primary",
            ].join(" ")}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export interface NumberFieldProps {
  label: string;
  /** Input'un HEMEN dışında, sabit bir kutuda gösterilir - placeholder gibi
   * yazarken kaybolmaz (bkz. görev tanımı: "Birimler input dışında
   * kaybolmayacak biçimde gösterilsin"). */
  unit: string;
  value: number | null;
  onChange: (value: number | null) => void;
  min: number;
  max: number;
  /**
   * Dokümantasyon/anlam amaçlı: "makul artış adımı". Native `<input
   * type=number>` KASITLI OLARAK kullanılmıyor - çoğu tarayıcı Türkçe
   * ondalık virgülü ("6,4") geçersiz karakter sayıp DOM seviyesinde
   * reddediyor, JS'e hiç ulaşmıyor bile. Bunun yerine serbest metin +
   * `inputMode="decimal"` kullanılıp virgül güvenle noktaya çevriliyor
   * (bkz. `handleChange`). `step`, backend'in de zorlamadığı bir "tam kat
   * olma" kısıtı olarak UYGULANMIYOR - sadece çağıran tarafın niyetini
   * belgelemek için tutuluyor.
   */
  step: number;
  required?: boolean;
  /** Boş bırakılabilir mi? `false` ise boş bırakıldığında "zorunlu" hatası gösterilir. */
  optional?: boolean;
}

/**
 * Türkçe ondalık virgülünü güvenle normalize eden, birimi input dışında
 * sabit gösteren sayısal form alanı (bkz. `NumberFieldProps` içindeki
 * gerekçe). `value`/`onChange` her zaman temiz bir `number | null` taşır -
 * kullanıcı arayüzü metin tabanlı olsa da çağıran taraf hiçbir zaman ham
 * string görmez.
 */
export function NumberField({
  label,
  unit,
  value,
  onChange,
  min,
  max,
  step: _step,
  required = false,
  optional = true,
}: NumberFieldProps) {
  const [text, setText] = useState(value != null ? String(value).replace(".", ",") : "");
  const [touched, setTouched] = useState(false);

  // Dışarıdan `value` değişirse (ör. Düzenle formunun prefill'i, ya da form
  // resetlendiğinde) metni senkronla - kullanıcının o an yazdığı ANLIK
  // karakteri EZMEMEK için sadece `value` referansı değiştiğinde çalışır.
  useEffect(() => {
    setText(value != null ? String(value).replace(".", ",") : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function handleChange(raw: string) {
    // Sadece rakam ve tek bir ondalık ayraç (','/'.') kabul et.
    const cleaned = raw.replace(/[^0-9.,]/g, "");
    setText(cleaned);
    const normalized = cleaned.replace(",", ".");
    if (normalized.trim() === "") {
      onChange(null);
      return;
    }
    const parsed = Number(normalized);
    if (!Number.isNaN(parsed)) onChange(parsed);
  }

  const isEmpty = text.trim() === "";
  const hasRequiredError = touched && required && isEmpty;
  const hasRangeError = touched && !isEmpty && value != null && (value < min || value > max);
  const hasError = hasRequiredError || hasRangeError;

  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium text-text-primary">{label}</span>
      <div className="flex">
        <input
          type="text"
          inputMode="decimal"
          value={text}
          onChange={(event) => handleChange(event.target.value)}
          onBlur={() => setTouched(true)}
          placeholder={optional ? "bilinmiyorsa boş bırakın" : undefined}
          className={[
            "min-h-touch w-full rounded-l-md border bg-surface-secondary px-3 py-2.5 text-sm text-text-primary outline-none transition-colors focus:border-accent-green",
            hasError ? "border-warning-rust" : "border-border-light",
          ].join(" ")}
        />
        <span className="flex items-center rounded-r-md border border-l-0 border-border-light bg-surface-primary px-2.5 font-mono text-xs text-text-secondary">
          {unit}
        </span>
      </div>
      {hasRequiredError ? (
        <p className="mt-1 text-xs text-warning-rust">Bu alan zorunlu.</p>
      ) : hasRangeError ? (
        <p className="mt-1 text-xs text-warning-rust">
          {min}–{max} {unit} aralığında olmalı.
        </p>
      ) : null}
    </div>
  );
}

/**
 * 1-5 arası puanlama girişi - numaralı kutular (yıldız ikonuna değil,
 * rakama dayanır ki seçilen değer SADECE renkle değil AÇIKÇA yazıyla da
 * görünsün). "Değerlendirmedim" durumuna dönmek için ayrı bir "Temizle"
 * butonu var - boş değer asla 0/1 gibi bir puana denk düşmez, gerçekten
 * `null`dur. Dokunma hedefleri >=44px (mobilde rahat dokunulabilir).
 */
export function RatingInput({
  label,
  value,
  onChange,
  allowClear = true,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  /** `false` ise "Temizle" butonu hiç gösterilmez - zorunlu (boş bırakılamaz) puanlar için, ör. genel puan. */
  allowClear?: boolean;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-text-primary">{label}</span>
        <span className="text-xs text-text-secondary">{value != null ? `${value} / 5` : "Değerlendirmedim"}</span>
      </div>
      <div className="flex items-center gap-1.5">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            aria-label={`${label}: ${n} / 5`}
            aria-pressed={value === n}
            className={[
              "flex h-10 w-10 items-center justify-center rounded-md border text-sm font-semibold transition-colors",
              value != null && n <= value
                ? "border-accent-brass bg-accent-brass/15 text-accent-brass"
                : "border-border-light text-text-secondary hover:border-neutral-grey hover:text-text-primary",
            ].join(" ")}
          >
            {n}
          </button>
        ))}
        {allowClear && value != null ? (
          <button
            type="button"
            onClick={() => onChange(null)}
            className="ml-1 h-10 rounded-md border border-border-light px-2.5 text-xs font-medium text-text-secondary transition-colors hover:border-warning-rust hover:text-warning-rust"
          >
            Temizle
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** Mat, basmalı toggle switch (glow/gölge yok). */
export function ToggleField({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      disabled={disabled}
      aria-pressed={checked}
      className="flex min-h-touch items-center justify-between rounded-md border border-border-light bg-surface-secondary px-3 text-left transition-colors hover:border-neutral-grey disabled:opacity-40"
    >
      <span className="text-sm font-medium text-text-primary">{label}</span>
      <span
        className={[
          "relative h-5 w-9 shrink-0 rounded-full border transition-colors",
          checked ? "border-accent-green bg-accent-green" : "border-border-light bg-surface-primary",
        ].join(" ")}
      >
        <span
          className={[
            "absolute top-0.5 h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform",
            checked ? "translate-x-4" : "translate-x-0.5",
          ].join(" ")}
        />
      </span>
    </button>
  );
}
