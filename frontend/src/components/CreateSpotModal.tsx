/**
 * Yeni spot ekleme formu - haritada bir konum seçildiğinde açılan modal.
 * `useCreateSpotStore.pendingCoordinates` dolu olduğu sürece açık kalır;
 * `key`'i koordinatlara bağlı olan `CreateSpotForm` her yeni konum
 * seçiminde temiz bir form state'iyle yeniden mount edilir.
 *
 * Koordinatlar veri modelinden/formdan KALDIRILDI - haritadan seçilen konum
 * salt okunur bir "Seçilen Konum" özeti olarak gösterilir, düzenlenemez.
 * Gönderimde `coordinates` doğrudan haritadan gelen `[boylam, enlem]`
 * çiftinden kurulur (state'e hiç girmez) - sıra hiçbir yerde bozulmaz.
 */
import { ImagePlus, MapPin, Star, Upload, X } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  createSpot,
  fetchSpotById,
  uploadSpotPhotos,
  type ClearanceRequired,
  type RoadType,
  type SpotCategory,
  type SpotFeature,
} from "../lib/api";
import { EMPTY_TRAVEL_INFO, type SpotTravelInfo } from "../lib/api";
import SpotTravelFields from "./SpotTravelFields";
import { extractErrorMessage } from "../lib/errors";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { Field, INPUT_CLASS, SegmentedGroup, ToggleField } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import { Section } from "./ui/Section";

const CATEGORY_OPTIONS: { value: SpotCategory; label: string }[] = [
  { value: "wild_camping", label: "Vahşi Kamp" },
  { value: "campsite", label: "Kamping / Karavan Alanı" },
  { value: "sanistation_only", label: "Hizmet Noktası (Su/Atık)" },
  { value: "day_parking", label: "Günübirlik Mola" },
];

const ROAD_TYPE_OPTIONS: { value: RoadType; label: string }[] = [
  { value: "asphalt", label: "Asfalt" },
  { value: "dirt", label: "Toprak" },
  { value: "rocky", label: "Taşlık-Stabilize" },
];

/** Boş metin -> null; aksi halde sayı. "Bilinmiyorsa null" alanları için (bkz. görev tanımı). */
function toNullableNumber(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

/** Fotoğraf state'i: dosya, blob URL önizleme ve kapak seçimi. */
interface PhotoEntry {
  file: File;
  previewUrl: string;
  isCover: boolean;
  isApproach: boolean;
}

interface Props {
  /**
   * Başarılı oluşturmadan sonra (store'un `focusSpot`ına EK olarak) çağrılır -
   * App.tsx bunu doğrudan `setSelectedSpot`e bağlayıp detay panelini bir
   * efekt/store-senkronizasyonuna gerek kalmadan açabiliyor.
   */
  onCreated?: (feature: SpotFeature) => void;
}

export default function CreateSpotModal({ onCreated }: Props) {
  const isModalOpen = useCreateSpotStore((s) => s.isModalOpen);
  const pendingCoordinates = useCreateSpotStore((s) => s.pendingCoordinates);
  const closeModal = useCreateSpotStore((s) => s.closeModal);
  const focusSpot = useCreateSpotStore((s) => s.focusSpot);

  if (!isModalOpen || !pendingCoordinates) return null;

  return (
    <CreateSpotForm
      key={`${pendingCoordinates[0]},${pendingCoordinates[1]}`}
      coordinates={pendingCoordinates}
      onClose={closeModal}
      onCreated={(feature) => {
        focusSpot(feature);
        onCreated?.(feature);
      }}
    />
  );
}

function CreateSpotForm({
  coordinates,
  onClose,
  onCreated,
}: {
  /** [boylam, enlem] - haritadan geldiği gibi, formda hiç düzenlenmez. */
  coordinates: [number, number];
  onClose: () => void;
  onCreated: (feature: SpotFeature) => void;
}) {
  const [longitude, latitude] = coordinates;
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<SpotCategory>("wild_camping");
  const [roadType, setRoadType] = useState<RoadType>("asphalt");
  const [maxVehicleLength, setMaxVehicleLength] = useState("");
  const [isUnlimitedLength, setIsUnlimitedLength] = useState(true);
  const [maxVehicleWidth, setMaxVehicleWidth] = useState("");
  const [maxVehicleHeight, setMaxVehicleHeight] = useState("");
  const [maxVehicleWeight, setMaxVehicleWeight] = useState("");
  const [requires4x4, setRequires4x4] = useState(false);
  const [steepIncline, setSteepIncline] = useState(false);
  const [freshWater, setFreshWater] = useState(false);
  const [blackWater, setBlackWater] = useState(false);
  const [greyWater, setGreyWater] = useState(false);
  const [electricity, setElectricity] = useState(false);
  const [photos, setPhotos] = useState<PhotoEntry[]>([]);
  const [hasToilet, setHasToilet] = useState(false);
  const [hasTrashBins, setHasTrashBins] = useState(false);
  const [isFree, setIsFree] = useState(true);
  const [priceDescription, setPriceDescription] = useState("");
  const [campingBehaviorAllowed, setCampingBehaviorAllowed] = useState(true);
  const [travelInfo, setTravelInfo] = useState<SpotTravelInfo>(EMPTY_TRAVEL_INFO);
  const [ruleInformationKnown, setRuleInformationKnown] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Unmount olduğunda tüm blob URL'leri temizle.
  useEffect(() => {
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps
      for (const p of photos) URL.revokeObjectURL(p.previewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addPhotos = useCallback((files: FileList | File[]) => {
    const newEntries: PhotoEntry[] = Array.from(files)
      .filter((f) => f.type.startsWith("image/"))
      .map((file) => ({
        file,
        previewUrl: URL.createObjectURL(file),
        isCover: false,
        isApproach: false,
      }));
    if (newEntries.length === 0) return;
    setPhotos((prev) => {
      const merged = [...prev, ...newEntries];
      // Eğer hiçbiri kapak değilse ilk elemanı kapak yap.
      if (!merged.some((p) => p.isCover)) merged[0].isCover = true;
      return merged;
    });
  }, []);

  const removePhoto = useCallback((index: number) => {
    setPhotos((prev) => {
      const removed = prev[index];
      URL.revokeObjectURL(removed.previewUrl);
      const next = prev.filter((_, i) => i !== index);
      // Kapak silindiyse ilk elemanı yeni kapak yap.
      if (removed.isCover && next.length > 0) next[0].isCover = true;
      return next;
    });
  }, []);

  const setCover = useCallback((index: number) => {
    setPhotos((prev) =>
      prev.map((p, i) => ({ ...p, isCover: i === index })),
    );
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setIsSubmitting(true);
    try {
      const clearanceRequired: ClearanceRequired = requires4x4 ? "high_4x4" : "standard";
      const created = await createSpot({
        ...travelInfo,
        title,
        description: description.trim() || null,
        category,
        coordinates: { latitude, longitude },
        passability: {
          road_type: roadType,
          max_vehicle_length: isUnlimitedLength ? null : Number(maxVehicleLength) || null,
          max_vehicle_width: toNullableNumber(maxVehicleWidth),
          max_vehicle_height: toNullableNumber(maxVehicleHeight),
          max_vehicle_weight_kg: toNullableNumber(maxVehicleWeight),
          clearance_required: clearanceRequired,
          caravan_types_allowed: [],
          steep_incline: steepIncline,
        },
        amenities: {
          fresh_water_thread: freshWater,
          black_water: blackWater,
          grey_water: greyWater,
          electricity_220v: electricity,
          has_toilet: hasToilet,
          has_trash_bins: hasTrashBins,
          rule_information_known: ruleInformationKnown,
          is_free: isFree,
          price_description: isFree ? null : priceDescription.trim() || null,
          camping_behavior_allowed: campingBehaviorAllowed,
          gsm_signals: {},
        },
      });

      if (photos.length > 0) {
        const coverIndex = photos.findIndex((p) => p.isCover);
        try {
          await uploadSpotPhotos(
            created.properties.id,
            photos.map((p) => p.file),
            coverIndex >= 0 ? coverIndex : 0,
            photos.flatMap((photo,index)=>photo.isApproach?[index]:[]),
          );
        } catch {
          // Fotoğrafların yüklenememesi tüm akışı durdurmasın - spot zaten kaydedildi.
        }
        // Fotoğraflar dahil güncel hali için tek noktayı yeniden çek.
        onCreated(await fetchSpotById(created.properties.id));
      } else {
        onCreated(created);
      }
    } catch (err) {
      setFormError(extractErrorMessage(err, "Nokta oluşturulamadı."));
      setIsSubmitting(false);
    }
  }

  return (
    <Modal
      title="Yeni Nokta Ekle"
      onClose={onClose}
      maxWidth="xl"
      testId="create-spot-modal"
      footer={
        <div className="flex items-center justify-between gap-3">
          {formError ? <p className="text-xs text-warning-rust">{formError}</p> : <span />}
          <Button type="submit" form="create-spot-form" variant="primary" disabled={isSubmitting}>
            {isSubmitting ? "Kaydediliyor…" : "Kaydet ve Haritaya Ekle"}
          </Button>
        </div>
      }
    >
      <form id="create-spot-form" onSubmit={handleSubmit} className="flex flex-col">
        {/* --- Seçilen konum: haritadan gelir, düzenlenemez --- */}
        <Section>
          <div className="flex items-center gap-2 rounded-md border border-border-light bg-surface-secondary px-3 py-2.5">
            <MapPin size={16} className="shrink-0 text-accent-green" />
            <span className="text-sm text-text-primary">Seçilen konum</span>
            <span className="ml-auto font-mono text-xs text-text-secondary">
              {latitude.toFixed(5)}, {longitude.toFixed(5)}
            </span>
          </div>
        </Section>

        <Section title="Temel Bilgiler">
          <div className="flex flex-col gap-4">
            <Field label="Nokta Başlığı">
              <input
                type="text"
                required
                minLength={3}
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className={INPUT_CLASS}
              />
            </Field>
            <Field label="Açıklama">
              <textarea
                rows={3}
                maxLength={5000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className={`${INPUT_CLASS} resize-none`}
              />
            </Field>
            <Field label="Kategori">
              <SegmentedGroup options={CATEGORY_OPTIONS} value={category} onChange={setCategory} />
            </Field>
          </div>
        </Section>

        <Section title="Geçiş ve Araç Kısıtları">
          <div className="flex flex-col gap-3">
            <Field label="Yol Durumu">
              <SegmentedGroup options={ROAD_TYPE_OPTIONS} value={roadType} onChange={setRoadType} />
            </Field>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <span className="mb-1.5 block text-sm font-medium text-text-primary">Maksimum araç uzunluğu (m)</span>
                <input
                  type="number"
                  min={0.1}
                  max={30}
                  step="0.1"
                  disabled={isUnlimitedLength}
                  value={maxVehicleLength}
                  onChange={(event) => setMaxVehicleLength(event.target.value)}
                  placeholder="örn. 6.5"
                  className={INPUT_CLASS}
                />
                <label className="mt-1.5 flex items-center gap-1.5 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    checked={isUnlimitedLength}
                    onChange={(event) => setIsUnlimitedLength(event.target.checked)}
                  />
                  Limitsiz
                </label>
              </div>
              <Field label="Maksimum araç genişliği (m)">
                <input
                  type="number"
                  min={0.1}
                  max={6}
                  step="0.1"
                  value={maxVehicleWidth}
                  onChange={(event) => setMaxVehicleWidth(event.target.value)}
                  placeholder="bilinmiyorsa boş bırakın"
                  className={INPUT_CLASS}
                />
              </Field>
              <Field label="Maksimum araç yüksekliği (m)">
                <input
                  type="number"
                  min={0.1}
                  max={5}
                  step="0.1"
                  value={maxVehicleHeight}
                  onChange={(event) => setMaxVehicleHeight(event.target.value)}
                  placeholder="bilinmiyorsa boş bırakın"
                  className={INPUT_CLASS}
                />
              </Field>
              <Field label="Maksimum araç ağırlığı (kg)">
                <input
                  type="number"
                  min={1}
                  max={10000}
                  step="1"
                  value={maxVehicleWeight}
                  onChange={(event) => setMaxVehicleWeight(event.target.value)}
                  placeholder="bilinmiyorsa boş bırakın"
                  className={INPUT_CLASS}
                />
              </Field>
              <ToggleField label="4x4 Gerekli mi?" checked={requires4x4} onChange={setRequires4x4} />
              <ToggleField label="Dik Eğim / Zorlu Viraj" checked={steepIncline} onChange={setSteepIncline} />
            </div>
          </div>
        </Section>

        <SpotTravelFields value={travelInfo} onChange={setTravelInfo} />

        <Section title="Olanaklar">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ToggleField label="Tatlı Su" checked={freshWater} onChange={setFreshWater} />
            <ToggleField label="Siyah Su Dökümü" checked={blackWater} onChange={setBlackWater} />
            <ToggleField label="Gri Su Boşaltma" checked={greyWater} onChange={setGreyWater} />
            <ToggleField label="Tuvalet (WC)" checked={hasToilet} onChange={setHasToilet} />
            <ToggleField label="Çöp Kutusu" checked={hasTrashBins} onChange={setHasTrashBins} />
            <ToggleField label="220V Elektrik" checked={electricity} onChange={setElectricity} />
          </div>
        </Section>
        <Section title="Kurallar ve Ücret">
          <div className="flex flex-col gap-3">
            <ToggleField label="Ücret ve kamp davranışı bilgisini biliyorum" checked={ruleInformationKnown} onChange={setRuleInformationKnown} />
            <p className="text-xs text-text-secondary">Kapalıysa bu bilgiler bilinmiyor olarak gösterilir.</p>
            <ToggleField disabled={!ruleInformationKnown} label="Ücretsiz mi?" checked={isFree} onChange={setIsFree} />
            {!isFree && <Field label="Ücret Açıklaması">
              <input type="text" maxLength={300} value={priceDescription}
                onChange={(event) => setPriceDescription(event.target.value)}
                placeholder="Örn: Gecelik 400 TL" className={INPUT_CLASS} />
            </Field>}
            <ToggleField disabled={!ruleInformationKnown} label="Kamp Davranışı İzni" checked={campingBehaviorAllowed} onChange={setCampingBehaviorAllowed} />
            <p className="text-xs text-text-secondary">Tente açılabilir, masa/sandalye dışarı konulabilir.</p>
          </div>
        </Section>

        <Section title="Fotoğraflar">
          <PhotoUploadSection
            photos={photos}
            onAddPhotos={addPhotos}
            onRemovePhoto={removePhoto}
            onSetCover={setCover}
            onToggleApproach={(index)=>setPhotos(prev=>prev.map((photo,i)=>i===index?{...photo,isApproach:!photo.isApproach}:photo))}
          />
        </Section>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Çoklu fotoğraf yükleme bileşeni
// ---------------------------------------------------------------------------

function PhotoUploadSection({
  photos,
  onAddPhotos,
  onRemovePhoto,
  onSetCover,
  onToggleApproach,
}: {
  photos: PhotoEntry[];
  onAddPhotos: (files: FileList | File[]) => void;
  onRemovePhoto: (index: number) => void;
  onSetCover: (index: number) => void;
  onToggleApproach: (index: number) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current = 0;
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) onAddPhotos(e.dataTransfer.files);
    },
    [onAddPhotos],
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Sürükle-bırak / dosya seçim alanı */}
      <div
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 transition-colors ${
          isDragging
            ? "border-accent-green bg-accent-green/10"
            : "border-border-light bg-surface-secondary hover:border-accent-green/50 hover:bg-accent-green/5"
        }`}
      >
        {isDragging ? (
          <Upload size={28} className="text-accent-green" />
        ) : (
          <ImagePlus size={28} className="text-text-secondary" />
        )}
        <p className="text-center text-sm text-text-secondary">
          {isDragging ? (
            <span className="font-semibold text-accent-green">Bırakarak yükleyin</span>
          ) : (
            <>
              <span className="font-semibold text-accent-green">Fotoğraf seçin</span> veya sürükleyip bırakın
            </>
          )}
        </p>
        <p className="text-xs text-text-secondary">JPEG, PNG, WebP — birden fazla seçebilirsiniz</p>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) onAddPhotos(e.target.files);
            e.target.value = ""; // Aynı dosyayı tekrar seçebilmek için.
          }}
        />
      </div>

      {/* Thumbnail önizleme grid'i */}
      {photos.length > 0 && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {photos.map((photo, idx) => (
            <div
              key={photo.previewUrl}
              className={`group relative aspect-square overflow-hidden rounded-lg border-2 transition-colors ${
                photo.isCover ? "border-accent-green" : "border-transparent hover:border-border-light"
              }`}
            >
              <img
                src={photo.previewUrl}
                alt={`Fotoğraf ${idx + 1}`}
                className="h-full w-full object-cover"
              />

              <button type="button" aria-pressed={photo.isApproach} onClick={()=>onToggleApproach(idx)} className="absolute right-1 top-8 rounded-md bg-white/95 p-1 text-[10px] text-text-primary">{photo.isApproach?"✓ Giriş / yol":"Giriş / yol olarak işaretle"}</button>
              {/* Kapak rozeti */}
              {photo.isCover && (
                <div className="absolute left-1 top-1 flex items-center gap-0.5 rounded-md bg-accent-green/90 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  <Star size={10} fill="currentColor" />
                  Kapak
                </div>
              )}

              {/* Hover overlay: Kapak yap + Sil */}
              <div className="absolute inset-0 flex items-end justify-between bg-gradient-to-t from-black/50 to-transparent p-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                {!photo.isCover && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSetCover(idx);
                    }}
                    className="flex items-center gap-0.5 rounded-md bg-white/90 px-1.5 py-0.5 text-[10px] font-semibold text-text-primary transition-colors hover:bg-white"
                    title="Kapak fotoğrafı yap"
                  >
                    <Star size={10} />
                    Kapak
                  </button>
                )}
                {photo.isCover && <span />}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemovePhoto(idx);
                  }}
                  className="rounded-full bg-white/90 p-1 text-warning-rust transition-colors hover:bg-white"
                  title="Fotoğrafı kaldır"
                >
                  <X size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {photos.length > 0 && (
        <p className="text-xs text-text-secondary">
          {photos.length} fotoğraf seçildi · Kapak fotoğrafını değiştirmek için üzerine tıklayın
        </p>
      )}
    </div>
  );
}
