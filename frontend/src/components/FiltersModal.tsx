/**
 * "Tüm Filtreler" - hızlı filtrelerde YER ALMAYAN geri kalan anahtarlar +
 * tamlık için hızlı olanların da tekrarı. Ortak `Modal` kabuğunu kullanır,
 * bu yüzden mobilde otomatik olarak tam ekran alt sayfaya döner (görev
 * tanımındaki "filtre drawer'ı" ihtiyacı ayrı bir bileşen gerektirmeden
 * karşılanmış olur).
 */
import { Caravan, Droplets, Gauge, Mountain, RotateCcw, ShieldCheck, SlidersHorizontal, Star, Zap } from "lucide-react";
import type { ComponentType } from "react";
import { useFilterStore, type FilterToggleKey } from "../store/filters";
import { useAuthStore } from "../store/useAuthStore";
import { useVehicleProfileStore } from "../store/useVehicleProfileStore";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

interface ToggleDef {
  key: FilterToggleKey;
  label: string;
  hint: string;
  Icon: ComponentType<{ size?: number; className?: string }>;
}

const ALL_TOGGLES: ToggleDef[] = [
  { key: "hasToilet", label: "Tuvalet (WC)", hint: "Bildirilen bilgiye göre filtrele", Icon: ShieldCheck },
  { key: "hasTrashBins", label: "Çöp Kutusu", hint: "Bildirilen bilgiye göre filtrele", Icon: ShieldCheck },
  { key: "freeOnly", label: "Ücretsiz", hint: "Bildirilen bilgiye göre filtrele", Icon: ShieldCheck },
  { key: "campingAllowed", label: "Kamp Davranışı Serbest", hint: "Bildirilen bilgiye göre filtrele", Icon: ShieldCheck },
  { key: "overnightAllowed", label: "Geceleme İzni Var", hint: "Bildirilen bilgiye göre filtrele", Icon: ShieldCheck },

  { key: "vehicleCompatibleOnly", label: "Aracıma Uygun", hint: "Aktif araç profiline uygun olmayanları gizle", Icon: Gauge },
  { key: "hasFreshWater", label: "Tatlı Su", hint: "Su kaynağı bildirilen noktalar", Icon: Droplets },
  { key: "hasElectricity", label: "Elektrik", hint: "220V bağlantısı bildirilen noktalar", Icon: Zap },
  { key: "onlyVerified", label: "Onaylı Noktalar", hint: "Moderatör tarafından onaylanmış noktalar", Icon: ShieldCheck },
  { key: "no4x4Required", label: "4x4 Gerekmez", hint: "Standart araçla erişilebilen noktalar", Icon: Mountain },
  { key: "caravanOnly", label: "Çekme Karavan Kabul Eder", hint: "Çekme karavana izin veren noktalar", Icon: Caravan },
  { key: "onlyFavorites", label: "Sadece Favorilerim", hint: "Kaydettiğin noktalar", Icon: Star },
];

export default function FiltersModal({ onClose }: { onClose: () => void }) {
  const filters = useFilterStore();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const hasActiveVehicle = useVehicleProfileStore((s) => s.profiles.some((p) => p.is_active));

  const toggles = ALL_TOGGLES.filter((t) => t.key !== "vehicleCompatibleOnly" || hasActiveVehicle);

  function handleToggle(key: FilterToggleKey) {
    if (key === "onlyFavorites" && !isAuthenticated) {
      openAuthModal();
      return;
    }
    filters.toggle(key);
  }

  return (
    <Modal
      title="Tüm Filtreler"
      icon={<SlidersHorizontal size={18} />}
      onClose={onClose}
      maxWidth="sm"
      testId="filters-modal"
      footer={
        <div className="flex items-center justify-between gap-3">
          <Button variant="ghost" size="sm" onClick={filters.reset}>
            <RotateCcw size={14} />
            Filtreleri Temizle
          </Button>
          <Button variant="primary" onClick={onClose}>
            Uygula
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-1.5">
        {toggles.map(({ key, label, hint, Icon }) => {
          const isActive = filters[key];
          return (
            <button
              key={key}
              type="button"
              aria-pressed={isActive}
              onClick={() => handleToggle(key)}
              className={[
                "flex min-h-touch items-center gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
                isActive
                  ? "border-accent-green bg-accent-green/10"
                  : "border-border-light hover:bg-surface-secondary",
              ].join(" ")}
            >
              <Icon size={18} className={isActive ? "shrink-0 text-accent-green" : "shrink-0 text-text-secondary"} />
              <span className="min-w-0 flex-1">
                <span className={`block text-sm font-medium ${isActive ? "text-accent-green" : "text-text-primary"}`}>
                  {label}
                </span>
                <span className="block text-xs text-text-secondary">{hint}</span>
              </span>
              <span
                aria-hidden
                className={[
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2",
                  isActive ? "border-accent-green bg-accent-green" : "border-border-light",
                ].join(" ")}
              >
                {isActive ? <span className="h-2 w-2 rounded-full bg-surface-primary" /> : null}
              </span>
            </button>
          );
        })}
      </div>
    </Modal>
  );
}
