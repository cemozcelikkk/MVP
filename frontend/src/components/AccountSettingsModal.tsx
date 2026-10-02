import { useState, type FormEvent } from "react";
import { deleteMyAccount, requestEmailVerification } from "../lib/api";
import { useAuthStore } from "../store/useAuthStore";
import { extractErrorMessage } from "../lib/errors";
import { Field, INPUT_CLASS } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
export default function AccountSettingsModal({ onClose }: {
  onClose: () => void;
}) {
  const user = useAuthStore(s => s.user);
  const logout = useAuthStore(s => s.logout);
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function sendVerification() {
    setBusy(true);
    setError(null);
    try {
      setMessage((await requestEmailVerification()).message);
    }
    catch (err) {
      setError(extractErrorMessage(err, "E-posta gönderilemedi."));
    }
    finally {
      setBusy(false);
    }
  }
  async function remove(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await deleteMyAccount(password, confirmation);
      logout();
      onClose();
    }
    catch (err) {
      setError(extractErrorMessage(err, "Hesap silinemedi."));
    }
    finally {
      setBusy(false);
    }
  }
  return <Modal title="Hesap Ayarları" maxWidth="sm" onClose={onClose}>
    <p className="text-sm">{user?.email}</p>
    <p className="mt-2 text-xs text-text-secondary">{user?.email_verified ? "E-posta doğrulandı" : "E-posta henüz doğrulanmadı"}</p>
    {!user?.email_verified && <Button disabled={busy} onClick={() => void sendVerification()} className="mt-3">Doğrulama E-postası Gönder</Button>}
    {message && <p role="status" className="mt-3 text-sm text-accent-green">{message}</p>}{error && <p role="alert" className="mt-3 text-xs text-warning-rust">{error}</p>}
    <div className="mt-5 border-t border-border-light pt-4">
      <Button variant="secondary" onClick={() => setDeleting(!deleting)}>Hesabımı Sil</Button>
      {deleting && <form onSubmit={remove} className="mt-3 flex flex-col gap-3">
        <p className="text-sm text-warning-rust">Hesabınız, kişisel listeleriniz, yorumlarınız ve ziyaret kayıtlarınız silinir. Paylaşılan noktalar kimliğinizden ayrılarak korunur. Bu işlem geri alınamaz.</p>
        <Field label="Şifreniz">
          <input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} className={INPUT_CLASS} />
        </Field>
        <Field label="Onaylamak için HESABIMI SİL yazın">
          <input required value={confirmation} onChange={e => setConfirmation(e.target.value)} className={INPUT_CLASS} />
        </Field>
        <Button type="submit" disabled={busy || confirmation !== "HESABIMI SİL"}>Kalıcı Olarak Sil</Button>
      </form>}
    </div>
  </Modal>;
}
