/**
 * Kamp noktası detayında "Yakındaki Hizmetler": seçili kamp alanının çevresinde
 * her kategoriden (yeme & içme, sağlık, WC, duş) en yakın birkaç nokta ve mesafesi.
 * "Haritada göster" aynı merkezi "Yakınımdakiler"e taşır - harita yarıçap dairesiyle
 * o çevreye odaklanır, kullanıcı başka bir sayfaya gitmez.
 */
import { Loader2, Radar } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchNearbyServicePoints, type ExternalStatus, type ServicePointFeature } from "../lib/api";
import {
  PLACE_FILTER_META,
  formatDistance,
  placeFilterOf,
  serviceIconSvg,
  servicePinColors,
  servicePointTitle,
} from "../lib/servicePoints";
import { SERVICE_FILTERS } from "../store/filters";
import { useNearbyStore } from "../store/useNearbyStore";
import Button from "./ui/Button";
import { Section } from "./ui/Section";

const RADIUS_M = 10_000;
// Harici kaynak çevreyi arka planda çekerken ("partial") artan aralıklarla yeniden sorulur.
const RETRY_DELAYS_MS = [1500, 3000, 5000, 8000];
const PER_CATEGORY = 2;

interface Props {
  center: [number, number];
  title: string;
  onSelect?: (feature: ServicePointFeature) => void;
}

export default function SpotNearbyServices({ center, title, onSelect }: Props) {
  const [points, setPoints] = useState<ServicePointFeature[] | null>(null);
  const [status, setStatus] = useState<ExternalStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const aroundSpot = useNearbyStore((s) => s.aroundSpot);
  const [lng, lat] = center;

  useEffect(() => {
    const controller = new AbortController();
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () =>
      fetchNearbyServicePoints({ latitude: lat, longitude: lng, radius_m: RADIUS_M }, controller.signal)
        .then((result) => {
          setPoints(result.features);
          setStatus(result.external_status);
          setFailed(false);
          // Bölge harici kaynaktan kısmen çekildiyse birkaç kez daha sor.
          if (result.external_status === "partial" && attempts < RETRY_DELAYS_MS.length) {
            timer = setTimeout(load, RETRY_DELAYS_MS[attempts++]);
          }
        })
        .catch((err) => {
          if (err?.name !== "CanceledError") setFailed(true);
        });
    load();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [lat, lng]);

  const byFilter = SERVICE_FILTERS.map((key) => ({
    key,
    rows: (points ?? []).filter((p) => placeFilterOf(p.properties.category) === key).slice(0, PER_CATEGORY),
  }));
  const total = byFilter.reduce((n, g) => n + g.rows.length, 0);

  return (
    <Section title="Yakındaki Hizmetler">
      {points === null && !failed ? (
        <p className="flex items-center gap-1.5 text-xs text-text-secondary">
          <Loader2 size={13} className="animate-spin" /> Çevre taranıyor…
        </p>
      ) : failed ? (
        <p className="text-xs text-warning-rust">Yakındaki hizmetler yüklenemedi.</p>
      ) : total === 0 ? (
        <p className="text-xs text-text-secondary">10 km içinde kayıtlı hizmet noktası bulunamadı.</p>
      ) : (
        <div className="flex flex-col gap-3" data-testid="spot-nearby-services">
          {byFilter
            .filter((g) => g.rows.length > 0)
            .map((g) => (
              <div key={g.key}>
                <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
                  {PLACE_FILTER_META[g.key].label}
                </span>
                <ul>
                  {g.rows.map((point) => (
                    <li key={point.properties.id}>
                      <button
                        type="button"
                        onClick={() => onSelect?.(point)}
                        className="flex min-h-touch w-full items-center gap-2.5 py-1.5 text-left transition-colors hover:bg-surface-secondary/60"
                      >
                        <span
                          aria-hidden
                          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full [&_svg]:h-3.5 [&_svg]:w-3.5"
                          style={{ backgroundColor: servicePinColors(point.properties.category).fill }}
                          dangerouslySetInnerHTML={{ __html: serviceIconSvg(point.properties.category) }}
                        />
                        <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
                          {servicePointTitle(point.properties)}
                        </span>
                        <span className="shrink-0 text-xs font-semibold tabular-nums text-text-secondary">
                          {formatDistance(point.properties.distance_m ?? 0)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
      )}
      {status === "unavailable" ? (
        <p className="mt-2 text-[11px] text-text-secondary">Harita verisine ulaşılamadı; yalnızca KaravanTR kayıtları.</p>
      ) : null}
      <Button variant="secondary" size="sm" className="mt-3 w-full" onClick={() => aroundSpot(center, title)} data-testid="spot-nearby-on-map">
        <Radar size={14} />
        Bu noktanın çevresini haritada göster
      </Button>
    </Section>
  );
}
