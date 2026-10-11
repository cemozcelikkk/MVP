/**
 * Hizmet noktası detayı (restoran / sağlık / WC / duş) - Keşif Panelinin
 * detay modu, kamp noktası detayının (`SpotDetailSidebar`) hafif karşılığı.
 *
 * Gruba göre farklı içerik ve sıralama:
 *  - Yeme & İçme: yol tarifi, 1-5 yıldız + yorum (kullanıcı başına tek aktif
 *    değerlendirme), "hâlâ açık" teyidi. Kamp alanlarının 7 boyutlu sisteminden ayrıdır.
 *  - Sağlık: tür, konum, yol tarifi ve "hâlâ hizmet veriyor" teyidi - yıldız/yorum
 *    bileşeni HİÇ render edilmez (yalnızca teyit sayısı; puan değildir).
 *  - WC / duş: EN ÜSTTE ücret + kullanılabilirlik + son güncelleme; herkes güncelleyebilir.
 * Tüm türlerde: moderatör onayı rozeti, hatalı konum / kapanmış / mükerrer kayıt bildirimi.
 */
import { ArrowLeft, BadgeCheck, CheckCircle2, Clock, Flag, Info, Navigation, Phone, ShieldAlert, Star, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import {
  confirmServicePoint,
  createServicePointReview,
  deleteServicePoint,
  deleteServicePointReview,
  fetchMyServicePointReview,
  fetchServicePointReviews,
  reportServicePoint,
  updateServicePointReview,
  updateServicePointStatus,
  verifyServicePoint,
  type AvailabilityStatus,
  type FeeStatus,
  type ServicePointFeature,
  type ServicePointReportReason,
  type ServicePointReview,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { googleMapsDirectionsUrl } from "../lib/format";
import {
  AVAILABILITY_LABEL,
  FEE_LABEL,
  REPORT_REASON_LABEL,
  SERVICE_CATEGORY_LABEL,
  SERVICE_GROUP_LABEL,
  STATUS_STALE_DAYS,
  serviceIconSvg,
  servicePinColors,
  servicePointTitle,
} from "../lib/servicePoints";
import { useAuthStore } from "../store/useAuthStore";
import { useMapDataStore } from "../store/useMapDataStore";
import { Field, INPUT_CLASS, SegmentedGroup } from "./FormControls";
import Button from "./ui/Button";
import { Section } from "./ui/Section";

interface Props {
  point: ServicePointFeature;
  onClose: () => void;
  onUpdated: (feature: ServicePointFeature) => void;
}

function daysSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000));
}

function agoText(iso: string): string {
  const days = daysSince(iso);
  if (days === 0) return "bugün";
  if (days === 1) return "dün";
  return `${days} gün önce`;
}

function checkedText(iso: string): string {
  return `Son güncelleme: ${agoText(iso)}`;
}

export default function ServicePointDetail({ point, onClose, onUpdated }: Props) {
  const { properties } = point;
  const [lon, lat] = point.geometry.coordinates;
  const authUser = useAuthStore((s) => s.user);
  const isModerator = authUser?.role === "moderator" || authUser?.role === "admin";
  // Harici (OSM) nokta henüz KaravanTR kaydı değil - silinecek/düzenlenecek bir kayıt yok.
  const canManage =
    !properties.is_external &&
    !!authUser &&
    (authUser.id === properties.created_by || authUser.role === "moderator" || authUser.role === "admin");
  const osmUrl = typeof properties.extra.osm_url === "string" ? properties.extra.osm_url : null;
  const colors = servicePinColors(properties.category);
  const phone = typeof properties.extra.phone === "string" ? properties.extra.phone : null;
  const openingHours = typeof properties.extra.opening_hours === "string" ? properties.extra.opening_hours : null;
  // Puan/durum değişince liste ve pin verisi de tazelensin (harita aynı bbox'ı yeniden sorgular).
  const handleUpdated = (feature: ServicePointFeature) => {
    onUpdated(feature);
    useMapDataStore.getState().retry();
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto" data-testid="service-point-detail">
      <button
        type="button"
        onClick={onClose}
        data-testid="back-to-list"
        className="flex min-h-touch shrink-0 items-center gap-1.5 border-b border-border-light px-4 text-sm font-medium text-text-secondary transition-colors hover:text-text-primary"
      >
        <ArrowLeft size={16} />
        Listeye Dön
      </button>

      <Section>
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-full [&_svg]:h-6 [&_svg]:w-6"
            style={{ backgroundColor: colors.fill }}
            dangerouslySetInnerHTML={{ __html: serviceIconSvg(properties.category) }}
          />
          <div className="min-w-0">
            <h2 className="font-display text-[26px] font-medium leading-[1.1] text-text-primary">
              {servicePointTitle(properties)}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="rounded-md bg-surface-secondary px-2 py-0.5 text-xs font-semibold text-text-secondary">
                {SERVICE_CATEGORY_LABEL[properties.category]}
              </span>
              <span className="text-xs text-text-secondary">{SERVICE_GROUP_LABEL[properties.group]}</span>
              {properties.is_verified ? (
                <span className="flex items-center gap-1 text-xs font-semibold text-accent-green" data-testid="verified-badge">
                  <BadgeCheck size={14} />
                  Moderatör onaylı
                </span>
              ) : null}
              {properties.group === "food" ? (
                properties.average_rating != null ? (
                  <span className="flex items-center gap-1 text-sm font-semibold text-accent-brass">
                    <Star size={13} fill="currentColor" />
                    {properties.average_rating.toFixed(1)}
                    <span className="font-normal text-text-secondary">({properties.review_count})</span>
                  </span>
                ) : (
                  <span className="text-xs text-text-secondary">Henüz puan yok</span>
                )
              ) : null}
            </div>
          </div>
        </div>
        <p className="mt-2 font-mono text-xs text-text-secondary">
          {lat.toFixed(5)}, {lon.toFixed(5)}
        </p>
        {properties.source === "OVERPASS_OSM" ? (
          <div className="mt-3 flex items-start gap-1.5 rounded-md border border-border-light px-3 py-2 text-xs text-text-secondary" data-testid="osm-notice">
            <Info size={14} className="mt-px shrink-0" />
            <span>
              {properties.is_external
                ? "Bu nokta OpenStreetMap harita verisinden geliyor ve KaravanTR kullanıcılarınca doğrulanmadı. Açık ya da kullanılabilir olduğu kesin değildir; yola çıkmadan teyit edin."
                : "Konum ve ad OpenStreetMap verisinden; durum bilgileri KaravanTR kullanıcılarının katkısıdır."}{" "}
              {osmUrl ? (
                <a href={osmUrl} target="_blank" rel="noreferrer" className="underline">
                  © OpenStreetMap katkıcıları
                </a>
              ) : null}
            </span>
          </div>
        ) : null}
      </Section>

      {/* WC/duş: sahada en çok sorulan bilgi (ücret, çalışıyor mu, ne zaman bakıldı) en üstte. */}
      {properties.group === "basic" ? <BasicStatusSection point={point} onUpdated={handleUpdated} /> : null}

      <Section>
        <a
          href={googleMapsDirectionsUrl(lat, lon)}
          target="_blank"
          rel="noreferrer"
          className="flex min-h-touch w-full items-center justify-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-4 text-sm font-medium text-text-primary transition-colors hover:bg-surface-secondary"
        >
          <Navigation size={15} />
          Yol Tarifi Al
        </a>
        {phone ? (
          <a
            href={`tel:${phone.replace(/\s+/g, "")}`}
            className="mt-2 flex min-h-touch w-full items-center justify-center gap-1.5 rounded-md border border-border-light px-4 text-sm font-medium text-text-primary transition-colors hover:bg-surface-secondary"
          >
            <Phone size={15} />
            {phone}
          </a>
        ) : null}
        {openingHours ? (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-text-secondary">
            <Clock size={13} />
            {openingHours}
          </p>
        ) : null}
        {properties.group === "health" ? (
          <p className="mt-3 flex items-start gap-1.5 rounded-md bg-warning-rust/10 px-3 py-2 text-xs text-text-primary">
            <ShieldAlert size={14} className="mt-px shrink-0 text-warning-rust" />
            Acil durumda 112'yi arayın. Çalışma durumu doğrulanmamış olabilir.
          </p>
        ) : null}
      </Section>

      {properties.group === "food" ? <FoodReviewsSection point={point} onUpdated={handleUpdated} /> : null}
      {/* WC/duşta durum güncellemesi zaten saha teyididir; diğerlerinde "hâlâ burada" teyidi. */}
      {properties.group !== "basic" ? <ConfirmSection point={point} onUpdated={handleUpdated} /> : null}

      <ReportSection pointId={properties.id} />

      {isModerator ? <ModeratorSection point={point} onUpdated={handleUpdated} /> : null}
      {canManage ? <DeleteSection pointId={properties.id} onDeleted={onClose} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// WC / duş: ücret + kullanılabilirlik + güncellik
// ---------------------------------------------------------------------------

const FEE_OPTIONS = (["free", "paid", "unknown"] as FeeStatus[]).map((value) => ({ value, label: FEE_LABEL[value] }));
const AVAILABILITY_OPTIONS = (["available", "unavailable", "unknown"] as AvailabilityStatus[]).map((value) => ({
  value,
  label: AVAILABILITY_LABEL[value],
  tone: value === "unavailable" ? ("danger" as const) : undefined,
}));

function BasicStatusSection({ point, onUpdated }: { point: ServicePointFeature; onUpdated: (f: ServicePointFeature) => void }) {
  const { properties } = point;
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const [isEditing, setIsEditing] = useState(false);
  const [fee, setFee] = useState<FeeStatus>(properties.fee_status);
  const [availability, setAvailability] = useState<AvailabilityStatus>(properties.availability_status);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isStale = !properties.status_checked_at || daysSince(properties.status_checked_at) > STATUS_STALE_DAYS;

  async function submit() {
    setIsSubmitting(true);
    setError(null);
    try {
      // Kullanıcı yalnızca "baktığı" alanları gönderir; ikisi de gönderilir çünkü form ikisini de gösteriyor.
      const updated = await updateServicePointStatus(properties.id, { fee_status: fee, availability_status: availability });
      setIsEditing(false);
      onUpdated(updated);
    } catch (err) {
      setError(extractErrorMessage(err, "Durum güncellenemedi."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Section title="Durum">
      <div className="grid grid-cols-2 gap-2">
        <StatusTile label="Ücret" value={FEE_LABEL[properties.fee_status]} tone={properties.fee_status === "unknown" ? "muted" : "default"} />
        <StatusTile
          label="Kullanım"
          value={AVAILABILITY_LABEL[properties.availability_status]}
          tone={
            properties.availability_status === "unavailable"
              ? "danger"
              : properties.availability_status === "available"
                ? "positive"
                : "muted"
          }
        />
      </div>
      <p className={`mt-2 text-xs ${isStale ? "text-warning-rust" : "text-text-secondary"}`}>
        {properties.status_checked_at
          ? checkedText(properties.status_checked_at)
          : properties.source === "OVERPASS_OSM" && properties.fee_status !== "unknown"
            ? "Ücret bilgisi harita verisinden; henüz sahada doğrulanmadı"
            : "Henüz sahada doğrulanmadı"}
        {properties.status_checked_at && isStale ? " - bilgi güncelliğini yitirmiş olabilir" : ""}
      </p>

      {isEditing ? (
        <div className="mt-3 flex flex-col gap-3 rounded-md border border-border-light p-3">
          <Field label="Ücret">
            <SegmentedGroup options={FEE_OPTIONS} value={fee} onChange={setFee} />
          </Field>
          <Field label="Şu an kullanılabilir mi?">
            <SegmentedGroup options={AVAILABILITY_OPTIONS} value={availability} onChange={setAvailability} />
          </Field>
          {error ? <p className="text-xs text-warning-rust">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setIsEditing(false)}>
              Vazgeç
            </Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={isSubmitting}>
              {isSubmitting ? "Kaydediliyor…" : "Doğrula ve Kaydet"}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="secondary"
          className="mt-3 w-full"
          data-testid="update-status-button"
          onClick={() => (isAuthenticated ? setIsEditing(true) : openAuthModal())}
        >
          Buradayım, durumu güncelle
        </Button>
      )}
    </Section>
  );
}

function StatusTile({ label, value, tone }: { label: string; value: string; tone: "default" | "muted" | "positive" | "danger" }) {
  const toneClass =
    tone === "danger"
      ? "text-warning-rust"
      : tone === "positive"
        ? "text-accent-green"
        : tone === "muted"
          ? "text-text-secondary"
          : "text-text-primary";
  return (
    <div className="rounded-md border border-border-light px-3 py-2">
      <span className="block text-[11px] font-medium uppercase tracking-wide text-text-secondary">{label}</span>
      <span className={`block text-sm font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Yeme & İçme: yıldız + yorum
// ---------------------------------------------------------------------------

function StarPicker({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="Puan">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n} yıldız`}
          onClick={() => onChange(n)}
          className="flex h-11 w-11 items-center justify-center rounded-md text-accent-brass transition-colors hover:bg-accent-brass/10"
        >
          <Star size={24} fill={n <= value ? "currentColor" : "none"} strokeWidth={1.6} />
        </button>
      ))}
    </div>
  );
}

function StarsInline({ rating }: { rating: number }) {
  return (
    <span className="flex text-accent-brass" aria-label={`${rating} / 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} size={12} fill={n <= rating ? "currentColor" : "none"} />
      ))}
    </span>
  );
}

function FoodReviewsSection({ point, onUpdated }: { point: ServicePointFeature; onUpdated: (f: ServicePointFeature) => void }) {
  const pointId = point.properties.id;
  const authUser = useAuthStore((s) => s.user);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const [reviews, setReviews] = useState<ServicePointReview[] | null>(null);
  const [mine, setMine] = useState<ServicePointReview | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchServicePointReviews(pointId)
      .then((rows) => !cancelled && setReviews(rows))
      .catch(() => !cancelled && setReviews([]));
    if (authUser) {
      fetchMyServicePointReview(pointId)
        .then((row) => !cancelled && setMine(row))
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [pointId, authUser, version]);

  function startEditing() {
    if (!authUser) {
      openAuthModal();
      return;
    }
    setRating(mine?.rating ?? 0);
    setComment(mine?.comment ?? "");
    setError(null);
    setIsEditing(true);
  }

  function refreshSummary(nextReviews: number, delta: (avg: number | null, n: number) => number | null) {
    // Özet backend'de hesaplanır; panelin başlığındaki puanı yeniden çekmeden tutarlı tutmak için yereldeki listeden türet.
    onUpdated({
      ...point,
      properties: { ...point.properties, review_count: nextReviews, average_rating: delta(point.properties.average_rating, nextReviews) },
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (rating < 1) {
      setError("Lütfen 1-5 arası bir yıldız seçin.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const saved = mine
        ? await updateServicePointReview(pointId, mine.id, { rating, comment: comment.trim() })
        : await createServicePointReview(pointId, { rating, comment: comment.trim() || null });
      const others = (reviews ?? []).filter((r) => r.id !== saved.id);
      const all = [saved, ...others];
      setMine(saved);
      setReviews(all);
      setIsEditing(false);
      refreshSummary(all.length, () => Math.round((all.reduce((sum, r) => sum + r.rating, 0) / all.length) * 100) / 100);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(extractErrorMessage(err, "Değerlendirme kaydedilemedi."));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function remove() {
    if (!mine) return;
    setIsSubmitting(true);
    try {
      await deleteServicePointReview(pointId, mine.id);
      const rest = (reviews ?? []).filter((r) => r.id !== mine.id);
      setMine(null);
      setReviews(rest);
      setIsEditing(false);
      refreshSummary(rest.length, () =>
        rest.length ? Math.round((rest.reduce((sum, r) => sum + r.rating, 0) / rest.length) * 100) / 100 : null,
      );
    } catch (err) {
      setError(extractErrorMessage(err, "Değerlendirme silinemedi."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Section title="Değerlendirmeler">
      {isEditing ? (
        <form onSubmit={submit} className="mb-4 flex flex-col gap-3 rounded-md border border-border-light p-3">
          <StarPicker value={rating} onChange={setRating} />
          <textarea
            rows={3}
            maxLength={2000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Yorumunuz (isteğe bağlı)"
            className={`${INPUT_CLASS} resize-none`}
          />
          {error ? <p className="text-xs text-warning-rust">{error}</p> : null}
          <div className="flex items-center justify-between gap-2">
            {mine ? (
              <Button variant="ghost" size="sm" onClick={remove} disabled={isSubmitting}>
                Değerlendirmemi sil
              </Button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => setIsEditing(false)}>
                Vazgeç
              </Button>
              <Button type="submit" variant="primary" size="sm" disabled={isSubmitting}>
                {isSubmitting ? "Kaydediliyor…" : "Kaydet"}
              </Button>
            </div>
          </div>
        </form>
      ) : (
        <Button variant="secondary" className="mb-4 w-full" onClick={startEditing} data-testid="rate-service-point">
          <Star size={15} />
          {mine ? "Değerlendirmemi düzenle" : "Puan ver / yorum yaz"}
        </Button>
      )}

      {reviews === null ? (
        <p className="text-xs text-text-secondary">Yükleniyor…</p>
      ) : reviews.length === 0 ? (
        <p className="text-xs text-text-secondary">Henüz değerlendirme yok. İlk puanı siz verin.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {reviews.map((review) => (
            <li key={review.id} className="border-b border-border-light/70 pb-3 last:border-0">
              <div className="flex items-center gap-2">
                <StarsInline rating={review.rating} />
                <span className="text-[11px] text-text-secondary">
                  {new Date(review.created_at).toLocaleDateString("tr-TR")}
                  {authUser?.id === review.user_id ? " · sizin" : ""}
                </span>
              </div>
              {review.comment ? <p className="mt-1 whitespace-pre-line text-sm text-text-primary">{review.comment}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Sorun bildir
// ---------------------------------------------------------------------------

const REASONS = Object.entries(REPORT_REASON_LABEL) as [ServicePointReportReason, string][];

function ReportSection({ pointId }: { pointId: string }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const [isOpen, setIsOpen] = useState(false);
  const [reason, setReason] = useState<ServicePointReportReason | null>(null);
  const [description, setDescription] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!reason) return;
    setState("sending");
    setError(null);
    try {
      await reportServicePoint(pointId, { reason, description: description.trim() || null });
      setState("sent");
      setIsOpen(false);
    } catch (err) {
      setError(extractErrorMessage(err, "Bildirim gönderilemedi."));
      setState("idle");
    }
  }

  return (
    <Section>
      {state === "sent" ? (
        <p className="text-xs text-accent-green">Teşekkürler - bildiriminiz moderatörlere iletildi.</p>
      ) : isOpen ? (
        <div className="flex flex-col gap-3 rounded-md border border-border-light p-3">
          <span className="text-sm font-semibold text-text-primary">Sorun nedir?</span>
          <div className="flex flex-wrap gap-1.5">
            {REASONS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={reason === value}
                onClick={() => setReason(value)}
                className={[
                  "min-h-touch rounded-md border px-3 text-sm font-medium transition-colors",
                  reason === value
                    ? "border-warning-rust bg-warning-rust/10 text-warning-rust"
                    : "border-border-light text-text-secondary hover:text-text-primary",
                ].join(" ")}
              >
                {label}
              </button>
            ))}
          </div>
          <textarea
            rows={2}
            maxLength={1000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Ek açıklama (isteğe bağlı) - ör. doğru konum, mükerrer kaydın adı"
            className={`${INPUT_CLASS} resize-none`}
          />
          {error ? <p className="text-xs text-warning-rust">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setIsOpen(false)}>
              Vazgeç
            </Button>
            <Button variant="danger" size="sm" onClick={submit} disabled={!reason || state === "sending"}>
              {state === "sending" ? "Gönderiliyor…" : "Bildir"}
            </Button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          data-testid="report-service-point"
          onClick={() => (isAuthenticated ? setIsOpen(true) : openAuthModal())}
          className="flex min-h-touch items-center gap-1.5 text-xs font-medium text-text-secondary transition-colors hover:text-warning-rust"
        >
          <Flag size={13} />
          Hatalı konum, kapanmış veya mükerrer kayıt bildir
        </button>
      )}
    </Section>
  );
}

function DeleteSection({ pointId, onDeleted }: { pointId: string; onDeleted: () => void }) {
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    try {
      await deleteServicePoint(pointId);
      useMapDataStore.getState().retry();
      onDeleted();
    } catch (err) {
      setError(extractErrorMessage(err, "Nokta silinemedi."));
    }
  }

  return (
    <Section>
      {error ? <p className="mb-2 text-xs text-warning-rust">{error}</p> : null}
      {isConfirming ? (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-text-secondary">Bu nokta haritadan kaldırılsın mı?</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setIsConfirming(false)}>
              Vazgeç
            </Button>
            <Button variant="danger-solid" size="sm" onClick={remove}>
              Evet, Sil
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="danger" size="sm" onClick={() => setIsConfirming(true)}>
          <Trash2 size={14} />
          Noktayı Sil
        </Button>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Topluluk teyidi ("hâlâ burada") - yeme & içme ve sağlık
// ---------------------------------------------------------------------------

function ConfirmSection({ point, onUpdated }: { point: ServicePointFeature; onUpdated: (f: ServicePointFeature) => void }) {
  const { properties } = point;
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthModal = useAuthStore((s) => s.openAuthModal);
  const [state, setState] = useState<"idle" | "sending" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const question = properties.group === "health" ? "Burası hâlâ hizmet veriyor mu?" : "Burası hâlâ açık mı?";
  const label = properties.group === "health" ? "Evet, hizmet veriyor" : "Evet, hâlâ açık";

  async function confirm() {
    if (!isAuthenticated) {
      openAuthModal();
      return;
    }
    setState("sending");
    setError(null);
    try {
      onUpdated(await confirmServicePoint(properties.id));
      setState("done");
    } catch (err) {
      setError(extractErrorMessage(err, "Teyit gönderilemedi."));
      setState("idle");
    }
  }

  return (
    <Section title="Güncellik">
      <p className="text-sm text-text-primary" data-testid="confirmation-summary">
        {properties.confirmation_count > 0 && properties.last_confirmed_at
          ? `${properties.confirmation_count} kişi teyit etti · son teyit ${agoText(properties.last_confirmed_at)}`
          : "Henüz kimse yerinde teyit etmedi."}
      </p>
      {error ? <p className="mt-1 text-xs text-warning-rust">{error}</p> : null}
      {state === "done" ? (
        <p className="mt-3 flex items-center gap-1.5 text-sm font-medium text-accent-green">
          <CheckCircle2 size={16} /> Teşekkürler, teyidiniz kaydedildi.
        </p>
      ) : (
        <>
          <p className="mt-3 text-xs text-text-secondary">{question} Yakınındaysanız teyit edin.</p>
          <Button variant="secondary" className="mt-2 w-full" onClick={confirm} disabled={state === "sending"} data-testid="confirm-service-point">
            <CheckCircle2 size={15} />
            {state === "sending" ? "Gönderiliyor…" : label}
          </Button>
        </>
      )}
    </Section>
  );
}

function ModeratorSection({ point, onUpdated }: { point: ServicePointFeature; onUpdated: (f: ServicePointFeature) => void }) {
  const { properties } = point;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      onUpdated(await verifyServicePoint(properties.id, !properties.is_verified));
    } catch (err) {
      setError(extractErrorMessage(err, "İşlem başarısız."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Moderasyon">
      {error ? <p className="mb-2 text-xs text-warning-rust">{error}</p> : null}
      <Button variant="secondary" size="sm" onClick={toggle} disabled={busy} data-testid="toggle-verify">
        <BadgeCheck size={14} />
        {properties.is_verified ? "Onayı kaldır" : "Noktayı onayla"}
      </Button>
    </Section>
  );
}
