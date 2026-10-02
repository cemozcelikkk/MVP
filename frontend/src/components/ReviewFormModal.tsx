/**
 * Değerlendirme ekleme/düzenleme modalı. `editingReview` verilirse PATCH,
 * verilmezse POST çağrılır - aynı form, iki mod.
 *
 * Genel puan ve yorum metni mevcut davranışı korur (zorunlu/opsiyonel aynı);
 * yedi saha ölçütü TAMAMEN opsiyoneldir ve her biri ayrı ayrı
 * "Değerlendirmedim"e döndürülebilir (bkz. `RatingInput`'taki `allowClear`).
 */
import { type FormEvent, useState } from "react";
import {
  createReview,
  updateReview,
  type DimensionRatings,
  type Review,
  type ReviewCreatePayload,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { formatDecimalTr } from "../lib/format";
import { VEHICLE_TYPE_LABEL } from "../lib/vehicleLabels";
import { useVehicleProfileStore } from "../store/useVehicleProfileStore";
import { Field, INPUT_CLASS, RatingInput } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import { Section } from "./ui/Section";

// Sıra kasıtlı: ilk üçü ("en yararlı 3") nokta detayındaki öne çıkan
// gösterimle birebir aynı - bkz. `SpotReviewsSection`.
const DIMENSION_FIELDS: { key: keyof DimensionRatings; label: string }[] = [
  { key: "safety", label: "Geceleme Güvenliği" },
  { key: "quietness", label: "Sessizlik" },
  { key: "road_access", label: "Yol Erişimi" },
  { key: "ground_suitability", label: "Zemin Uygunluğu" },
  { key: "cleanliness", label: "Temizlik" },
  { key: "view", label: "Manzara" },
  { key: "signal", label: "İnternet / Telefon Çekimi" },
];

const EMPTY_DIMENSIONS: DimensionRatings = {
  safety: null,
  quietness: null,
  road_access: null,
  ground_suitability: null,
  cleanliness: null,
  view: null,
  signal: null,
};

interface Props {
  spotId: string;
  /** `null` = yeni değerlendirme; dolu = bu yorumu düzenle. */
  editingReview: Review | null;
  onClose: () => void;
  onSaved: (review: Review) => void;
}

export default function ReviewFormModal({ spotId, editingReview, onClose, onSaved }: Props) {
  const activeVehicle = useVehicleProfileStore((s) => s.profiles.find((p) => p.is_active) ?? null);
  const openVehicleModal = useVehicleProfileStore((s) => s.openModal);

  const [rating, setRating] = useState(editingReview?.rating ?? 5);
  const [comment, setComment] = useState(editingReview?.comment ?? "");
  const [dimensions, setDimensions] = useState<DimensionRatings>(
    editingReview?.dimension_ratings ?? EMPTY_DIMENSIONS,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function setDimension(key: keyof DimensionRatings, value: number | null) {
    setDimensions((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setIsSubmitting(true);
    try {
      const payload: ReviewCreatePayload = {
        rating,
        comment: comment.trim() || null,
        dimension_ratings: dimensions,
      };
      const saved = editingReview
        ? await updateReview(spotId, editingReview.id, payload)
        : await createReview(spotId, payload);
      onSaved(saved);
    } catch (err) {
      setFormError(extractErrorMessage(err, "Değerlendirme kaydedilemedi."));
      setIsSubmitting(false);
    }
  }

  return (
    <Modal
      title={editingReview ? "Değerlendirmeyi Düzenle" : "Değerlendirme Yaz"}
      onClose={onClose}
      maxWidth="lg"
      testId="review-form-modal"
      footer={
        <div className="flex items-center justify-between gap-3">
          {formError ? <p className="text-xs text-warning-rust">{formError}</p> : <span />}
          <Button type="submit" form="review-form" variant="primary" disabled={isSubmitting}>
            {isSubmitting ? "Kaydediliyor…" : editingReview ? "Değişiklikleri Kaydet" : "Kaydet"}
          </Button>
        </div>
      }
    >
      <form id="review-form" onSubmit={handleSubmit} className="flex flex-col">
        {/* Sistemin ekleyeceği araç bilgisi - açık, zorlayıcı olmayan bildirim. */}
        <Section>
          <div className="rounded-md border border-border-light bg-surface-secondary p-3">
            {activeVehicle ? (
              <p className="text-sm leading-relaxed text-text-secondary">
                Bu değerlendirmeye{" "}
                <span className="font-medium text-text-primary">
                  {VEHICLE_TYPE_LABEL[activeVehicle.vehicle_type]} · {formatDecimalTr(activeVehicle.length_m)} m
                </span>{" "}
                bilgisi eklenecek.
              </p>
            ) : (
              <p className="text-sm leading-relaxed text-text-secondary">
                Aracınız hakkında bilgi eklenmeyecek.{" "}
                <button
                  type="button"
                  onClick={() => openVehicleModal({ startInAddMode: true })}
                  className="font-medium text-accent-green underline underline-offset-2 transition-colors hover:text-accent-green-hover"
                >
                  Araç profili eklemek ister misiniz? (opsiyonel)
                </button>
              </p>
            )}
          </div>
        </Section>

        <Section>
          <div className="flex flex-col gap-4">
            <RatingInput label="Genel Puan" value={rating} onChange={(v) => setRating(v ?? rating)} allowClear={false} />
            <Field label="Yorum">
              <textarea
                rows={4}
                maxLength={2000}
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="Bu nokta hakkındaki deneyiminizi paylaşın (opsiyonel)"
                className={`${INPUT_CLASS} resize-none`}
              />
            </Field>
          </div>
        </Section>

        <Section title="Saha Değerlendirmesi" action={<span className="text-xs text-text-secondary">bilmediğinizi boş bırakın</span>}>
          <div className="flex flex-col gap-3">
            {DIMENSION_FIELDS.map(({ key, label }) => (
              <RatingInput key={key} label={label} value={dimensions[key]} onChange={(value) => setDimension(key, value)} />
            ))}
          </div>
        </Section>
      </form>
    </Modal>
  );
}
