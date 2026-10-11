/**
 * Yeni nokta ekleme akışının ilk ve kısa adımları.
 *
 * 1. `AddPlaceChooser` - "Ne eklemek istiyorsunuz?": Kamp / Karavan Alanı,
 *    Yeme & İçme, Sağlık Hizmetleri, Temel İhtiyaçlar kartları. Hizmet
 *    gruplarında hemen ardından alt tür (ör. Sağlık Ocağı) seçilir; konum henüz
 *    yoksa (haritada sağ tık ile gelinmediyse) son adım konum yöntemidir.
 * 2. Kamp seçildiyse mevcut detaylı form (`CreateSpotModal`) açılır.
 * 3. Hizmet noktalarında `ServicePointCreateModal`: tür + konum (+ restoranlarda
 *    ad; sağlıkta harita verisinden önerilen opsiyonel ad; WC/duşta opsiyonel
 *    ücret/kullanılabilirlik). Uzun açıklama, değerlendirme ya da araç
 *    soruları YOK - yıldız/yorum ve durum bilgisi sonradan detay panelinden eklenir.
 */
import { ArrowLeft, ChevronRight, Loader2, MapPin, MapPinned, Navigation } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import axios from "axios";
import {
  createServicePoint,
  fetchServicePoint,
  fetchServicePointNameSuggestion,
  type AvailabilityStatus,
  type FeeStatus,
  type ServicePointCategory,
  type ServicePointFeature,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import {
  AVAILABILITY_LABEL,
  FEE_LABEL,
  SERVICE_CATEGORY_LABEL,
  SERVICE_GROUPS,
  serviceIconSvg,
  servicePinColors,
} from "../lib/servicePoints";
import { CATEGORY_PIN_STYLE, categoryIconSvg } from "../lib/pinStyle";
import type { PlaceGroup } from "../store/filters";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useMapDataStore } from "../store/useMapDataStore";
import { Field, INPUT_CLASS, SegmentedGroup } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

interface Props {
  /** Hizmet noktası oluşturulunca detay panelini açmak için (App.tsx). */
  onServicePointCreated?: (feature: ServicePointFeature) => void;
}

export default function AddPlaceFlow({ onServicePointCreated }: Props) {
  const isChooserOpen = useCreateSpotStore((s) => s.isChooserOpen);
  const isModalOpen = useCreateSpotStore((s) => s.isModalOpen);
  const addGroup = useCreateSpotStore((s) => s.addGroup);
  const addCategory = useCreateSpotStore((s) => s.addCategory);
  const pendingCoordinates = useCreateSpotStore((s) => s.pendingCoordinates);

  if (isChooserOpen) return <AddPlaceChooser />;
  if (isModalOpen && pendingCoordinates && addGroup && addGroup !== "camping" && addCategory) {
    return (
      <ServicePointCreateModal
        key={`${addCategory}:${pendingCoordinates.join(",")}`}
        category={addCategory}
        coordinates={pendingCoordinates}
        onCreated={onServicePointCreated}
      />
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Tür seçimi
// ---------------------------------------------------------------------------

const MAIN_OPTIONS: { group: PlaceGroup; label: string; description: string; iconHtml: string; fill: string }[] = [
  {
    group: "camping",
    label: "Kamp / Karavan Alanı",
    description: "Konaklama noktası - araç, yol, zemin ve olanak bilgileriyle",
    iconHtml: categoryIconSvg("CAMPING"),
    fill: CATEGORY_PIN_STYLE.CAMPING.fill,
  },
  ...SERVICE_GROUPS.map(({ group, label, description, categories }) => ({
    group,
    label,
    description,
    iconHtml: serviceIconSvg(categories[0]),
    fill: servicePinColors(categories[0]).fill,
  })),
];

function IconTile({ html, fill, size = 44 }: { html: string; fill: string; size?: number }) {
  return (
    <span
      aria-hidden
      className="flex shrink-0 items-center justify-center rounded-xl [&_svg]:h-[55%] [&_svg]:w-[55%]"
      style={{ backgroundColor: fill, width: size, height: size }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function AddPlaceChooser() {
  const closeChooser = useCreateSpotStore((s) => s.closeChooser);
  const chooseType = useCreateSpotStore((s) => s.chooseType);
  const addGroup = useCreateSpotStore((s) => s.addGroup);
  const startPicking = useCreateSpotStore((s) => s.startPicking);
  const useCurrentLocation = useCreateSpotStore((s) => s.useCurrentLocation);
  const isLocating = useCreateSpotStore((s) => s.isLocating);
  const hasLocation = useCreateSpotStore((s) => s.pendingCoordinates !== null);
  // Alt tür adımı yalnızca hizmet gruplarında; tür seçildiyse (addGroup dolu) konum adımındayız.
  const [subGroup, setSubGroup] = useState<PlaceGroup | null>(null);

  const step: "main" | "sub" | "location" = addGroup ? "location" : subGroup ? "sub" : "main";
  const sub = SERVICE_GROUPS.find((g) => g.group === subGroup);

  function back() {
    if (step === "location") {
      // Kampta alt adım yok, doğrudan ana listeye; hizmette alt türe dön.
      useCreateSpotStore.setState({ addGroup: null, addCategory: null });
      return;
    }
    setSubGroup(null);
  }

  const title =
    step === "main" ? "Ne eklemek istiyorsunuz?" : step === "sub" ? (sub?.label ?? "") : "Konumu nasıl seçelim?";

  return (
    <Modal title={title} onClose={closeChooser} maxWidth="md" testId="add-place-chooser">
      {step !== "main" ? (
        <button
          type="button"
          onClick={back}
          className="mb-3 flex items-center gap-1.5 text-sm font-medium text-text-secondary transition-colors hover:text-text-primary"
        >
          <ArrowLeft size={15} />
          Geri
        </button>
      ) : null}

      {step === "main" ? (
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {MAIN_OPTIONS.map((option) => (
            <button
              key={option.group}
              type="button"
              data-testid={`add-type-${option.group}`}
              onClick={() => (option.group === "camping" ? chooseType("camping", null) : setSubGroup(option.group))}
              className="flex items-start gap-3 rounded-xl border border-border-light bg-surface-primary p-3.5 text-left transition-colors hover:border-accent-green/60 hover:bg-surface-secondary/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-brass"
            >
              <IconTile html={option.iconHtml} fill={option.fill} />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-text-primary">{option.label}</span>
                <span className="mt-0.5 block text-xs leading-snug text-text-secondary">{option.description}</span>
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {step === "sub" && sub ? (
        <div className="flex flex-col gap-2">
          {sub.categories.map((category) => (
            <button
              key={category}
              type="button"
              data-testid={`add-category-${category}`}
              onClick={() => chooseType(sub.group, category)}
              className="flex items-center gap-3 rounded-xl border border-border-light p-3 text-left transition-colors hover:border-accent-green/60 hover:bg-surface-secondary/60"
            >
              <IconTile html={serviceIconSvg(category)} fill={servicePinColors(category).fill} size={38} />
              <span className="flex-1 text-sm font-semibold text-text-primary">{SERVICE_CATEGORY_LABEL[category]}</span>
              <ChevronRight size={16} className="text-text-secondary" />
            </button>
          ))}
        </div>
      ) : null}

      {step === "location" && !hasLocation ? (
        <div className="flex flex-col gap-2">
          <LocationOption
            icon={<MapPinned size={20} className="text-accent-green" />}
            title="Haritadan Seç"
            hint="Harita üzerinde noktaya tıklayın"
            onClick={startPicking}
          />
          <LocationOption
            icon={
              isLocating ? (
                <Loader2 size={20} className="animate-spin text-accent-green" />
              ) : (
                <Navigation size={20} className="text-accent-green" />
              )
            }
            title={isLocating ? "Konum alınıyor…" : "Konumumu Kullan"}
            hint="GPS ile şu an bulunduğunuz yer"
            onClick={useCurrentLocation}
            disabled={isLocating}
          />
        </div>
      ) : null}
    </Modal>
  );
}

function LocationOption({
  icon,
  title,
  hint,
  onClick,
  disabled,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-3 rounded-xl border border-border-light p-3.5 text-left transition-colors hover:border-accent-green/60 hover:bg-surface-secondary/60 disabled:opacity-60"
    >
      {icon}
      <span>
        <span className="block text-sm font-semibold text-text-primary">{title}</span>
        <span className="block text-xs text-text-secondary">{hint}</span>
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Hizmet noktası kısa formu
// ---------------------------------------------------------------------------

const FEE_OPTIONS = (["unknown", "free", "paid"] as FeeStatus[]).map((value) => ({ value, label: FEE_LABEL[value] }));
const AVAILABILITY_OPTIONS = (["unknown", "available", "unavailable"] as AvailabilityStatus[]).map((value) => ({
  value,
  label: AVAILABILITY_LABEL[value],
}));

function ServicePointCreateModal({
  category,
  coordinates,
  onCreated,
}: {
  category: ServicePointCategory;
  /** [boylam, enlem] */
  coordinates: [number, number];
  onCreated?: (feature: ServicePointFeature) => void;
}) {
  const closeModal = useCreateSpotStore((s) => s.closeModal);
  const focusServicePoint = useCreateSpotStore((s) => s.focusServicePoint);
  const [longitude, latitude] = coordinates;
  const group = SERVICE_GROUPS.find((g) => g.categories.includes(category))!.group;
  const [name, setName] = useState("");
  const [suggestedName, setSuggestedName] = useState<string | null>(null);
  const [feeStatus, setFeeStatus] = useState<FeeStatus>("unknown");
  const [availability, setAvailability] = useState<AvailabilityStatus>("unknown");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // 409: aynı yer zaten var (KaravanTR kaydı ya da harita verisi) - yeni kayıt yerine onu aç.
  const [existingId, setExistingId] = useState<string | null>(null);

  async function openExisting() {
    if (!existingId) return;
    try {
      const existing = await fetchServicePoint(existingId);
      focusServicePoint(existing);
      onCreated?.(existing);
    } catch (err) {
      setFormError(extractErrorMessage(err, "Mevcut nokta açılamadı."));
    }
  }

  // Sağlık: seçilen konumun yakınında harita verisinde (OSM) adı bilinen bir
  // kuruluş varsa adı otomatik doldur. Bulunamazsa alan boş kalır - ad zorunlu değil.
  useEffect(() => {
    if (group !== "health") return;
    let cancelled = false;
    fetchServicePointNameSuggestion(category, latitude, longitude)
      .then((result) => {
        if (cancelled || !result.name) return;
        setSuggestedName(result.name);
        setName((current) => current || result.name || "");
      })
      .catch(() => {
        // Öneri yalnızca kolaylık - hata akışı durdurmaz.
      });
    return () => {
      cancelled = true;
    };
  }, [group, category, latitude, longitude]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setExistingId(null);
    setIsSubmitting(true);
    try {
      const created = await createServicePoint({
        category,
        coordinates: { latitude, longitude },
        name: name.trim() || null,
        ...(group === "basic"
          ? {
              fee_status: feeStatus === "unknown" ? null : feeStatus,
              availability_status: availability === "unknown" ? null : availability,
            }
          : {}),
      });
      focusServicePoint(created);
      useMapDataStore.getState().retry();
      onCreated?.(created);
    } catch (err) {
      setFormError(extractErrorMessage(err, "Nokta eklenemedi."));
      if (axios.isAxiosError(err) && err.response?.status === 409 && err.response.data?.existing_id) {
        setExistingId(String(err.response.data.existing_id));
      }
      setIsSubmitting(false);
    }
  }

  const isFood = group === "food";
  const nameLabel = isFood ? "İşletme adı" : group === "health" ? "Kuruluş adı (isteğe bağlı)" : "Ad / tarif (isteğe bağlı)";

  return (
    <Modal
      title={`${SERVICE_CATEGORY_LABEL[category]} Ekle`}
      icon={<IconTile html={serviceIconSvg(category)} fill={servicePinColors(category).fill} size={30} />}
      onClose={closeModal}
      maxWidth="md"
      testId="create-service-point-modal"
      footer={
        <div className="flex items-center justify-between gap-3">
          {formError ? <p className="text-xs text-warning-rust">{formError}</p> : <span />}
          {existingId ? (
            <Button variant="primary" onClick={openExisting} data-testid="open-existing-point">
              Mevcut noktayı aç
            </Button>
          ) : (
            <Button type="submit" form="create-service-point-form" variant="primary" disabled={isSubmitting}>
              {isSubmitting ? "Ekleniyor…" : "Ekle"}
            </Button>
          )}
        </div>
      }
    >
      <form id="create-service-point-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex items-center gap-2 rounded-md border border-border-light bg-surface-secondary px-3 py-2.5">
          <MapPin size={16} className="shrink-0 text-accent-green" />
          <span className="text-sm text-text-primary">Seçilen konum</span>
          <span className="ml-auto font-mono text-xs text-text-secondary">
            {latitude.toFixed(5)}, {longitude.toFixed(5)}
          </span>
          <button
            type="button"
            onClick={() => useCreateSpotStore.setState({ isModalOpen: false, isPickingLocation: true, pendingCoordinates: null })}
            className="ml-1 shrink-0 rounded-md px-2 py-1 text-xs font-semibold text-accent-green transition-colors hover:bg-accent-green/10"
          >
            Değiştir
          </button>
        </div>

        <Field
          label={nameLabel}
          hint={suggestedName && name === suggestedName ? "Harita verisinden otomatik dolduruldu - düzeltebilirsiniz." : undefined}
        >
          <input
            type="text"
            required={isFood}
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={isFood ? "örn. Deniz Balık Evi" : undefined}
            className={INPUT_CLASS}
          />
        </Field>

        {group === "basic" ? (
          <>
            <Field label="Ücret">
              <SegmentedGroup options={FEE_OPTIONS} value={feeStatus} onChange={setFeeStatus} />
            </Field>
            <Field label="Şu an kullanılabilir mi?">
              <SegmentedGroup options={AVAILABILITY_OPTIONS} value={availability} onChange={setAvailability} />
            </Field>
            <p className="text-xs text-text-secondary">Bilmiyorsanız boş geçin; siz veya başkaları sonra güncelleyebilir.</p>
          </>
        ) : null}
        {isFood ? (
          <p className="text-xs text-text-secondary">Yıldız ve yorumu eklendikten sonra nokta detayından bırakabilirsiniz.</p>
        ) : null}
      </form>
    </Modal>
  );
}
