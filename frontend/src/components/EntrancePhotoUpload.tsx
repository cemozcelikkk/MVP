import { useState } from "react";
import { fetchSpotById, uploadSpotPhoto, type SpotFeature } from "../lib/api";
import { useAuthStore } from "../store/useAuthStore";
import { extractErrorMessage } from "../lib/errors";
export default function EntrancePhotoUpload({ spotId, onUpdated }: {
  spotId: string;
  onUpdated: (spot: SpotFeature) => void;
}) {
  const authenticated = useAuthStore(s => s.isAuthenticated);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!authenticated)
    return null;
  return <div className="mt-3">
    <label className="text-xs font-medium">Giriş / yaklaşım fotoğrafı ekle<input aria-label="Giriş fotoğrafı" disabled={busy} type="file" accept="image/jpeg,image/png,image/webp" className="mt-2 block w-full text-xs" onChange={async (e) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file)
        return;
      setBusy(true);
      setError(null);
      try {
        await uploadSpotPhoto(spotId, file, "entrance");
        onUpdated(await fetchSpotById(spotId));
      }
      catch (err) {
        setError(extractErrorMessage(err, "Fotoğraf yüklenemedi."));
      }
      finally {
        setBusy(false);
      }
    }} />
    </label>{busy && <p className="mt-1 text-xs">Yükleniyor…</p>}{error && <p role="alert" className="mt-1 text-xs text-warning-rust">{error}</p>}</div>;
}
