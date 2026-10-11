/**
 * Moderasyon: kategori geçişinde OTOMATİK taşınmayan eski restoran/sağlık kayıtları.
 * Bunlar kamp alanına özgü veri taşıdığı için (check-in, fotoğraf, geceleme bilgisi ...)
 * olduğu yerde bekletildi; karar moderatörün:
 *  - Kamp alanı olarak tut: kategori Kamp olur, tüm verisi yerinde kalır.
 *  - Hizmet noktasına taşı: restoran/sağlık noktası olur (kamp verisi silinmez, arşivde kalır).
 *  - Olduğu gibi bırak: eski kategorisinde, salt okunur kalır.
 */
import { useCallback, useEffect, useState } from "react";
import {
  fetchCategoryReviewQueue,
  resolveCategoryReview,
  type CategoryReviewAction,
  type CategoryReviewItem,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { CATEGORY_LABEL } from "../lib/pinStyle";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useMapDataStore } from "../store/useMapDataStore";
import Button from "./ui/Button";

export default function CategoryReviewTab() {
  const [rows, setRows] = useState<CategoryReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    fetchCategoryReviewQueue()
      .then((result) => {
        if (cancelled) return;
        setRows(result);
        setError(null);
      })
      .catch((err) => !cancelled && setError(extractErrorMessage(err, "Liste alınamadı.")));
    return () => {
      cancelled = true;
    };
  }, [version]);

  if (error) return <p className="text-xs text-warning-rust">{error}</p>;
  if (rows === null) return <p className="text-sm text-text-secondary">Yükleniyor…</p>;
  if (rows.length === 0) {
    return <p className="text-sm text-text-secondary">İnceleme bekleyen eski kayıt yok - kategori geçişi tamamlandı.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-text-secondary">
        Bu kayıtlar restoran/sağlık kategorisinde ama kamp alanına özgü veri taşıyor; veri kaybı olmasın diye
        otomatik taşınmadı.
      </p>
      {rows.map((row) => (
        <Row key={row.spot_id} row={row} onDone={reload} />
      ))}
    </div>
  );
}

function Row({ row, onDone }: { row: CategoryReviewItem; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const focusLocation = useCreateSpotStore((s) => s.focusLocation);

  async function act(action: CategoryReviewAction) {
    setBusy(true);
    setError(null);
    try {
      await resolveCategoryReview(row.spot_id, action);
      useMapDataStore.getState().retry();
      onDone();
    } catch (err) {
      setError(extractErrorMessage(err, "İşlem başarısız."));
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-border-light p-3" data-testid="category-review-row">
      <p className="text-sm font-semibold text-text-primary">{row.title}</p>
      <p className="text-xs text-text-secondary">
        Eski kategori: {CATEGORY_LABEL[row.category] ?? row.category}
        {row.review_count ? ` · ${row.review_count} değerlendirme` : ""}
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-1">
        {row.reason_labels.map((label) => (
          <li key={label} className="rounded bg-accent-brass/15 px-1.5 py-0.5 text-[11px] font-medium text-text-primary">
            {label}
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => focusLocation([row.longitude, row.latitude])}
        className="mt-1 min-h-[32px] font-mono text-xs text-accent-green hover:underline"
      >
        {row.latitude.toFixed(5)}, {row.longitude.toFixed(5)} - haritada göster
      </button>
      {error ? <p className="text-xs text-warning-rust">{error}</p> : null}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={busy} onClick={() => act("keep_as_camping")}>
          Kamp alanı olarak tut
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => act("move_to_service")}>
          Hizmet noktasına taşı
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("keep_as_is")}>
          Olduğu gibi bırak
        </Button>
      </div>
    </div>
  );
}
