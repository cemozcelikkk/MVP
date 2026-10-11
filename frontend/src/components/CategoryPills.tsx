/**
 * Harita üstündeki yatay kaydırılabilir grup şeridi (park4night tarzı).
 *
 * Seçim `useFilterStore.selectedGroups`ta tutulur; MapView "Kamp" için
 * `GET /spots?category=CAMPING`, hizmet grupları için `GET /service-points?group=...`
 * çağırır ve görünür alanı hemen yeniden sorgular. Birden çok grup birlikte
 * seçilebilir; "Tümü" seçimi temizler. Etkin bir düğmenin zemini o grubun
 * harita pini rengini alır - şerit ile işaretçiler aynı renk dilini konuşur.
 */
import { CATEGORY_PIN_STYLE } from "../lib/pinStyle";
import { PLACE_FILTER_META } from "../lib/servicePoints";
import { type PlaceFilter, useFilterStore } from "../store/filters";

const PILLS: { group: PlaceFilter; emoji: string; label: string; color: { fill: string; border: string } }[] = [
  { group: "camping", emoji: "⛺", label: "Kamp", color: CATEGORY_PIN_STYLE.CAMPING },
  ...(["food", "health", "wc", "shower"] as const).map((group) => ({ group, ...PLACE_FILTER_META[group] })),
];

const BASE_CLASS =
  "pointer-events-auto flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-medium shadow-float transition-colors";
const IDLE_CLASS =
  "border-border-light bg-surface-primary text-text-primary/85 hover:border-text-primary/35 hover:text-text-primary";

export default function CategoryPills() {
  const selected = useFilterStore((s) => s.selectedGroups);
  const toggleGroup = useFilterStore((s) => s.toggleGroup);
  const clearCategories = useFilterStore((s) => s.clearCategories);
  const isAll = selected.length === 0;

  return (
    <div
      role="toolbar"
      aria-label="Nokta türüne göre filtrele"
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
      {PILLS.map(({ group, emoji, label, color }) => {
        const isActive = selected.includes(group);
        return (
          <button
            key={group}
            type="button"
            aria-pressed={isActive}
            onClick={() => toggleGroup(group)}
            className={[BASE_CLASS, isActive ? "text-white" : IDLE_CLASS].join(" ")}
            style={isActive ? { backgroundColor: color.fill, borderColor: color.border } : undefined}
          >
            <span aria-hidden>{emoji}</span>
            {label}
          </button>
        );
      })}
    </div>
  );
}
