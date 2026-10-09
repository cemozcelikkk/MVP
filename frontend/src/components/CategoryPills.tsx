/**
 * Harita üstündeki yatay kaydırılabilir kategori şeridi (park4night tarzı).
 *
 * Seçim `useFilterStore.selectedCategories`te tutulur; MapView bu diziyi
 * `GET /spots?category=...` parametresine çevirip görünür alanı hemen yeniden
 * sorgular. Birden çok grup birlikte seçilebilir; "Tümü" seçimi temizler.
 * Etkin bir düğmenin zemini, o kategorinin harita pini rengini alır - şerit
 * ile haritadaki işaretçiler aynı renk dilini konuşur.
 */
import type { SpotCategory } from "../lib/api";
import { CATEGORY_PIN_STYLE } from "../lib/pinStyle";
import { useFilterStore } from "../store/filters";

interface CategoryPill {
  key: string;
  emoji: string;
  label: string;
  categories: readonly SpotCategory[];
}

const PILLS: CategoryPill[] = [
  { key: "camping", emoji: "⛺", label: "Kamp", categories: ["CAMPING"] },
  { key: "fish", emoji: "🐟", label: "Balık", categories: ["FISH_RESTAURANT"] },
  { key: "meat", emoji: "🥩", label: "Et", categories: ["MEAT_RESTAURANT"] },
  { key: "pool", emoji: "🏊‍♂️", label: "Havuz/Otel", categories: ["HOTEL_POOL"] },
  { key: "health", emoji: "🏥", label: "Sağlık", categories: ["HOSPITAL", "HEALTH_CENTER"] },
];

const BASE_CLASS =
  "pointer-events-auto flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-medium shadow-float transition-colors";
const IDLE_CLASS =
  "border-border-light bg-surface-primary text-text-primary/85 hover:border-text-primary/35 hover:text-text-primary";

export default function CategoryPills() {
  const selected = useFilterStore((s) => s.selectedCategories);
  const toggleCategoryGroup = useFilterStore((s) => s.toggleCategoryGroup);
  const clearCategories = useFilterStore((s) => s.clearCategories);
  const isAll = selected.length === 0;

  return (
    <div
      role="toolbar"
      aria-label="Kategoriye göre filtrele"
      className="no-scrollbar flex gap-2 overflow-x-auto px-3 py-1 sm:px-4"
    >
      <button
        type="button"
        aria-pressed={isAll}
        onClick={clearCategories}
        className={[
          BASE_CLASS,
          isAll ? "border-accent-green bg-accent-green text-text-on-dark" : IDLE_CLASS,
        ].join(" ")}
      >
        Tümü
      </button>
      {PILLS.map(({ key, emoji, label, categories }) => {
        const isActive = categories.every((c) => selected.includes(c));
        const style = CATEGORY_PIN_STYLE[categories[0]];
        return (
          <button
            key={key}
            type="button"
            aria-pressed={isActive}
            onClick={() => toggleCategoryGroup(categories)}
            className={[BASE_CLASS, isActive ? "text-white" : IDLE_CLASS].join(" ")}
            style={isActive ? { backgroundColor: style.fill, borderColor: style.border } : undefined}
          >
            <span aria-hidden>{emoji}</span>
            {label}
          </button>
        );
      })}
    </div>
  );
}
