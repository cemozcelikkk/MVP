import { useAuthStore } from "../store/useAuthStore";
/**
 * Mevcut bir spot'u düzenleme formu - `CreateSpotModal` ile aynı alan
 * setini (koordinatlar hariç) paylaşır, sadece PATCH ile gönderir.
 * Konum salt okunur bir özet olarak gösterilir: bu uç konum taşımaz
 * (bkz. backend `SpotUpdate` şeması).
 */
import { MapPin } from "lucide-react";
import { type FormEvent, useState } from "react";
import {
  updateSpot,
  type ClearanceRequired,
  type RoadType,
  type SpotCategory,
  type SpotFeature,
} from "../lib/api";
import { EMPTY_TRAVEL_INFO, type SpotTravelInfo } from "../lib/api";
import SpotTravelFields from "./SpotTravelFields";
import { extractErrorMessage } from "../lib/errors";
import { Field, INPUT_CLASS, SegmentedGroup, ToggleField } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import { Section } from "./ui/Section";

const CATEGORY_OPTIONS: { value: SpotCategory; label: string }[] = [
  { value: "wild_camping", label: "Vahşi Kamp" },
  { value: "campsite", label: "Kamping / Karavan Alanı" },
  { value: "sanistation_only", label: "Hizmet Noktası (Su/Atık)" },
  { value: "day_parking", label: "Günübirlik Mola" },
  { value: "farm_stay", label: "Çiftlik Konaklaması" },
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

interface Props {
  spot: SpotFeature;
  onClose: () => void;
  onUpdated: (feature: SpotFeature) => void;
}

export default function EditSpotModal({ spot, onClose, onUpdated }: Props) {
  const { properties, geometry } = spot;
  const [lon, lat] = geometry.coordinates;

  const isStaff = useAuthStore(s=>s.user?.role === "moderator" || s.user?.role === "admin");
  const [pointLatitude,setPointLatitude] = useState(lat);
  const [pointLongitude,setPointLongitude] = useState(lon);
  const [title, setTitle] = useState(properties.title);
  const [description, setDescription] = useState(properties.description ?? "");
  const [category, setCategory] = useState<SpotCategory>(properties.category);
  const [roadType, setRoadType] = useState<RoadType>(properties.passability?.road_type ?? "asphalt");
  const [maxVehicleLength, setMaxVehicleLength] = useState(
    properties.passability?.max_vehicle_length != null ? String(properties.passability.max_vehicle_length) : "",
  );
  const [isUnlimitedLength, setIsUnlimitedLength] = useState(properties.passability?.max_vehicle_length == null);
  const [maxVehicleWidth, setMaxVehicleWidth] = useState(
    properties.passability?.max_vehicle_width != null ? String(properties.passability.max_vehicle_width) : "",
  );
  const [maxVehicleHeight, setMaxVehicleHeight] = useState(
    properties.passability?.max_vehicle_height != null ? String(properties.passability.max_vehicle_height) : "",
  );
  const [maxVehicleWeight, setMaxVehicleWeight] = useState(
    properties.passability?.max_vehicle_weight_kg != null ? String(properties.passability.max_vehicle_weight_kg) : "",
  );
  const [requires4x4, setRequires4x4] = useState(properties.passability?.clearance_required === "high_4x4");
  const [steepIncline, setSteepIncline] = useState(!!properties.passability?.steep_incline);
  const [freshWater, setFreshWater] = useState(!!properties.amenities?.fresh_water_thread);
  const [blackWater, setBlackWater] = useState(!!properties.amenities?.black_water);
  const [greyWater, setGreyWater] = useState(!!properties.amenities?.grey_water);
  const [electricity, setElectricity] = useState(!!properties.amenities?.electricity_220v);
  const [hasToilet, setHasToilet] = useState(properties.amenities?.has_toilet ?? false);
  const [hasTrashBins, setHasTrashBins] = useState(properties.amenities?.has_trash_bins ?? false);
  const [isFree, setIsFree] = useState(properties.amenities?.is_free ?? true);
  const [priceDescription, setPriceDescription] = useState(properties.amenities?.price_description ?? "");
  const [campingBehaviorAllowed, setCampingBehaviorAllowed] = useState(properties.amenities?.camping_behavior_allowed ?? true);
  const [travelInfo, setTravelInfo] = useState<SpotTravelInfo>({ ...EMPTY_TRAVEL_INFO, ...properties });
  const [ruleInformationKnown, setRuleInformationKnown] = useState(properties.amenities?.rule_information_known ?? false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setIsSubmitting(true);
    try {
      const clearanceRequired: ClearanceRequired = requires4x4 ? "high_4x4" : "standard";
      const updated = await updateSpot(properties.id, {
        ...travelInfo,
        ...(isStaff && (pointLatitude !== lat || pointLongitude !== lon) ? { coordinates: {latitude:pointLatitude,longitude:pointLongitude} } : {}),
        title,
        description: description.trim() || null,
        category,
        passability: {
          road_type: roadType,
          max_vehicle_length: isUnlimitedLength ? null : Number(maxVehicleLength) || null,
          max_vehicle_width: toNullableNumber(maxVehicleWidth),
          max_vehicle_height: toNullableNumber(maxVehicleHeight),
          max_vehicle_weight_kg: toNullableNumber(maxVehicleWeight),
          clearance_required: clearanceRequired,
          caravan_types_allowed: properties.passability?.caravan_types_allowed ?? [],
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
          gsm_signals: properties.amenities?.gsm_signals ?? {},
        },
      });
      onUpdated(updated);
    } catch (err) {
      setFormError(extractErrorMessage(err, "Nokta güncellenemedi."));
      setIsSubmitting(false);
    }
  }

  return (
    <Modal
      title="Noktayı Düzenle"
      onClose={onClose}
      maxWidth="xl"
      testId="edit-spot-modal"
      footer={
        <div className="flex items-center justify-between gap-3">
          {formError ? <p className="text-xs text-warning-rust">{formError}</p> : <span />}
          <Button type="submit" form="edit-spot-form" variant="primary" disabled={isSubmitting}>
            {isSubmitting ? "Kaydediliyor…" : "Değişiklikleri Kaydet"}
          </Button>
        </div>
      }
    >
      <form id="edit-spot-form" onSubmit={handleSubmit} className="flex flex-col">
        <Section>
          <div className="flex items-center gap-2 rounded-md border border-border-light bg-surface-secondary px-3 py-2.5">
            <MapPin size={16} className="shrink-0 text-text-secondary" />
            <span className="text-sm text-text-primary">Konum</span>
            <span className="ml-auto font-mono text-xs text-text-secondary">
              {lat.toFixed(5)}, {lon.toFixed(5)}
            </span>
          </div>
          {isStaff ? <div className="mt-3 grid grid-cols-2 gap-3"><Field label="Düzeltilmiş enlem"><input required type="number" step="any" min={-90} max={90} value={pointLatitude} onChange={e=>setPointLatitude(Number(e.target.value))} className={INPUT_CLASS}/></Field><Field label="Düzeltilmiş boylam"><input required type="number" step="any" min={-180} max={180} value={pointLongitude} onChange={e=>setPointLongitude(Number(e.target.value))} className={INPUT_CLASS}/></Field><p className="col-span-2 text-xs text-text-secondary">Konum düzeltmesi moderatör yetkisi gerektirir ve geçmişe kaydedilir.</p></div> : <p className="mt-1.5 text-xs text-text-secondary">Konum hatası için içerik bildirimi gönderebilirsiniz.</p>}
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
      </form>
    </Modal>
  );
}
