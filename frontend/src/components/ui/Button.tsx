/**
 * Ortak buton sistemi - primary/secondary/danger/ghost, tek boyut skalası.
 * Tüm modal ve panel eylemleri (Kaydet, İptal, Sil, Gönder…) buradan gelir
 * ki "ortak primary/secondary/danger butonları" kuralı tek yerde yaşasın.
 */
import { forwardRef, type ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "danger-solid" | "ghost";
type Size = "md" | "sm";

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-accent-green text-text-on-dark hover:bg-accent-green-hover",
  secondary: "border border-text-primary/20 text-text-primary hover:border-text-primary/40 hover:bg-surface-secondary/60",
  danger: "border border-warning-rust text-warning-rust hover:bg-warning-rust/10",
  // Yıkıcı işlemin SON onayı (ör. "Evet, Sil") için dolgulu - ana buton (primary) yeşiliyle karışmasın.
  "danger-solid": "bg-warning-rust text-white hover:brightness-95",
  ghost: "text-text-secondary hover:bg-surface-secondary hover:text-text-primary",
};

const SIZE_CLASSES: Record<Size, string> = {
  md: "min-h-touch px-5 text-sm",
  sm: "min-h-[36px] px-3.5 text-xs",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = "secondary", size = "md", className = "", type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={[
        "inline-flex items-center justify-center gap-1.5 rounded-full font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      ].join(" ")}
      {...rest}
    />
  );
});

export default Button;
