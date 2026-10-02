import { useCallback, useEffect, useState, type FormEvent } from "react";
import { addTripStop, createTripList, deleteTripList, fetchTripList, fetchTripLists, fetchTripRoute, reorderTripStops, removeTripStop, updateTripStop, type TripItem, type TripList, type TripListSummary, type TripRoute, fetchSpotById } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { useTripStore } from "../store/useTripStore";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { Field, INPUT_CLASS } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
function StopRow({ item, index, count, busy, onSave, onMove, onRemove }: {
  item: TripItem;
  index: number;
  count: number;
  busy: boolean;
  onSave: (notes: string | null, date: string | null) => Promise<void>;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const [notes, setNotes] = useState(item.notes ?? "");
  const [date, setDate] = useState(item.planned_on ?? "");
  return <div className="rounded-md border border-border-light p-3">
    <p className="text-sm font-semibold">{index + 1}. {item.spot.title}</p>
    <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
      <Field label="Planlanan gün">
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className={INPUT_CLASS} />
      </Field>
      <Field label="Kişisel not">
        <input maxLength={1000} value={notes} onChange={e => setNotes(e.target.value)} className={INPUT_CLASS} />
      </Field>
    </div>
    <div className="mt-2 flex flex-wrap gap-2">
      <Button size="sm" disabled={busy} onClick={() => void onSave(notes.trim() || null, date || null)}>Tarih / Notu Kaydet</Button>
      <Button size="sm" disabled={busy || index === 0} onClick={() => onMove(-1)}>Yukarı</Button>
      <Button size="sm" disabled={busy || index === count - 1} onClick={() => onMove(1)}>Aşağı</Button>
      <Button size="sm" disabled={busy} onClick={onRemove}>Duraktan Çıkar</Button>
    </div>
  </div>;
}
export default function TripPlannerModal() { const open = useTripStore(s => s.isOpen); return open ? <TripForm /> : null; }
function TripForm() {
  const close = useTripStore(s => s.close);
  const pending = useTripStore(s => s.pendingSpot);
  const [lists, setLists] = useState<TripListSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<TripList | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [route, setRoute] = useState<TripRoute | null>(null);
  const [corridor, setCorridor] = useState(5);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const load = useCallback(async () => {
    try {
      setLists(await fetchTripLists());
    }
    catch (err) {
      setError(extractErrorMessage(err, "Listeler yüklenemedi."));
    }
  }, []);
  useEffect(() => {
    let live = true;
    fetchTripLists().then(value => {
      if (live)
        setLists(value);
    })
      .catch(err => {
        if (live)
          setError(extractErrorMessage(err, "Listeler yüklenemedi."));
      });
    return () => { live = false; };
  }, []);
  function selectPlan(id: string) {
    setRoute(null);
    setConfirmDelete(false);
    setDetail(null);
    setError(null);
    setSelected(id);
  }
  useEffect(() => {
    let live = true;
    if (selected)
      fetchTripList(selected).then(value => {
        if (live)
          setDetail(value);
      }).catch(err => {
        if (live)
          setError(extractErrorMessage(err, "Plan yüklenemedi."));
      });
    return () => { live = false; };
  }, [selected]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    }
    catch (err) {
      setError(extractErrorMessage(err, "İşlem tamamlanamadı."));
    }
    finally {
      setBusy(false);
    }
  }
  async function create(e: FormEvent) { e.preventDefault(); await run(async () => { const created = await createTripList(title); setTitle(""); await load(); selectPlan(created.id); }); }
  async function add(spotId: string) { await run(async () => { await addTripStop(selected, spotId); setDetail(await fetchTripList(selected)); setRoute(null); setMessage("Durak plana eklendi."); }); }
  async function move(index: number, delta: number) {
    if (!detail)
      return;
    const ids = detail.items.map(item => item.spot_id);
    [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]];
    await run(async () => { setDetail(await reorderTripStops(selected, ids)); setRoute(null); });
  }
  const points = detail?.items.map(item => `${item.spot.entry_latitude ?? item.spot.latitude},${item.spot.entry_longitude ?? item.spot.longitude}`) ?? [];
  const maps = points.length >= 2 ? "https://www.google.com/maps/dir/?" + new URLSearchParams({ api: "1", origin: points[0], destination: points[points.length - 1], waypoints: points.slice(1, -1).join("|"), travelmode: "driving" }).toString() : null;
  return <Modal title="Seyahat Planlarım" maxWidth="xl" onClose={close}>
    <div className="flex flex-col gap-4">
      <form onSubmit={create} className="flex gap-2">
        <input required minLength={1} maxLength={150} placeholder="Yeni plan adı" aria-label="Yeni plan adı" value={title} onChange={e => setTitle(e.target.value)} className={INPUT_CLASS} />
        <Button type="submit" disabled={busy}>Oluştur</Button>
      </form>
      <Field label="Seyahat planı">
        <select disabled={busy} value={selected} onChange={e => selectPlan(e.target.value)} className={INPUT_CLASS}>
          <option value="">Plan seçin</option>{lists.map(list => <option key={list.id} value={list.id}>{list.title}</option>)}</select>
      </Field>
      {pending && <Button disabled={!selected || busy || !!detail?.items.some(item => item.spot_id === pending.properties.id)} onClick={() => void add(pending.properties.id)}>“{pending.properties.title}” Noktasını Ekle</Button>}
      {error && <p role="alert" className="text-xs text-warning-rust">{error}</p>}{message && <p role="status" className="text-xs text-accent-green">{message}</p>}
      {detail && <>
        <p className="text-xs text-text-secondary">Durak sırası, tarihler ve notlar hesabınızda saklanır.</p>{!detail.items.length && <p className="text-sm">Haritadaki bir noktayı açıp “Seyahat Planına Ekle” düğmesini kullanın.</p>}
        {detail.items.map((item, index) => <StopRow key={item.id} item={item} index={index} count={detail.items.length} busy={busy} onMove={delta => void move(index, delta)} onRemove={() => void run(async () => { await removeTripStop(selected, item.spot_id); setDetail(await fetchTripList(selected)); setRoute(null); })} onSave={(notes, date) => run(async () => setDetail(await updateTripStop(selected, item.spot_id, notes, date)))} />)}
        <Field label="Rota çevresindeki arama mesafesi">
          <select value={corridor} onChange={e => { setCorridor(Number(e.target.value)); setRoute(null); }} className={INPUT_CLASS}>{[2, 5, 10, 20].map(km => <option key={km} value={km}>{km} km</option>)}</select>
        </Field>
        <Button disabled={busy || detail.items.length < 2 || detail.items.length > 10} onClick={() => void run(async () => setRoute(await fetchTripRoute(selected, corridor)))}>Rotayı ve Yakın Durakları Hesapla</Button>
        {maps && points.length <= 10 && <a className="text-sm font-medium text-accent-green" href={maps} target="_blank" rel="noreferrer">Durakları Google Haritalar'da Aç</a>}
        <p className="text-xs text-text-secondary">Rota hesaplama 2–10 durak için standart araç rotası kullanır. Karavanın yükseklik, ağırlık ve yol kısıtlarını değerlendirmez.</p>
        {route && <>
          <p className="text-sm">{route.distance_km} km · yaklaşık {route.duration_minutes} dakika sürüş</p>
          <Button onClick={() => useTripStore.getState().showRoute(route.geometry)}>Rotayı Haritada Göster</Button>
          <p className="text-sm font-medium">Rota yakınındaki noktalar</p>{!route.nearby_spots.length && <p className="text-xs">Seçili mesafede ek nokta bulunamadı.</p>}{route.nearby_spots.map(spot => <div key={spot.id} className="flex items-center justify-between gap-2 border-b border-border-light py-2">
            <span className="text-sm">{spot.title}</span>
            <Button size="sm" disabled={busy} onClick={() => void add(spot.id)}>Plana Ekle</Button>
            <Button size="sm" onClick={() => void run(async () => { const feature = await fetchSpotById(spot.id); useCreateSpotStore.getState().focusSpot(feature); close(); })}>Haritada</Button>
          </div>)}</>}
        <Button variant="secondary" onClick={() => setConfirmDelete(!confirmDelete)}>Planı Sil</Button>{confirmDelete && <div>
          <p className="mb-2 text-sm">Bu plan ve içindeki kişisel notlar silinecek.</p>
          <Button disabled={busy} onClick={() => void run(async () => { await deleteTripList(selected); selectPlan(""); await load(); })}>Silmeyi Onayla</Button>
        </div>}
      </>}
    </div>
  </Modal>;
}
