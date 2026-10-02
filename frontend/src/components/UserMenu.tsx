import { useTripStore } from "../store/useTripStore";
/**
 * Sağ üstteki kullanıcı adı + güven seviyesi düğmesi -> profil/çıkış açılır
 * menüsü. Moderatör/admin için "Moderasyon" girişini de burada tutar ki üst
 * bar sıradan kullanıcı için gereksiz yere kalabalıklaşmasın.
 */
import { ChevronDown, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import AccountSettingsModal from "./AccountSettingsModal";
import type { UserRole } from "../lib/api";
import { useAuthStore } from "../store/useAuthStore";

const ROLE_LABEL: Record<UserRole, string> = {
  user: "Kullanıcı",
  moderator: "Moderatör",
  admin: "Yönetici",
};

export default function UserMenu({ onOpenModeration }: { onOpenModeration: () => void }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [accountOpen,setAccountOpen] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const isStaff = user?.role === "moderator" || user?.role === "admin";

  useEffect(() => {
    if (!isOpen) return;
    function handlePointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  if (!user) return null;

  return (
    <><div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        data-testid="user-menu-trigger"
        className="flex h-10 items-center gap-2 rounded-md pl-1 pr-2 text-left transition-colors hover:bg-surface-secondary"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-green/15 text-xs font-bold text-accent-green">
          {user.display_name.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden leading-tight xl:block">
          <span className="block text-[13px] font-semibold text-text-primary">{user.display_name}</span>
          <span className="block text-[11px] text-text-secondary">Güven {user.trust_score}</span>
        </span>
        <ChevronDown size={14} className={`text-text-secondary transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      {isOpen ? (
        <div
          role="menu"
          data-testid="user-menu"
          className="absolute right-0 top-12 z-30 w-56 overflow-hidden rounded-md border border-border-light bg-surface-primary shadow-modal"
        >
          <div className="border-b border-border-light px-3 py-2.5">
            <p className="text-sm font-semibold text-text-primary">{user.display_name}</p>
            <p className="text-xs text-text-secondary">
              {ROLE_LABEL[user.role]} · Güven puanı {user.trust_score}
            </p>
          </div>
          <button type="button" role="menuitem" className="min-h-touch w-full px-3 text-left text-sm" onClick={()=>{setIsOpen(false);setAccountOpen(true);}}>Hesap Ayarları</button>
          <button type="button" role="menuitem" className="min-h-touch w-full px-3 text-left text-sm" onClick={()=>{setIsOpen(false);useTripStore.getState().open();}}>Seyahat Planlarım</button>
          {isStaff ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setIsOpen(false);
                onOpenModeration();
              }}
              className="flex min-h-touch w-full items-center gap-2.5 px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-secondary"
            >
              <ShieldCheck size={16} className="text-text-secondary" />
              Moderasyon
            </button>
          ) : null}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setIsOpen(false);
              logout();
            }}
            className="flex min-h-touch w-full items-center gap-2.5 px-3 text-sm font-medium text-warning-rust transition-colors hover:bg-warning-rust/10"
          >
            <LogOut size={16} />
            Çıkış Yap
          </button>
        </div>
      ) : null}
    </div>{accountOpen && <AccountSettingsModal onClose={()=>setAccountOpen(false)} />}</>
  );
}
