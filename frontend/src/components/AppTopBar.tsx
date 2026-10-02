/**
 * Tek, düzenli üst uygulama çubuğu - eski dağınık sol-üst/orta-üst/sağ-üst
 * yüzen araç gruplarının (FilterBar/CreateSpotButton'ın filtre kısmı/
 * AuthWidget) yerini alır. Üç bölüm: marka (sol), hızlı filtreler (orta),
 * kullanıcı alanı (sağ). Masaüstünde ~68px, dar ekranda tek satıra iner
 * (ikincil eylemler kullanıcı menüsüne taşınır).
 *
 * Açık yüzey (surface-primary) - harita/pin/küme dışındaki TÜM ürün kabuğu
 * bu yüzeyde yaşar; koyu mat yüzey SADECE harita üstü yüzen araçlarda kalır.
 */
import {
  Caravan,
  Droplets,
  Gauge,
  LogIn,
  Menu,
  PanelLeft,
  PanelLeftClose,
  ShieldCheck,
  ShieldCheck as VerifiedIcon,
  SlidersHorizontal,
  Star,
  Zap,
} from "lucide-react";
import { useState, type ComponentType, type ReactNode } from "react";
import type { FilterToggleKey, FilterValues } from "../store/filters";
import { countActiveFilters, useFilterStore } from "../store/filters";
import { useAuthStore } from "../store/useAuthStore";
import { useFavoritesStore } from "../store/useFavoritesStore";
import { useModerationStore } from "../store/useModerationStore";
import { usePanelStore } from "../store/usePanelStore";
import { useVehicleProfileStore } from "../store/useVehicleProfileStore";
import FiltersModal from "./FiltersModal";
import UserMenu from "./UserMenu";

interface QuickFilterDef {
  key: FilterToggleKey;
  label: string;
  Icon: ComponentType<{ size?: number; className?: string }>;
}

// En fazla 4 görünür hızlı filtre (bkz. görev tanımı); geri kalanı "Tüm
// Filtreler" modalına taşınır (bkz. FiltersModal). "Aracıma Uygun" yalnızca
// aktif bir araç profili varsa görünür - anlamsız bir filtreyi listede
// tutmak yerine sessizce düşürülür (eski FilterBar ile aynı kural).
function quickFilters(hasActiveVehicle: boolean): QuickFilterDef[] {
  const base: QuickFilterDef[] = [
    { key: "hasFreshWater", label: "Su", Icon: Droplets },
    { key: "hasElectricity", label: "Elektrik", Icon: Zap },
    { key: "onlyVerified", label: "Onaylı Noktalar", Icon: VerifiedIcon },
  ];
  return hasActiveVehicle ? [{ key: "vehicleCompatibleOnly", label: "Aracıma Uygun", Icon: Gauge }, ...base] : base;
}

export default function AppTopBar() {
  const isPanelOpen = usePanelStore((s) => s.isOpen);
  const togglePanel = usePanelStore((s) => s.toggle);
  const filters = useFilterStore();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const openFavoritesDrawer = useFavoritesStore((s) => s.openDrawer);
  const openVehicleModal = useVehicleProfileStore((s) => s.openModal);
  const openModeration = useModerationStore((s) => s.open);
  const hasActiveVehicle = useVehicleProfileStore((s) => s.profiles.some((p) => p.is_active));
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const activeCount = countActiveFilters(filters as unknown as FilterValues);
  const chips = quickFilters(hasActiveVehicle);

  function handleToggle(key: FilterToggleKey) {
    if (key === "onlyFavorites" && !isAuthenticated) {
      openAuthModal();
      return;
    }
    filters.toggle(key);
  }

  function handleFavoritesClick() {
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    openFavoritesDrawer();
  }

  function handleVehiclesClick() {
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    openVehicleModal();
  }

  return (
    <>
      <header className="z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border-light/70 bg-surface-primary px-3 lg:h-[68px] lg:px-5">
        {/* --- Sol: panel aç/kapa + marka --- */}
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={togglePanel}
            aria-label={isPanelOpen ? "Keşif panelini kapat" : "Keşif panelini aç"}
            aria-pressed={isPanelOpen}
            data-testid="panel-toggle"
            className="flex h-10 w-10 items-center justify-center rounded-full text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary"
          >
            {isPanelOpen ? <PanelLeftClose size={19} /> : <PanelLeft size={19} />}
          </button>
          <div className="flex items-center gap-2.5">
            <BrandMark className="h-7 w-7 text-accent-green" />
            <p className="hidden font-display text-[22px] font-medium leading-none tracking-tight text-text-primary sm:block">
              KaravanTR
            </p>
          </div>
        </div>

        {/* --- Orta: hızlı filtreler (yalnızca lg+) --- */}
        <div className="hidden flex-1 items-center justify-center gap-1.5 lg:flex">
          {chips.map(({ key, label, Icon }) => {
            const isActive = filters[key];
            return (
              <button
                key={key}
                type="button"
                aria-pressed={isActive}
                onClick={() => handleToggle(key)}
                className={[
                  "flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-medium transition-colors",
                  isActive
                    ? "border-accent-green bg-accent-green text-text-on-dark"
                    : "border-text-primary/15 text-text-primary/80 hover:border-text-primary/35 hover:text-text-primary",
                ].join(" ")}
              >
                <Icon size={14} />
                {label}
              </button>
            );
          })}
          <button
            type="button"
            data-testid="open-all-filters"
            onClick={() => setIsFiltersOpen(true)}
            className="flex h-9 items-center gap-1.5 rounded-full border border-text-primary/15 px-3.5 text-[13px] font-medium text-text-primary/80 transition-colors hover:border-text-primary/35 hover:text-text-primary"
          >
            <SlidersHorizontal size={14} />
            Tüm Filtreler
            {activeCount > 0 ? (
              <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-green px-1 text-[10px] font-bold text-text-on-dark">
                {activeCount}
              </span>
            ) : null}
          </button>
        </div>

        {/* --- Orta (dar ekran): sadece filtre girişi, sayaçlı --- */}
        <button
          type="button"
          onClick={() => setIsFiltersOpen(true)}
          aria-label="Filtreler"
          className="ml-auto flex h-10 items-center gap-1.5 rounded-full px-2.5 text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary lg:hidden"
        >
          <SlidersHorizontal size={18} />
          {activeCount > 0 ? (
            <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-green px-1 text-[10px] font-bold text-text-on-dark">
              {activeCount}
            </span>
          ) : null}
        </button>

        {/* --- Sağ: kaydedilenler / araçlarım / kullanıcı (yalnızca lg+) --- */}
        <div className="hidden shrink-0 items-center gap-1 lg:flex">
          <button
            type="button"
            onClick={handleFavoritesClick}
            className="flex h-10 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary"
          >
            <Star size={16} />
            Kaydedilenler
          </button>
          <button
            type="button"
            onClick={handleVehiclesClick}
            className="flex h-10 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary"
          >
            <Caravan size={16} />
            Araçlarım
          </button>
          <div className="mx-1 h-6 w-px bg-border-light" />
          {isAuthenticated ? (
            <UserMenu onOpenModeration={openModeration} />
          ) : (
            <button
              type="button"
              onClick={openAuthModal}
              className="flex h-10 items-center gap-1.5 rounded-full bg-accent-green px-4 text-[13px] font-semibold text-text-on-dark transition-colors hover:bg-accent-green-hover"
            >
              <LogIn size={15} />
              Giriş Yap
            </button>
          )}
        </div>

        {/* --- Sağ (dar ekran): hamburger - ikincil eylemler burada toplanır --- */}
        <button
          type="button"
          onClick={() => setIsMobileMenuOpen(true)}
          aria-label="Menü"
          data-testid="open-mobile-menu"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-text-secondary transition-colors hover:bg-surface-secondary hover:text-text-primary lg:hidden"
        >
          <Menu size={20} />
        </button>
      </header>

      {isFiltersOpen ? <FiltersModal onClose={() => setIsFiltersOpen(false)} /> : null}
      {isMobileMenuOpen ? (
        <MobileMenu
          onClose={() => setIsMobileMenuOpen(false)}
          onFavorites={handleFavoritesClick}
          onVehicles={handleVehiclesClick}
          onModeration={openModeration}
        />
      ) : null}
    </>
  );
}

/** Dar ekranda hamburger menüsü: Kaydedilenler/Araçlarım + kullanıcı bilgisi/çıkış (bkz. UserMenu içeriğiyle aynı eylemler). */
function MobileMenu({
  onClose,
  onFavorites,
  onVehicles,
  onModeration,
}: {
  onClose: () => void;
  onFavorites: () => void;
  onVehicles: () => void;
  onModeration: () => void;
}) {
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const logout = useAuthStore((s) => s.logout);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const isStaff = user?.role === "moderator" || user?.role === "admin";
  const ROLE_LABEL: Record<string, string> = { user: "Kullanıcı", moderator: "Moderatör", admin: "Yönetici" };

  return (
    <div
      className="animate-overlay-fade-in fixed inset-0 z-40 flex justify-end bg-map-bg/60"
      onClick={onClose}
    >
      <div
        className="animate-sheet-rise-in flex h-full w-72 max-w-[85vw] flex-col bg-surface-primary shadow-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-border-light p-4">
          {isAuthenticated && user ? (
            <div>
              <p className="font-semibold text-text-primary">{user.display_name}</p>
              <p className="text-xs text-text-secondary">
                {ROLE_LABEL[user.role]} · Güven {user.trust_score}
              </p>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => {
                onClose();
                openAuthModal();
              }}
              className="flex min-h-touch w-full items-center justify-center gap-1.5 rounded-full bg-accent-green px-3 text-sm font-semibold text-text-on-dark"
            >
              <LogIn size={15} />
              Giriş Yap
            </button>
          )}
        </div>
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
          <MobileMenuItem
            icon={<Star size={17} />}
            label="Kaydedilenler"
            onClick={() => {
              onClose();
              onFavorites();
            }}
          />
          <MobileMenuItem
            icon={<Caravan size={17} />}
            label="Araçlarım"
            onClick={() => {
              onClose();
              onVehicles();
            }}
          />
          {isStaff ? (
            <MobileMenuItem
              icon={<ShieldCheck size={17} />}
              label="Moderasyon"
              onClick={() => {
                onClose();
                onModeration();
              }}
            />
          ) : null}
        </nav>
        {isAuthenticated ? (
          <div className="border-t border-border-light p-2">
            <MobileMenuItem
              label="Çıkış Yap"
              danger
              onClick={() => {
                onClose();
                logout();
              }}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MobileMenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon?: ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex min-h-touch w-full items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors",
        danger ? "text-warning-rust hover:bg-warning-rust/10" : "text-text-primary hover:bg-surface-secondary",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

/** Marka işareti: iki sırt ve yol - hero'daki sırt silüetleriyle aynı dil. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" aria-hidden>
      <path d="M2 24 L11 11 L16 17 L21 9 L30 24 Z" fill="currentColor" />
      <path d="M13 24 C15 21 17 21 19 24" stroke="rgb(var(--surface-primary))" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="24" cy="6" r="2.2" fill="rgb(var(--accent-brass))" />
    </svg>
  );
}
