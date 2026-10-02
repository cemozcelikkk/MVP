/**
 * Keşif modu: görünen bölgedeki noktalar, görsel öncelikli kartlar olarak.
 * `MapView`'ın zaten çektiği bbox sonucunu (`useMapDataStore`) paylaşır -
 * liste için AYRI bir API isteği YOK. Sıralama tamamen istemci tarafında,
 * sadece GÜVENİLİR biçimde zaten var olan alanlarla yapılır (puan, güncelleme
 * tarihi) - konum izni gerektiren "yakındaki" burada BİLEREK yok.
 *
 * Kart yalnızca yola çıkmadan önce sorulan üç soruyu yanıtlar: su var mı,
 * elektrik var mı, yol karavanı taşır mı. Ayrıntılar (GSM, ölçüler, canlı
 * durum geçmişi) nokta detayında kalır.
 */
import { Caravan, Droplets, Navigation, Route, ShieldAlert, Star, Zap } from "lucide-react";
import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { resolveMediaUrl, type CompatibilityStatus, type RoadType, type SpotFeature } from "../lib/api";
import { googleMapsDirectionsUrl } from "../lib/format";
import { CATEGORY_LABEL, CATEGORY_LANDSCAPE_STYLE, categoryIconSvg } from "../lib/pinStyle";
import { countActiveFilters, useFilterStore, type FilterValues } from "../store/filters";
import { useMapDataStore } from "../store/useMapDataStore";

type SortKey = "default" | "rating" | "freshness";

const SORT_LABEL: Record<SortKey, string> = {
  default: "Önerilen",
  rating: "En yüksek puan",
  freshness: "En yeni bilgi",
};

const ROAD_LABEL: Record<RoadType, string> = {
  asphalt: "Asfalt",
  gravel: "Çakıllı",
  dirt: "Toprak",
  rocky: "Taşlık",
};

const COMPAT_LABEL: Record<CompatibilityStatus, string> = {
  compatible: "Aracına uygun",
  caution: "Dikkatli giriş",
  not_compatible: "Aracına uygun değil",
  insufficient_data: "Uygunluk bilinmiyor",
};

function sortFeatures(features: SpotFeature[], sort: SortKey): SpotFeature[] {
  if (sort === "default") return features;
  const withIndex = features.map((f, index) => ({ f, index }));
  withIndex.sort((a, b) => {
    if (sort === "rating") {
      const ar = a.f.properties.average_rating ?? -1;
      const br = b.f.properties.average_rating ?? -1;
      if (ar !== br) return br - ar;
    } else {
      const at = new Date(a.f.properties.updated_at).getTime();
      const bt = new Date(b.f.properties.updated_at).getTime();
      if (at !== bt) return bt - at;
    }
    return a.index - b.index; // eşitlikte kararlı (orijinal bbox sırası)
  });
  return withIndex.map((w) => w.f);
}

interface Props {
  onSelect: (feature: SpotFeature) => void;
}

export default function ExploreList({ onSelect }: Props) {
  const features = useMapDataStore((s) => s.features);
  const isLoading = useMapDataStore((s) => s.isLoading);
  const errorMessage = useMapDataStore((s) => s.errorMessage);
  const retry = useMapDataStore((s) => s.retry);
  const filters = useFilterStore();
  const [sort, setSort] = useState<SortKey>("default");

  const activeCount = countActiveFilters(filters as unknown as FilterValues);
  const sorted = useMemo(() => sortFeatures(features, sort), [features, sort]);

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 px-5 pb-4 pt-6">
        <h2 className="font-display text-[26px] font-medium leading-tight text-text-primary" data-testid="explore-count">
          {isLoading && features.length === 0 ? "Noktalar yükleniyor" : `Bu bölgede ${features.length} nokta`}
        </h2>
        <div className="mt-2 flex items-center justify-between gap-3">
          <p className="text-[13px] text-text-secondary">
            {activeCount > 0 ? `${activeCount} filtre uygulanıyor` : "Haritayı kaydırdıkça liste güncellenir"}
          </p>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as SortKey)}
            aria-label="Sıralama"
            className="shrink-0 cursor-pointer rounded-full border border-text-primary/15 bg-transparent py-1 pl-3 pr-2 text-[13px] font-medium text-text-primary outline-none hover:border-text-primary/35 focus-visible:border-accent-green"
          >
            {(Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
              <option key={key} value={key}>
                {SORT_LABEL[key]}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8">
        {errorMessage ? (
          <div className="rounded-xl bg-warning-rust/10 p-4">
            <p className="mb-3 text-sm text-warning-rust">{errorMessage}</p>
            <button
              type="button"
              onClick={retry}
              className="min-h-touch rounded-full border border-text-primary/20 px-4 text-sm font-semibold text-text-primary hover:bg-surface-secondary"
            >
              Tekrar dene
            </button>
          </div>
        ) : sorted.length === 0 && !isLoading ? (
          <div className="rounded-xl border border-dashed border-border-light p-5">
            <p className="font-display text-lg text-text-primary">Bu bölgede nokta yok</p>
            <p className="mt-1 text-sm leading-relaxed text-text-secondary">
              Haritayı uzaklaştır ya da filtreleri gevşet. Bildiğin bir yer varsa haritadan “Nokta ekle” ile işaretle.
            </p>
          </div>
        ) : (
          <ul className="flex flex-col gap-7">
            {sorted.map((feature) => (
              <li key={feature.properties.id}>
                <SpotCard feature={feature} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function SpotCard({ feature, onSelect }: { feature: SpotFeature; onSelect: (f: SpotFeature) => void }) {
  const { properties, geometry } = feature;
  const hasSeriousWarning = (properties.live_status?.badge ?? false) || properties.live_status?.severity === "critical";
  const compatStatus = properties.compatibility?.status;
  const photo = properties.photos[0];
  const photoUrl = photo ? resolveMediaUrl(photo.thumbnail_url ?? photo.storage_url) : null;
  const [photoFailed, setPhotoFailed] = useState(false);
  const { amenities, passability } = properties;
  const [lon, lat] = geometry.coordinates;

  // Not `<button>`: kart, içine gerçek bir `<a>` (Google Haritalar butonu)
  // barındırıyor - HTML'de bir <button> başka bir etkileşimli eleman
  // İÇEREMEZ (geçersiz iç içe geçme, tarayıcı DOM'u sessizce bozar). Bunun
  // yerine `role="button"` + klavye desteği ile aynı erişilebilirliği
  // sağlıyoruz.
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(feature);
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={`explore-row-${properties.id}`}
      onClick={() => onSelect(feature)}
      onKeyDown={handleKeyDown}
      className="group block w-full cursor-pointer rounded-xl text-left outline-offset-4"
    >
      <div className="relative aspect-[16/9] overflow-hidden rounded-xl bg-surface-secondary">
        {photoUrl && !photoFailed ? (
          <img
            src={photoUrl}
            alt={photo?.caption ?? ""}
            loading="lazy"
            decoding="async"
            onError={() => setPhotoFailed(true)}
            className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.03]"
          />
        ) : (
          <CardLandscape id={properties.id} category={properties.category} />
        )}
        <span className="pointer-events-none absolute left-3 top-3 max-w-[calc(100%-1.5rem)] truncate rounded-full bg-map-bg/70 px-2.5 py-1 text-[12px] font-medium text-text-on-dark backdrop-blur-sm">
          {CATEGORY_LABEL[properties.category]}
        </span>
        {hasSeriousWarning ? (
          <span className="pointer-events-none absolute right-3 top-3 flex items-center gap-1 rounded-full bg-warning-rust px-2.5 py-1 text-[12px] font-semibold text-text-on-dark">
            <ShieldAlert size={13} aria-hidden />
            Aktif uyarı
          </span>
        ) : null}
        <a
          href={googleMapsDirectionsUrl(lat, lon)}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => event.stopPropagation()}
          title="Google Haritalar'da Aç"
          aria-label="Google Haritalar'da Aç"
          className="absolute bottom-3 right-3 flex h-9 w-9 items-center justify-center rounded-full bg-surface-raised/95 text-text-primary shadow-float outline-offset-2 transition-colors hover:bg-surface-primary"
        >
          <Navigation size={15} />
        </a>
      </div>

      <div className="px-0.5 pt-3">
        <div className="flex items-baseline justify-between gap-3">
          <h3
            className="min-w-0 truncate font-display text-[20px] font-medium leading-snug text-text-primary decoration-accent-green/40 underline-offset-4 group-hover:underline"
            title={properties.title}
          >
            {properties.title}
          </h3>
          {properties.average_rating != null ? (
            <span
              className="flex shrink-0 items-center gap-1 text-[13px] font-semibold tabular-nums text-text-primary"
              aria-label={`Puan ${properties.average_rating.toFixed(1)}, ${properties.review_count} değerlendirme`}
            >
              <Star size={12} fill="currentColor" className="text-accent-brass" aria-hidden />
              {properties.average_rating.toFixed(1)}
            </span>
          ) : null}
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {amenities ? (
            <>
              <FactBadge icon={<Droplets size={13} />} on={amenities.fresh_water_thread}>
                {amenities.fresh_water_thread ? "Su var" : "Su yok"}
              </FactBadge>
              <FactBadge icon={<Zap size={13} />} on={amenities.electricity_220v}>
                {amenities.electricity_220v ? "Elektrik" : "Elektrik yok"}
              </FactBadge>
            </>
          ) : (
            <FactBadge on={false}>Olanak bilgisi yok</FactBadge>
          )}
          {passability ? (
            <FactBadge
              icon={<Route size={13} />}
              tone={
                passability.clearance_required === "high_4x4" || passability.steep_incline || passability.road_type === "rocky"
                  ? "caution"
                  : "earth"
              }
            >
              {[
                ROAD_LABEL[passability.road_type],
                passability.clearance_required === "high_4x4" ? "4x4" : null,
                passability.steep_incline ? "dik" : null,
              ]
                .filter(Boolean)
                .join(", ")}
            </FactBadge>
          ) : null}
          {compatStatus ? (
            <FactBadge
              icon={<Caravan size={13} />}
              tone={compatStatus === "compatible" ? "on" : compatStatus === "insufficient_data" ? "off" : "caution"}
            >
              {COMPAT_LABEL[compatStatus]}
            </FactBadge>
          ) : null}
        </div>
      </div>
    </div>
  );
}

type BadgeTone = "on" | "off" | "earth" | "caution";

const BADGE_TONE: Record<BadgeTone, string> = {
  on: "bg-accent-sage/30 text-accent-green-hover",
  off: "text-text-secondary/80 ring-1 ring-inset ring-border-light",
  earth: "bg-accent-earth/10 text-accent-earth",
  caution: "bg-accent-brass/20 text-accent-earth",
};

/** Kart üzerindeki tek bir saha gerçeği. `on` verilirse tonu var/yok durumundan türetir. */
function FactBadge({
  icon,
  on,
  tone,
  children,
}: {
  icon?: ReactNode;
  on?: boolean;
  tone?: BadgeTone;
  children: ReactNode;
}) {
  const resolved: BadgeTone = tone ?? (on ? "on" : "off");
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 truncate whitespace-nowrap rounded-full px-2.5 py-1 text-[12.5px] font-medium ${BADGE_TONE[resolved]}`}
    >
      {icon ? <span className={`shrink-0 ${resolved === "off" ? "opacity-60" : ""}`}>{icon}</span> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

/** id'den deterministik tohum (FNV-1a) - aynı nokta her zaman aynı manzarayı alır. */
function seedOf(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function ridgePath(rand: () => number, base: number, amplitude: number, peaks: number): string {
  const step = 400 / peaks;
  let d = `M0 ${base + (rand() - 0.5) * amplitude}`;
  for (let i = 1; i <= peaks; i++) {
    const x = i * step - step / 2 + (rand() - 0.5) * step * 0.4;
    d += ` L${x.toFixed(0)} ${(base - amplitude * (0.35 + rand() * 0.65)).toFixed(0)}`;
    d += ` L${(i * step).toFixed(0)} ${(base - amplitude * rand() * 0.25).toFixed(0)}`;
  }
  return `${d} L400 250 L0 250 Z`;
}

function landscapeFor(id: string) {
  let state = seedOf(id) || 1;
  const rand = () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return ((state >>> 0) % 10000) / 10000;
  };
  return {
    far: ridgePath(rand, 165, 90, 3 + Math.floor(rand() * 3)),
    near: ridgePath(rand, 215, 55, 2 + Math.floor(rand() * 3)),
    sunX: Math.round(170 + rand() * 180), // sol üstteki kategori etiketinden uzak
    sunY: Math.round(40 + rand() * 40),
  };
}

/**
 * Fotoğrafı olmayan (ya da yüklenemeyen) noktalar için yer tutucu: açık,
 * doğal tonlarda bir manzara illüstrasyonu (id'den türetilen sırt
 * silüetleri) + kategori piktogramı. Boş/kırık görsel alanı yerine kartın
 * ritmini koruyan, kategoriyi de ayırt ettiren bir görsel.
 */
function CardLandscape({ id, category }: { id: string; category: SpotFeature["properties"]["category"] }) {
  const style = CATEGORY_LANDSCAPE_STYLE[category] ?? CATEGORY_LANDSCAPE_STYLE.day_parking;
  const { far, near, sunX, sunY } = useMemo(() => landscapeFor(id), [id]);
  return (
    <div
      className="relative h-full w-full"
      style={{ background: `linear-gradient(180deg, ${style.sky} 0%, ${style.ground} 100%)` }}
      aria-hidden
    >
      <svg viewBox="0 0 400 250" preserveAspectRatio="xMidYMax slice" className="absolute inset-0 h-full w-full">
        <circle cx={sunX} cy={sunY} r="26" fill={style.sun} opacity="0.9" />
        <circle cx={sunX} cy={sunY} r="42" fill={style.sun} opacity="0.25" />
        <path d={far} fill={style.ridgeFar} />
        <path d={near} fill={style.ridgeNear} />
      </svg>
      <span
        className="absolute bottom-3 left-3 flex h-10 w-10 items-center justify-center rounded-lg bg-map-bg/50 [&_svg]:h-5 [&_svg]:w-5"
        dangerouslySetInnerHTML={{ __html: categoryIconSvg(category) }}
      />
    </div>
  );
}
