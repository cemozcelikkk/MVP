import { useEffect, useState, type FormEvent } from "react";
import { resetPassword, verifyEmail } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { useAuthStore } from "../store/useAuthStore";
import { Field, INPUT_CLASS } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
export default function AccountLinkHandler() {
  const [link, setLink] = useState(() => { const params = new URLSearchParams(window.location.hash.slice(1)); const action = params.get("account_action"); return action === "reset" || action === "verify" ? { action, token: params.get("token") ?? "" } : null; });
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (link)
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }, [link]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!link)
      return;
    if (link.action === "reset" && password !== repeat) {
      setError("Şifreler eşleşmiyor.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = link.action === "reset" ? await resetPassword(link.token, password) : await verifyEmail(link.token);
      setMessage(result.message);
      if (link.action === "reset")
        useAuthStore.getState().logout();
      else
        await useAuthStore.getState().restoreSession();
    }
    catch (err) {
      setError(extractErrorMessage(err, "Bağlantı kullanılamadı."));
    }
    finally {
      setBusy(false);
    }
  }
  if (!link)
    return null;
  return <Modal title={link.action === "reset" ? "Yeni Şifre Belirle" : "E-postayı Doğrula"} onClose={() => setLink(null)} maxWidth="sm">
    {message ? <>
      <p role="status" className="text-sm text-accent-green">{message}</p>
      <Button className="mt-3" onClick={() => setLink(null)}>Tamam</Button>
    </> : <form onSubmit={submit} className="flex flex-col gap-3">
      {link.action === "reset" ? <>
        <Field label="Yeni şifre">
          <input required type="password" autoComplete="new-password" minLength={8} maxLength={72} value={password} onChange={e => setPassword(e.target.value)} className={INPUT_CLASS} />
        </Field>
        <Field label="Şifre tekrar">
          <input required type="password" autoComplete="new-password" minLength={8} maxLength={72} value={repeat} onChange={e => setRepeat(e.target.value)} className={INPUT_CLASS} />
        </Field>
      </> : <p className="text-sm">E-posta adresinizi doğrulamak için aşağıdaki düğmeye basın.</p>}
      {error && <p role="alert" className="text-xs text-warning-rust">{error}</p>}<Button type="submit" disabled={busy}>{busy ? "İşleniyor…" : link.action === "reset" ? "Şifreyi Güncelle" : "E-postayı Doğrula"}</Button>
    </form>}
  </Modal>;
}
