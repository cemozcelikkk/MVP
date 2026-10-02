import { useEffect, useState } from "react";
import { fetchContentReports, resolveContentReport, fetchSpotById, fetchSpotChanges, type ContentReport, type SpotChange, type SpotFeature } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useMapDataStore } from "../store/useMapDataStore";
import EditSpotModal from "./EditSpotModal";
import Button from "./ui/Button";
import { INPUT_CLASS } from "./FormControls";
const REASONS = { wrong_location: "Yanlış konum", duplicate: "Mükerrer nokta", closed: "Kapalı", incorrect_information: "Hatalı bilgi", inappropriate: "Uygunsuz içerik", other: "Diğer" };
function Row({ row, onChanged }: {
  row: ContentReport;
  onChanged: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<SpotFeature | null>(null);
  const [history, setHistory] = useState<SpotChange[] | null>(null);
  const [action, setAction] = useState<"resolve" | "reject" | "hide" | null>(null);
  async function act() {
    if (!action)
      return;
    setBusy(true);
    setError(null);
    try {
      await resolveContentReport(row.id, action, note);
      useMapDataStore.getState().retry();
      onChanged();
    }
    catch (err) {
      setError(extractErrorMessage(err, "İşlem başarısız."));
    }
    finally {
      setBusy(false);
      setAction(null);
    }
  }
  async function edit() {
    setError(null);
    try {
      setEditing(await fetchSpotById(row.spot_id));
    }
    catch (err) {
      setError(extractErrorMessage(err, "Nokta açılamadı."));
    }
  }
  async function audit() {
    setError(null);
    try {
      setHistory(await fetchSpotChanges(row.spot_id));
    }
    catch (err) {
      setError(extractErrorMessage(err, "Geçmiş alınamadı."));
    }
  }
  return <div className="rounded-md border border-border-light p-3">
    <p className="text-sm font-semibold">{REASONS[row.reason]} · {{ spot: "Nokta", photo: "Fotoğraf", review: "Yorum" }[row.target_kind]}</p>
    <p className="mt-1 whitespace-pre-wrap text-sm">{row.description}</p>
    <p className="mt-1 text-xs text-text-secondary">{new Date(row.created_at).toLocaleString("tr-TR")}</p>
    <div className="mt-2 flex flex-wrap gap-2">
      <Button size="sm" onClick={() => void edit()}>Noktayı İncele / Düzelt</Button>
      <Button size="sm" onClick={() => void audit()}>Değişiklik Geçmişi</Button>
    </div>
    {row.state === "pending" ? <>
      <label className="mt-3 block text-xs">İşlem açıklaması<textarea rows={2} minLength={5} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} className={INPUT_CLASS} />
      </label>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || note.trim().length < 5} onClick={() => setAction("resolve")}>Düzeltildi</Button>
        <Button size="sm" disabled={busy || note.trim().length < 5} onClick={() => setAction("reject")}>Reddet</Button>
        <Button size="sm" disabled={busy || note.trim().length < 5} onClick={() => setAction("hide")}>İçeriği Gizle</Button>
      </div>
      {action && <div className="mt-2 rounded-md border border-warning-rust p-2 text-xs">
        <p>{action === "hide" ? "İçerik uygulamada görünmeyecek. İşlem açıklaması kaydedilecek." : "Bu bildirim sonuçlandırılacak."}</p>
        <div className="mt-2 flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => void act()}>Onayla</Button>
          <Button size="sm" onClick={() => setAction(null)}>Vazgeç</Button>
        </div>
      </div>}
    </> : <p className="mt-2 text-xs">Sonuç: {row.resolution_note}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-warning-rust">{error}</p>}
    {history && <div className="mt-3 border-t border-border-light pt-2">
      <p className="text-sm font-medium">Son 30 değişiklik</p>{!history.length && <p className="text-xs">Kayıt yok. Eski değişiklikler geriye dönük üretilemez.</p>}{history.map(change => <details key={change.id} className="mt-2 text-xs">
        <summary>{new Date(change.created_at).toLocaleString("tr-TR")} · {{ created: "Oluşturuldu", updated: "Düzenlendi", verified: "Onay durumu değişti", deleted: "Silindi", hidden: "Gizlendi" }[change.action] ?? change.action}</summary>
        <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap">{JSON.stringify({ önce: change.before, sonra: change.after }, null, 2)}</pre>
      </details>)}</div>}
    {editing && <EditSpotModal spot={editing} onClose={() => setEditing(null)} onUpdated={updated => { setEditing(null); useCreateSpotStore.getState().spotUpdated(updated); setNote("Nokta bilgisi düzeltildi."); }} />}
  </div>;
}
export default function ContentModerationTab() {
  const [state, setState] = useState("pending");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<ContentReport[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  function reload() {
    setBusy(true);
    setError(null);
    setRows([]);
    setRevision(value => value + 1);
  }
  useEffect(() => {
    let live = true;
    fetchContentReports(state, offset)
      .then(value => {
        if (live)
          setRows(value);
      })
      .catch(err => {
        if (live)
          setError(extractErrorMessage(err, "Bildirimler alınamadı."));
      })
      .finally(() => {
        if (live)
          setBusy(false);
      });
    return () => { live = false; };
  }, [state, offset, revision]);
  return <div>
    <select aria-label="İçerik bildirimi durumu" className={INPUT_CLASS} value={state} onChange={e => { reload(); setState(e.target.value); setOffset(0); }}>
      <option value="pending">Bekleyen</option>
      <option value="resolved">Çözülen</option>
      <option value="rejected">Reddedilen</option>
    </select>
    {error && <p role="alert" className="mt-2 text-xs text-warning-rust">{error}</p>}{busy && <p className="mt-2 text-xs">Yükleniyor…</p>}{!busy && !rows.length && <p className="mt-3 text-xs">Bildirim yok.</p>}
    <div className="mt-3 flex flex-col gap-3">{rows.map(row => <Row key={row.id} row={row} onChanged={reload} />)}</div>
    <div className="mt-3 flex gap-2">
      <Button size="sm" disabled={offset === 0 || busy} onClick={() => { reload(); setOffset(Math.max(0, offset - 20)); }}>Önceki</Button>
      <Button size="sm" disabled={rows.length < 20 || busy} onClick={() => { reload(); setOffset(offset + 20); }}>Sonraki</Button>
    </div>
  </div>;
}
