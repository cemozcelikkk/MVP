/**
 * Giriş/kayıt modalı.
 *
 * Görünürlüğü `useAuthStore.isAuthModalOpen` yönetir (bkz. store'daki not) -
 * bu bileşen App.tsx'te koşulsuz render edilir, kendi `isOpen` kontrolünü
 * kendi yapar.
 */
import { type FormEvent, useState } from "react";
import { forgotPassword } from "../lib/api";
import { useAuthStore } from "../store/useAuthStore";
import { INPUT_CLASS } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

type Tab = "login" | "register" | "forgot";

export default function AuthModal() {
  const isOpen = useAuthStore((s) => s.isAuthModalOpen);
  const isLoading = useAuthStore((s) => s.isLoading);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const closeAuthModal = useAuthStore((s) => s.closeAuthModal);

  const [tab, setTab] = useState<Tab>("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mailBusy,setMailBusy] = useState(false);
  const [message,setMessage] = useState<string|null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  if (!isOpen) return null;

  function switchTab(next: Tab) {
    setTab(next);
    setMessage(null);
    setFormError(null);
  }

  function handleClose() {
    closeAuthModal();
    // `if (!isOpen) return null` bileşeni UNMOUNT ETMEZ (App.tsx onu
    // koşulsuz render ediyor) - `useState`ler kapanışlar arasında hayatta
    // kalır. Bunu elle sıfırlamazsak, bir kez "Kayıt Ol" sekmesine
    // geçmiş bir kullanıcı sonraki HER açılışta (ör. çıkış yapıp tekrar
    // "Giriş Yap"a bastığında) yanlışlıkla kayıt formunu görür.
    setTab("login");
    setEmail("");
    setUsername("");
    setPassword("");
    setFormError(null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (tab === "forgot") {
      setMailBusy(true);
      try { setMessage((await forgotPassword(email)).message); } catch(err) { setFormError(err instanceof Error ? err.message : "İşlem başarısız."); } finally {setMailBusy(false);}
      return;
    }
    try {
      if (tab === "login") {
        await login(email, password);
      } else {
        await register(email, username, password);
      }
      handleClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "İşlem başarısız.");
    }
  }

  return (
    <Modal
      title={tab === "forgot" ? "Şifremi Unuttum" : tab === "login" ? "Giriş Yap" : "Kayıt Ol"}
      onClose={handleClose}
      maxWidth="sm"
      testId="auth-modal"
      headerExtra={
        <div className="flex rounded-md border border-border-light p-0.5">
          <TabButton active={tab === "login"} onClick={() => switchTab("login")}>
            Giriş
          </TabButton>
          <TabButton active={tab === "register"} onClick={() => switchTab("register")}>
            Kayıt
          </TabButton>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-text-primary">E-posta</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={INPUT_CLASS}
          />
        </label>

        {tab === "register" ? (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-text-primary">Kullanıcı Adı</span>
            <input
              type="text"
              required
              minLength={3}
              maxLength={100}
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className={INPUT_CLASS}
            />
          </label>
        ) : null}

        {tab !== "forgot" && <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-text-primary">Şifre</span>
          <input
            type="password"
            required
            minLength={8}
            autoComplete={tab === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={INPUT_CLASS}
          />
        </label>}

        {formError ? <p className="text-xs text-warning-rust">{formError}</p> : null}

        <Button type="submit" variant="primary" disabled={isLoading || mailBusy} className="mt-1 w-full">
          {isLoading || mailBusy ? "İşleniyor…" : tab === "forgot" ? "Bağlantı Gönder" : tab === "login" ? "Giriş Yap" : "Kayıt Ol"}
        </Button>
        {message && <p role="status" className="text-sm text-accent-green">{message}</p>}
        {tab === "login" && <button type="button" onClick={()=>switchTab("forgot")} className="min-h-touch text-xs text-text-secondary">Şifremi Unuttum</button>}
      </form>
    </Modal>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "min-h-[32px] rounded px-3 text-xs font-semibold transition-colors",
        active ? "bg-accent-green text-text-on-dark" : "text-text-secondary hover:text-text-primary",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
