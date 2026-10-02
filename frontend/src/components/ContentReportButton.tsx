import { useState, type FormEvent } from "react";
import { reportContent, type ContentReason, type ContentReport } from "../lib/api";
import { useAuthStore } from "../store/useAuthStore";
import { extractErrorMessage } from "../lib/errors";
import { Field, INPUT_CLASS } from "./FormControls";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
export default function ContentReportButton({ spotId, targetId, targetKind = "spot", label = "Hata / içerik bildir" }: {
  spotId: string;
  targetId: string;
  targetKind?: ContentReport["target_kind"];
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ContentReason>(targetKind === "spot" ? "incorrect_information" : "inappropriate");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await reportContent(spotId, { target_kind: targetKind, target_id: targetId, reason, description });
      setMessage("Bildiriminiz incelemeye gönderildi.");
      setOpen(false);
      setDescription("");
    }
    catch (err) {
      setError(extractErrorMessage(err, "Bildirim gönderilemedi."));
    }
    finally {
      setBusy(false);
    }
  }
  return <>
    <button type="button" className="min-h-touch text-xs font-medium text-text-secondary hover:text-warning-rust" onClick={() => {
      if (!useAuthStore.getState().isAuthenticated) {
        useAuthStore.getState().openAuthModal();
        return;
      }
      setOpen(true);
      setError(null);
      setMessage(null);
    }}>{label}</button>
    {message && <p role="status" className="text-xs text-accent-green">{message}</p>}
    {open && <Modal title="İçerik bildir" onClose={() => setOpen(false)} maxWidth="sm">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label="Bildirim nedeni">
          <select value={reason} onChange={e => setReason(e.target.value as ContentReason)} className={INPUT_CLASS}>
            {targetKind === "spot" && <>
              <option value="wrong_location">Yanlış koordinat</option>
              <option value="duplicate">Mükerrer nokta</option>
              <option value="closed">Kalıcı olarak kapalı</option>
              <option value="incorrect_information">Hatalı bilgi</option>
            </>}
            <option value="inappropriate">Uygunsuz içerik</option>
            <option value="other">Diğer</option>
          </select>
        </Field>
        <Field label="Açıklama / önerilen düzeltme">
          <textarea required minLength={5} maxLength={2000} rows={4} value={description} onChange={e => setDescription(e.target.value)} className={INPUT_CLASS} />
        </Field>
        {error && <p role="alert" className="text-xs text-warning-rust">{error}</p>}<Button type="submit" disabled={busy}>{busy ? "Gönderiliyor…" : "İncelemeye Gönder"}</Button>
      </form>
    </Modal>}
  </>;
}
