/**
 * Tasarım token sistemi - tek doğruluk kaynağı `src/index.css`teki `:root`
 * CSS değişkenleridir (bkz. o dosyanın üst docstring'i). Bu dosya sadece o
 * değişkenleri Tailwind utility sınıflarına (`bg-surface-primary`,
 * `text-text-secondary`, `border-border-light` vb.) bağlar - hiçbir renk
 * burada veya bileşen içinde ikinci kez ham hex olarak YAZILMAZ.
 *
 * CSS değişkenleri `index.css`de "R G B" (boşluk ayraçlı) üçlü olarak
 * tanımlanır ve burada `rgb(var(--x) / <alpha-value>)` deseniyle sarılır -
 * böylece `bg-accent-green/10` gibi opaklık varyantları normal şekilde çalışır.
 *
 * Eski (v1 "saha defteri") token adları KASITLI OLARAK korunuyor ve yeni
 * paletin en yakın karşılığına yönlendiriliyor - henüz taşınmamış nadir bir
 * className kalırsa sessizce eski koyu temaya değil, YENİ palete düşer.
 */
/** `--x` CSS değişkenini (index.css'de "R G B" üçlüsü) opaklık-destekli bir Tailwind rengine çevirir. */
function withAlpha(cssVar) {
  return `rgb(var(${cssVar}) / <alpha-value>)`;
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // --- Harita zemini (tek koyu yüzey - "saha defteri" karakteri BURADA yaşıyor) ---
        "map-bg": withAlpha("--map-bg"),

        // --- Açık ürün kabuğu: üst bar, sol panel, modaller, kartlar ---
        "surface-primary": withAlpha("--surface-primary"),
        "surface-secondary": withAlpha("--surface-secondary"),
        "surface-raised": withAlpha("--surface-raised"),
        "border-light": withAlpha("--border-light"),

        // --- Koyu yüzeyler: harita üstü yüzen araçlar (zoom, pin, küme, rozet) ---
        "surface-dark": withAlpha("--surface-dark"),
        "surface-dark-raised": withAlpha("--surface-dark-raised"),
        "border-dark": withAlpha("--border-dark"),

        // --- Metin ---
        "text-primary": withAlpha("--text-primary"),
        "text-secondary": withAlpha("--text-secondary"),
        "text-on-dark": withAlpha("--text-on-dark"),
        "text-on-dark-muted": withAlpha("--text-on-dark-muted"),

        // --- Vurgular (bkz. index.css: pirinç SADECE seçili/önemli eylem, pas SADECE gerçek uyarı) ---
        "accent-green": withAlpha("--accent-green"),
        "accent-green-hover": withAlpha("--accent-green-hover"),
        "accent-sage": withAlpha("--accent-sage"),
        "accent-earth": withAlpha("--accent-earth"),
        "accent-brass": withAlpha("--accent-brass"),
        "warning-rust": withAlpha("--warning-rust"),
        "neutral-grey": withAlpha("--neutral-grey"),

        // --- Geriye dönük takma adlar (bkz. dosya docstring'i) ---
        canvas: withAlpha("--map-bg"),
        "slate-dark": withAlpha("--surface-dark"),
        panel: withAlpha("--surface-primary"),
        "border-muted": withAlpha("--border-light"),
        ink: withAlpha("--text-primary"),
        "ink-muted": withAlpha("--text-secondary"),
        "accent-rust": withAlpha("--warning-rust"),
      },
      fontFamily: {
        // Gövde/arayüz: Hanken Grotesk - sıcak ama sakin bir grotesk; Türkçe
        // (latin-ext) glifleri tam. index.html'de Google Fonts'tan yüklenir.
        sans: ["Hanken Grotesk", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        // Editoryal başlıklar: Newsreader (optik boyutlu serif) - hero, nokta
        // adları, panel başlıkları. Büyük boyda ince ve dar, küçükte sağlam.
        display: ["Newsreader", "Georgia", "serif"],
        // `font-mono` sınıfı KASITLI OLARAK gövde ailesine bağlı: teknik
        // veriler tabular rakamlarla (bkz. index.css `.font-mono`) hizalanır,
        // ayrı bir monospace yüzü yok.
        mono: ["Hanken Grotesk", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        // Marka karakteri: yumuşak/oyuncak değil, kontrollü 2-8px - iOS/Android
        // (Expo) tarafına doğrudan taşınabilecek küçük, tutarlı bir ölçek.
        xs: "2px",
        sm: "4px",
        md: "6px",
        lg: "8px",
        // Görsel öncelikli keşif kartları ve hero vizörü - küçük kontrollerden
        // bilinçli olarak daha yumuşak (hiyerarşi: kart > buton > rozet).
        xl: "14px",
        "2xl": "22px",
      },
      spacing: {
        // Dokunma hedefi alt sınırı (bkz. görev tanımı: "en az ~44x44px").
        touch: "44px",
      },
      boxShadow: {
        // TEK yerde tanımlı, kontrollü gölge ölçeği - "büyük/yapay gölge yok"
        // kuralına uyan, sadece katman ayrımı için gerekli minimum değer.
        // Neon/glow/parlayan kenarlık YOK.
        panel: "0 1px 0 rgba(34, 38, 30, 0.06), 0 12px 32px -18px rgba(21, 33, 27, 0.35)",
        float: "0 6px 18px -6px rgba(10, 18, 14, 0.55)",
        modal: "0 24px 60px -20px rgba(10, 18, 14, 0.55)",
      },
    },
  },
  plugins: [],
}
