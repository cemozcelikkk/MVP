/**
 * "Araçlarım" yönetim modalı - araç profili ekleme/düzenleme/silme ve aktif
 * aracı değiştirme. İçeride "liste" ve "form" (ekle/düzenle) olmak üzere iki
 * görünüm arasında geçiş yapar.
 *
 * Görünürlük `useVehicleProfileStore` üzerinden kontrol edilir ki
 * `AppTopBar` ve `SpotDetailSidebar`daki `CompatibilityCard` (kardeşi
 * olmayan bileşenler) bunu prop-drilling olmadan açabilsin.
 */
import { Caravan, Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import type { VehicleProfile, VehicleProfilePayload, VehicleType, Drivetrain } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { VEHICLE_TYPE_LABEL } from "../lib/vehicleLabels";
import { useVehicleProfileStore } from "../store/useVehicleProfileStore";
import { Field, INPUT_CLASS, NumberField, SegmentedGroup, ToggleField } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

// Etiketler `lib/vehicleLabels.ts`teki TEK kaynaktan geliyor ki bir yorumun
// araç anlık görüntüsündeki metin ("Campervan · 6,4 m") burada seçilen
// etiketle HER ZAMAN birebir aynı olsun.
const VEHICLE_TYPE_OPTIONS: { value: VehicleType; label: string }[] = (
  Object.entries(VEHICLE_TYPE_LABEL) as [VehicleType, string][]
).map(([value, label]) => ({ value, label }));

const DRIVETRAIN_OPTIONS: { value: Drivetrain; label: string }[] = [
  { value: "4x2", label: "4x2" },
  { value: "4x4", label: "4x4" },
];

export default function VehicleProfilesModal() {
  const isModalOpen = useVehicleProfileStore((s) => s.isModalOpen);
  if (!isModalOpen) return null;
  // `key` yok ama içerik her açılışta yeniden mount edilsin diye dış kabuk
  // sadece `isModalOpen` true iken render ediliyor - bu, iç görünüm
  // state'inin (liste/form) her açılışta temiz başlamasını sağlar.
  return <VehicleProfilesModalInner />;
}

function VehicleProfilesModalInner() {
  const startInAddMode = useVehicleProfileStore((s) => s.startInAddMode);
  const closeModal = useVehicleProfileStore((s) => s.closeModal);
  const profiles = useVehicleProfileStore((s) => s.profiles);
  const isLoading = useVehicleProfileStore((s) => s.isLoading);
  const listError = useVehicleProfileStore((s) => s.error);
  const fetchProfiles = useVehicleProfileStore((s) => s.fetchProfiles);
  const removeProfile = useVehicleProfileStore((s) => s.removeProfile);
  const activateProfile = useVehicleProfileStore((s) => s.activateProfile);

  const [view, setView] = useState<"list" | "form">(startInAddMode ? "form" : "list");
  const [editingProfile, setEditingProfile] = useState<VehicleProfile | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  function openAddForm() {
    setEditingProfile(null);
    setView("form");
  }
  function openEditForm(profile: VehicleProfile) {
    setEditingProfile(profile);
    setView("form");
  }

  async function handleActivate(profileId: string) {
    setPendingActionId(profileId);
    setRowError(null);
    try {
      await activateProfile(profileId);
    } catch (err) {
      setRowError(extractErrorMessage(err, "Araç aktifleştirilemedi."));
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleDelete(profileId: string) {
    setPendingActionId(profileId);
    setRowError(null);
    try {
      await removeProfile(profileId);
      setConfirmingDeleteId(null);
    } catch (err) {
      setRowError(extractErrorMessage(err, "Araç silinemedi."));
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <Modal
      title={view === "form" ? (editingProfile ? "Aracı Düzenle" : "Araç Ekle") : "Araçlarım"}
      icon={<Caravan size={18} />}
      onClose={closeModal}
      maxWidth="lg"
      testId="vehicle-profiles-modal"
    >
      {view === "form" ? (
        <VehicleProfileForm editingProfile={editingProfile} onCancel={() => setView("list")} onSaved={() => setView("list")} />
      ) : isLoading ? (
        <p className="py-6 text-center text-sm text-text-secondary">Yükleniyor…</p>
      ) : listError ? (
        <div className="py-6 text-center">
          <p className="mb-3 text-sm text-warning-rust">{listError}</p>
          <Button variant="secondary" onClick={() => fetchProfiles()}>
            Tekrar Dene
          </Button>
        </div>
      ) : profiles.length === 0 ? (
        <div className="py-6 text-center">
          <p className="mx-auto mb-4 max-w-xs text-sm leading-relaxed text-text-secondary">
            Aracınızı ekleyerek noktaların size uygun olup olmadığını otomatik görebilirsiniz.
          </p>
          <Button variant="primary" onClick={openAddForm} className="mx-auto">
            <Plus size={15} />
            Araç Ekle
          </Button>
        </div>
      ) : (
        <>
          {rowError ? <p className="mb-3 text-sm text-warning-rust">{rowError}</p> : null}
          <div className="flex flex-col gap-2.5">
            {profiles.map((profile) => (
              <VehicleProfileCard
                key={profile.id}
                profile={profile}
                isPending={pendingActionId === profile.id}
                isConfirmingDelete={confirmingDeleteId === profile.id}
                onActivate={() => handleActivate(profile.id)}
                onEdit={() => openEditForm(profile)}
                onRequestDelete={() => setConfirmingDeleteId(profile.id)}
                onCancelDelete={() => setConfirmingDeleteId(null)}
                onConfirmDelete={() => handleDelete(profile.id)}
              />
            ))}
          </div>
          <Button variant="secondary" onClick={openAddForm} className="mt-3 w-full">
            <Plus size={15} />
            Araç Ekle
          </Button>
        </>
      )}
    </Modal>
  );
}

function VehicleProfileCard({
  profile,
  isPending,
  isConfirmingDelete,
  onActivate,
  onEdit,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  profile: VehicleProfile;
  isPending: boolean;
  isConfirmingDelete: boolean;
  onActivate: () => void;
  onEdit: () => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const specs = [
    `${profile.length_m} m`,
    profile.width_m != null ? `${profile.width_m} m` : null,
    profile.height_m != null ? `${profile.height_m} m` : null,
    profile.weight_kg != null ? `${profile.weight_kg} kg` : null,
    profile.drivetrain,
  ].filter(Boolean);

  return (
    <div className={["rounded-md border p-3", profile.is_active ? "border-accent-green bg-accent-green/5" : "border-border-light"].join(" ")}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-text-primary">{profile.name}</p>
        {profile.is_active ? (
          <span className="shrink-0 rounded-full border border-accent-green px-2 py-0.5 text-[11px] font-semibold text-accent-green">Aktif</span>
        ) : null}
      </div>
      <p className="mb-2 text-xs font-medium text-text-secondary">{VEHICLE_TYPE_LABEL[profile.vehicle_type]}</p>
      <p className="mb-3 font-mono text-xs text-text-secondary">{specs.join(" · ")}</p>

      {isConfirmingDelete ? (
        <div className="rounded-md border border-warning-rust p-2.5">
          <p className="mb-2 text-xs text-text-primary">Bu aracı silmek istediğinize emin misiniz?</p>
          <div className="flex gap-2">
            <Button variant="danger-solid" size="sm" className="flex-1" onClick={onConfirmDelete} disabled={isPending}>
              {isPending ? "Siliniyor…" : "Evet, Sil"}
            </Button>
            <Button variant="secondary" size="sm" className="flex-1" onClick={onCancelDelete} disabled={isPending}>
              Vazgeç
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          {!profile.is_active ? (
            <Button variant="secondary" size="sm" className="flex-1 !border-accent-green !text-accent-green" onClick={onActivate} disabled={isPending}>
              {isPending ? "…" : "Aktif Yap"}
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" onClick={onEdit}>
            <Pencil size={13} />
            Düzenle
          </Button>
          <Button variant="secondary" size="sm" className="!text-warning-rust" onClick={onRequestDelete}>
            <Trash2 size={13} />
            Sil
          </Button>
        </div>
      )}
    </div>
  );
}

function VehicleProfileForm({
  editingProfile,
  onCancel,
  onSaved,
}: {
  editingProfile: VehicleProfile | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const addProfile = useVehicleProfileStore((s) => s.addProfile);
  const editProfile = useVehicleProfileStore((s) => s.editProfile);

  const [name, setName] = useState(editingProfile?.name ?? "");
  const [vehicleType, setVehicleType] = useState<VehicleType>(editingProfile?.vehicle_type ?? "motorhome");
  const [lengthM, setLengthM] = useState<number | null>(editingProfile?.length_m ?? null);
  const [widthM, setWidthM] = useState<number | null>(editingProfile?.width_m ?? null);
  const [heightM, setHeightM] = useState<number | null>(editingProfile?.height_m ?? null);
  const [weightKg, setWeightKg] = useState<number | null>(editingProfile?.weight_kg ?? null);
  const [drivetrain, setDrivetrain] = useState<Drivetrain>(editingProfile?.drivetrain ?? "4x2");
  const [hasGreyWaterTank, setHasGreyWaterTank] = useState(editingProfile?.has_grey_water_tank ?? false);
  const [hasBlackWaterCassette, setHasBlackWaterCassette] = useState(editingProfile?.has_black_water_cassette ?? false);
  const [hasSolarPower, setHasSolarPower] = useState(editingProfile?.has_solar_power ?? false);
  const [travelsWithPet, setTravelsWithPet] = useState(editingProfile?.travels_with_pet ?? false);
  const [isActive, setIsActive] = useState(editingProfile?.is_active ?? false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const isNameValid = name.trim().length >= 1;
  const isLengthValid = lengthM != null && lengthM > 0 && lengthM <= 30;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    if (!isNameValid) {
      setFormError("Profil adı zorunlu.");
      return;
    }
    if (!isLengthValid) {
      setFormError("Araç uzunluğu 0,1–30 m aralığında olmalı.");
      return;
    }

    const payload: VehicleProfilePayload = {
      name: name.trim(),
      vehicle_type: vehicleType,
      length_m: lengthM,
      width_m: widthM,
      height_m: heightM,
      weight_kg: weightKg,
      drivetrain,
      has_grey_water_tank: hasGreyWaterTank,
      has_black_water_cassette: hasBlackWaterCassette,
      has_solar_power: hasSolarPower,
      travels_with_pet: travelsWithPet,
      is_active: isActive,
    };

    setIsSubmitting(true);
    try {
      if (editingProfile) {
        await editProfile(editingProfile.id, payload);
      } else {
        await addProfile(payload);
      }
      onSaved();
    } catch (err) {
      setFormError(extractErrorMessage(err, "Araç profili kaydedilemedi."));
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <Field label="Profil Adı">
        <input
          type="text"
          required
          minLength={1}
          maxLength={100}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder='ör. "Ducato"'
          className={INPUT_CLASS}
        />
      </Field>

      <Field label="Araç Tipi">
        <SegmentedGroup options={VEHICLE_TYPE_OPTIONS} value={vehicleType} onChange={setVehicleType} />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <NumberField label="Uzunluk" unit="m" value={lengthM} onChange={setLengthM} min={0.1} max={30} step={0.1} required optional={false} />
        <NumberField label="Genişlik" unit="m" value={widthM} onChange={setWidthM} min={0.1} max={6} step={0.1} />
        <NumberField label="Yükseklik" unit="m" value={heightM} onChange={setHeightM} min={0.1} max={5} step={0.1} />
        <NumberField label="Ağırlık" unit="kg" value={weightKg} onChange={setWeightKg} min={1} max={10000} step={1} />
      </div>

      <Field label="Çekiş Tipi">
        <SegmentedGroup options={DRIVETRAIN_OPTIONS} value={drivetrain} onChange={setDrivetrain} />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <ToggleField label="Gri Su Tankı" checked={hasGreyWaterTank} onChange={setHasGreyWaterTank} />
        <ToggleField label="Siyah Su Kaseti" checked={hasBlackWaterCassette} onChange={setHasBlackWaterCassette} />
        <ToggleField label="Güneş Paneli" checked={hasSolarPower} onChange={setHasSolarPower} />
        <ToggleField label="Evcil Hayvanla Seyahat" checked={travelsWithPet} onChange={setTravelsWithPet} />
      </div>

      <ToggleField
        label={editingProfile?.is_active ? "Aktif Profil" : "Aktif Profil Olarak Ayarla"}
        checked={isActive}
        onChange={setIsActive}
      />
      <p className="-mt-2 text-xs text-text-secondary">
        Uyumluluk kontrolü her zaman aktif profili kullanır - kullanıcı başına yalnızca bir aktif araç olabilir.
      </p>

      {formError ? <p className="text-xs text-warning-rust">{formError}</p> : null}

      <div className="flex gap-2">
        <Button type="button" variant="secondary" className="flex-1" onClick={onCancel} disabled={isSubmitting}>
          Vazgeç
        </Button>
        <Button type="submit" variant="primary" className="flex-1" disabled={isSubmitting}>
          {isSubmitting ? "Kaydediliyor…" : editingProfile ? "Değişiklikleri Kaydet" : "Kaydet"}
        </Button>
      </div>
    </form>
  );
}
