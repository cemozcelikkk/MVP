import { useRef, useState, type FormEvent } from "react";
import { searchPlaces, searchSpots, type PlaceResult, type SpotFeature } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { INPUT_CLASS } from "./FormControls";
import Button from "./ui/Button";
export default function SpotSearch({ onSelect }: {
  onSelect: (spot: SpotFeature) => void;
}) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"spot" | "place">("spot");
  const [spots, setSpots] = useState<SpotFeature[]>([]);
  const [places, setPlaces] = useState<PlaceResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [radius, setRadius] = useState(25);
  const requestNumber = useRef(0);
  async function run(event?: FormEvent, nearby = false) {
    event?.preventDefault();
    const current = ++requestNumber.current;
    setBusy(true);
    setError(null);
    setSearched(true);
    setSpots([]);
    setPlaces([]);
    try {
      if (nearby) {
        const position = await new Promise<GeolocationPosition>((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 10000 }));
        const result = await searchSpots("", { latitude: position.coords.latitude, longitude: position.coords.longitude }, radius);
        if (current === requestNumber.current)
          setSpots(result.features);
      }
      else if (mode === "place") {
        const result = await searchPlaces(query);
        if (current === requestNumber.current)
          setPlaces(result);
      }
      else {
        const result = await searchSpots(query);
        if (current === requestNumber.current)
          setSpots(result.features);
      }
    }
    catch (err) {
      if (current === requestNumber.current)
        setError(extractErrorMessage(err, "Arama tamamlanamadı. Konum iznini ve bağlantınızı kontrol edin."));
    }
    finally {
      if (current === requestNumber.current)
        setBusy(false);
    }
  }
  return <div className="border-b border-border-light p-4">
    <form onSubmit={run} className="flex flex-col gap-2">
      <label className="text-sm font-medium" htmlFor="spot-search">Şehir, ilçe veya nokta ara</label>
      <select aria-label="Arama türü" className={INPUT_CLASS} value={mode} onChange={(e) => { setMode(e.target.value as "spot" | "place"); setSearched(false); setSpots([]); setPlaces([]); }}>
        <option value="spot">Nokta adı / açıklaması</option>
        <option value="place">Şehir / ilçe</option>
      </select>
      <div className="flex gap-2">
        <input id="spot-search" minLength={2} maxLength={100} required value={query} onChange={(e) => setQuery(e.target.value)} className={INPUT_CLASS} placeholder="Örn: Fethiye" />
        <Button type="submit" disabled={busy}>Ara</Button>
      </div>
      <div className="flex items-center gap-2">
        <select className={INPUT_CLASS} aria-label="Yakındaki arama mesafesi" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>{[5, 10, 25, 50, 100].map(km => <option key={km} value={km}>{km} km</option>)}</select>
        <Button type="button" disabled={busy} onClick={() => void run(undefined, true)}>Yakınımda</Button>
      </div>
    </form>
    {busy && <p className="mt-2 text-xs">Aranıyor…</p>}{error && <p role="alert" className="mt-2 text-xs text-warning-rust">{error}</p>}
    {spots.map(spot => <button type="button" key={spot.properties.id} onClick={() => { useCreateSpotStore.getState().focusSpot(spot); onSelect(spot); }} className="block min-h-touch w-full border-b border-border-light text-left text-sm">{spot.properties.title}</button>)}
    {places.map(place => <button type="button" key={`${place.latitude},${place.longitude}`} onClick={() => useCreateSpotStore.getState().focusLocation([place.longitude, place.latitude])} className="block min-h-touch w-full border-b border-border-light py-2 text-left text-sm">{place.label}</button>)}
    {!!places.length && <a className="mt-2 block text-xs text-text-secondary" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>}
    {searched && !busy && !error && !spots.length && !places.length && <p className="mt-2 text-xs">Sonuç bulunamadı.</p>}
  </div>;
}
