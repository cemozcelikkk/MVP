/**
 * Moderasyon: hizmet noktası (restoran/sağlık/WC/duş) bildirimleri kuyruğu.
 * Haklı bir "kapanmış" / "mükerrer" bildiriminde nokta tek tıkla kaldırılır
 * (soft-delete); "konum hatalı" bildirimlerinde noktayı haritada açıp
 * değerlendirmek için koordinat bağlantısı verilir.
 */
import { useCallback, useEffect, useState } from "react";
import {
  fetchServicePointReportQueue,
  resolveServicePointReport,
  type ServicePointReportRow,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { REPORT_REASON_LABEL, SERVICE_CATEGORY_LABEL, servicePointTitle } from "../lib/servicePoints";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useMapDataStore } from "../store/useMapDataStore";
import Button from "./ui/Button";

export default function ServicePointModerationTab() {
  const [rows, setRows] = useState<ServicePointReportRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    fetchServicePointReportQueue("pending")
      .then((result) => {
        if (cancelled) return;
        setRows(result);
        setError(null);
      })
      .catch((err) => !cancelled && setError(extractErrorMessage(err, "Bildirimler alınamadı.")));
    return () => {
      cancelled = true;
    };
  }, [version]);

  if (error) return <p className="text-xs text-warning-rust">{error}</p>;
  if (rows === null) return <p className="text-sm text-text-secondary">Yükleniyor…</p>;
  if (rows.length === 0) return <p className="text-sm text-text-secondary">Bekleyen hizmet noktası bildirimi yok.</p>;

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => (
        <ReportRow key={row.id} row={row} onDone={reload} />
      ))}
    </div>
  );
}

function ReportRow({ row, onDone }: { row: ServicePointReportRow; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const focusLocation = useCreateSpotStore((s) => s.focusLocation);

  async function act(action: "resolve" | "reject", removePoint = false) {
    setBusy(true);
    setError(null);
    try {
      await resolveServicePointReport(row.id, { action, remove_point: removePoint });
      if (removePoint) useMapDataStore.getState().retry();
      onDone();
    } catch (err) {
      setError(extractErrorMessage(err, "İşlem başarısız."));
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-border-light p-3" data-testid="service-point-report-row">
      <p className="text-sm font-semibold">
        {REPORT_REASON_LABEL[row.reason]} · {servicePointTitle(row.point)}
      </p>
      <p className="text-xs text-text-secondary">
        {SERVICE_CATEGORY_LABEL[row.point.category]} · {new Date(row.created_at).toLocaleString("tr-TR")}
      </p>
      {row.description ? <p className="mt-1 whitespace-pre-wrap text-sm">{row.description}</p> : null}
      <button
        type="button"
        onClick={() => focusLocation([row.point.longitude, row.point.latitude])}
        className="mt-1 font-mono text-xs text-accent-green hover:underline"
      >
        {row.point.latitude.toFixed(5)}, {row.point.longitude.toFixed(5)} - haritada göster
      </button>
      {error ? <p className="mt-1 text-xs text-warning-rust">{error}</p> : null}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="danger-solid" disabled={busy} onClick={() => act("resolve", true)}>
          Haklı - noktayı kaldır
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => act("resolve")}>
          Haklı - düzeltildi
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("reject")}>
          Reddet
        </Button>
      </div>
    </div>
  );
}
