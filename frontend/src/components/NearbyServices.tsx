/**
 * "Yakınımdakiler" - Keşif panelinde, haritadaki hizmet katmanıyla AYNI veriyi
 * (useMapDataStore.servicePoints) listeleyen bölüm. Ayrı sayfa yok: merkez
 * (harita alanı / konumum / seçili kamp noktası), yarıçap ve kategoriler burada
 * değişir; harita aynı anda güncellenir (bkz. MapView, useNearbyStore).
 *
 * Kategori çipleri harita şeridiyle aynı filtre durumunu paylaşır - birden çok
 * kategori seçilebilir. Harici (OpenStreetMap) noktalar "harita verisi" olarak
 * işaretlenir; açık/çalışıyor bilgisi gibi sunulmaz.
 */
import { Crosshair, Loader2, Map as MapIcon, MapPin, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ServicePointFeature } from "../lib/api";
import {
  AVAILABILITY_LABEL,
  FEE_LABEL,
  PLACE_FILTER_META,
  SERVICE_CATEGORY_LABEL,
  SERVICE_GROUP_LABEL,
  formatDistance,
  serviceIconSvg,
  servicePinColors,
  servicePointTitle,
} from "../lib/servicePoints";
import { countActiveFilters, SERVICE_FILTERS, useFilterStore, type FilterValues } from "../store/filters";
import { useMapDataStore } from "../store/useMapDataStore";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { NEARBY_RADIUS_OPTIONS, useNearbyStore } from "../store/useNearbyStore";

const COLLAPSED_ROWS = 6;

const STATUS_HINT: Partial<Record<string, string>> = {
  too_wide: "Restoran, WC ve duş harita verisi için haritayı yakınlaştırın.",
  unavailable:
    "Harita verisine (OpenStreetMap) şu an ulaşılamıyor; birkaç dakika içinde otomatik olarak tekrar deneniyor. KaravanTR kayıtları ve önbellek gösteriliyor.",
  partial: "Bölgenin harita verisi yükleniyor…",
};

interface Props {
  onSelect?: (feature: ServicePointFeature) => void;
}

export default function NearbyServices({ onSelect }: Props) {
  const points = useMapDataStore((s) => s.servicePoints);
  const externalStatus = useMapDataStore((s) => s.externalStatus);
  const attribution = useMapDataStore((s) => s.attribution);
  const selected = useFilterStore((s) => s.selectedGroups);
  const toggleGroup = useFilterStore((s) => s.toggleGroup);
  const filters = useFilterStore();
  const campFiltersActive = countActiveFilters(filters as unknown as FilterValues) > 0;
  const { mode, center, centerLabel, radiusM, isLocating, error, showViewport, locateMe, setRadius } = useNearbyStore();
  const [expanded, setExpanded] = useState(false);

  // Yalnızca "Kamp" seçiliyse hizmet katmanı kapalıdır.
  const servicesHidden = selected.length > 0 && !selected.some((g) => g !== "camping");
  const sorted = useMemo(
    () =>
      mode === "viewport"
        ? points
        : [...points].sort((a, b) => (a.properties.distance_m ?? 0) - (b.properties.distance_m ?? 0)),
    [points, mode],
  );
  const shown = expanded ? sorted : sorted.slice(0, COLLAPSED_ROWS);

  return (
    <section className="mb-8" data-testid="nearby-services">
      <h3 className="font-display text-xl font-medium text-text-primary">Yakınımdakiler</h3>

      {/* Merkez: harita alanı (varsayılan) / konumum / seçili kamp noktası */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <CenterButton active={mode === "viewport"} onClick={showViewport} icon={<MapIcon size={14} />} label="Harita alanı" />
        <CenterButton
          active={mode === "me"}
          onClick={locateMe}
          disabled={isLocating}
          testId="nearby-locate-me"
          icon={isLocating ? <Loader2 size={14} className="animate-spin" /> : <Crosshair size={14} />}
          label="Konumuma yakın"
        />
        {mode === "spot" ? (
          <span className="flex min-h-touch items-center gap-1 rounded-full border border-accent-green bg-accent-green/10 pl-3 pr-1 text-xs font-semibold text-accent-green">
            <MapPin size={13} />
            <span className="max-w-[150px] truncate">{centerLabel}</span>
            <button type="button" onClick={showViewport} aria-label="Kamp noktası merkezini kaldır" className="flex h-9 w-9 items-center justify-center rounded-full hover:bg-accent-green/15">
              <X size={14} />
            </button>
          </span>
        ) : null}
        {mode !== "viewport" ? (
          <select
            value={radiusM}
            onChange={(e) => setRadius(Number(e.target.value))}
            aria-label="Yarıçap"
            className="min-h-touch rounded-full border border-border-light bg-transparent px-2.5 text-xs font-medium text-text-primary"
          >
            {NEARBY_RADIUS_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r / 1000} km
              </option>
            ))}
          </select>
        ) : null}
      </div>
      {error ? <p className="mt-1.5 text-xs text-warning-rust">{error}</p> : null}

      {/* Kategoriler - harita şeridiyle ortak, çoklu seçim */}
      <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Hizmet kategorileri">
        {SERVICE_FILTERS.map((key) => {
          const meta = PLACE_FILTER_META[key];
          const isActive = selected.includes(key);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={isActive}
              data-testid={`nearby-filter-${key}`}
              onClick={() => toggleGroup(key)}
              className={[
                "flex min-h-touch items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors",
                isActive ? "text-white" : "border-border-light text-text-secondary hover:text-text-primary",
              ].join(" ")}
              style={isActive ? { backgroundColor: meta.color.fill, borderColor: meta.color.border } : undefined}
            >
              <span
                aria-hidden
                className="flex h-4 w-4 items-center justify-center [&_svg]:h-4 [&_svg]:w-4"
                dangerouslySetInnerHTML={{ __html: serviceIconSvg(meta.category, isActive ? "#FFFFFF" : meta.color.fill) }}
              />
              {meta.label}
            </button>
          );
        })}
      </div>

      {servicesHidden ? (
        <p className="mt-3 text-xs text-text-secondary">Hizmetleri görmek için bir kategori seçin.</p>
      ) : campFiltersActive ? (
        <p className="mt-3 text-xs text-text-secondary">Kamp filtreleri açıkken hizmet noktaları gizlenir.</p>
      ) : (
        <>
          {externalStatus && STATUS_HINT[externalStatus] ? (
            <p className="mt-3 text-xs text-text-secondary">{STATUS_HINT[externalStatus]}</p>
          ) : null}
          {sorted.length === 0 && (externalStatus === "partial" || externalStatus === "unavailable") ? (
            // Veri henüz gelmedi: "burada hiçbir şey yok" demek yanıltıcı olur.
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-dashed border-border-light p-4" data-testid="nearby-waiting">
              <Loader2 size={16} className="shrink-0 animate-spin text-text-secondary" />
              <p className="text-sm text-text-secondary">
                {externalStatus === "partial"
                  ? "Bu bölgenin harita verisi yükleniyor…"
                  : "Harita verisi bekleniyor - alınınca liste kendiliğinden güncellenecek."}
              </p>
            </div>
          ) : sorted.length === 0 ? (
            <div className="mt-3 rounded-xl border border-dashed border-border-light p-4" data-testid="nearby-empty">
              <p className="text-sm font-medium text-text-primary">
                {mode === "viewport" ? "Bu alanda kayıtlı hizmet yok" : "Bu yarıçapta kayıtlı hizmet yok"}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-text-secondary">
                {mode === "viewport"
                  ? "Haritayı kaydırın veya yakınlaştırın."
                  : "Yarıçapı büyütebilirsiniz."}{" "}
                Bildiğiniz bir restoran, sağlık kuruluşu, WC ya da duş varsa ekleyin - diğer gezginlere yardımcı olur.
              </p>
              <button
                type="button"
                onClick={() => useCreateSpotStore.getState().openChooser(mode !== "viewport" && center ? center : undefined)}
                className="mt-3 flex min-h-touch items-center gap-1.5 rounded-full bg-accent-green px-4 text-sm font-semibold text-text-on-dark transition-colors hover:bg-accent-green-hover"
              >
                <Plus size={15} />
                {mode !== "viewport" && center ? "Bu konuma nokta ekle" : "Nokta ekle"}
              </button>
            </div>
          ) : (
            <ul className="mt-2 divide-y divide-border-light/70" data-testid="service-point-list">
              {shown.map((point) => (
                <li key={point.properties.id}>
                  <ServiceRow point={point} onSelect={onSelect} />
                </li>
              ))}
            </ul>
          )}
          {sorted.length > COLLAPSED_ROWS ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 min-h-touch text-sm font-semibold text-accent-green hover:underline"
            >
              {expanded ? "Daha az göster" : `Tümünü göster (${sorted.length})`}
            </button>
          ) : null}
          {attribution ? (
            <p className="mt-2 text-[11px] text-text-secondary">
              Harita verisi:{" "}
              <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">
                {attribution}
              </a>
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

function CenterButton({
  active,
  onClick,
  icon,
  label,
  disabled,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={[
        "flex min-h-touch items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors disabled:opacity-60",
        active ? "border-accent-green bg-accent-green/10 text-accent-green" : "border-border-light text-text-secondary hover:text-text-primary",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

function ServiceRow({ point, onSelect }: { point: ServicePointFeature; onSelect?: (f: ServicePointFeature) => void }) {
  const p = point.properties;
  const detail =
    p.group === "food"
      ? p.average_rating != null
        ? `★ ${p.average_rating.toFixed(1)} (${p.review_count})`
        : null
      : p.group === "basic"
        ? [
            p.fee_status !== "unknown" ? FEE_LABEL[p.fee_status] : null,
            // Harici veride kullanılabilirlik hiçbir zaman bilinmez; doğrulanmış bilgi gibi gösterme.
            !p.is_external && p.availability_status !== "unknown" ? AVAILABILITY_LABEL[p.availability_status] : null,
          ]
            .filter(Boolean)
            .join(" · ") || null
        : null;
  return (
    <button
      type="button"
      onClick={() => onSelect?.(point)}
      className="flex w-full items-center gap-3 py-2.5 text-left transition-colors hover:bg-surface-secondary/60"
    >
      <span
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full [&_svg]:h-4 [&_svg]:w-4"
        style={{ backgroundColor: servicePinColors(p.category).fill }}
        dangerouslySetInnerHTML={{ __html: serviceIconSvg(p.category) }}
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text-primary">{servicePointTitle(p)}</span>
        <span className="block truncate text-xs text-text-secondary">
          {/* Adsız kayıtta başlık zaten tür adı - alt satırda grubu göster. */}
          {p.name ? SERVICE_CATEGORY_LABEL[p.category] : SERVICE_GROUP_LABEL[p.group]}
          {detail ? ` · ${detail}` : ""}
          {p.is_external ? " · harita verisi" : ""}
        </span>
      </span>
      {p.distance_m != null ? (
        <span className="shrink-0 text-xs font-semibold tabular-nums text-text-primary">{formatDistance(p.distance_m)}</span>
      ) : null}
    </button>
  );
}
