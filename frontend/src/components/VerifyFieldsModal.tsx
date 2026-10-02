/**
 * "Saha bilgisini doğrula" - ziyaret sonrası kısa doğrulama formu.
 *
 * İlk ekranda en fazla 4 kısa soru (yol, geceleme, su, elektrik); gri/siyah su
 * "Diğer bilgileri de doğrula" altında. Her soruda varsayılan "Bilmiyorum /
 * kontrol etmedim" - kimse bilmediği bir konuda cevap vermeye zorlanmaz ve o
 * alan gönderilmez/sayılmaz. Göndermeden önce topluluğa NELERİN görüneceği
 * açıkça listelenir.
 *
 * Metin bilinçli olarak "kesin doğrulandı" iddiasında bulunmaz: doğrulama
 * check-in kaydına dayanır, o da GPS sahteciliğine karşı kusursuz kanıt değildir.
 */
import { type FormEvent, useState } from "react";
import {
  submitVerifications,
  type MyVerifications,
  type SpotFieldFreshness,
  type VerifiableField,
  type VerificationAnswer,
} from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { SegmentedGroup } from "./FormControls";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

const UNKNOWN_OPTION = { value: "unknown" as VerificationAnswer, label: "Bilmiyorum / kontrol etmedim" };

interface Question {
  field: VerifiableField;
  question: string;
  options: { value: VerificationAnswer; label: string }[];
}

const PRIMARY_QUESTIONS: Question[] = [
  {
    field: "road_access",
    question: "Noktaya araçla erişim nasıldı?",
    options: [
      { value: "passable", label: "Geçilebilir" },
      { value: "difficult", label: "Zor geçiliyor" },
      { value: "impassable", label: "Geçilemiyor" },
      UNKNOWN_OPTION,
    ],
  },
  {
    field: "overnight",
    question: "Burada geceleme mümkün müydü?",
    options: [
      { value: "allowed", label: "Mümkün" },
      { value: "not_allowed", label: "Mümkün değil" },
      UNKNOWN_OPTION,
    ],
  },
  {
    field: "fresh_water",
    question: "Tatlı su çalışıyor muydu?",
    options: [
      { value: "working", label: "Çalışıyor" },
      { value: "not_working", label: "Çalışmıyor" },
      UNKNOWN_OPTION,
    ],
  },
  {
    field: "electricity",
    question: "Elektrik kullanılabiliyor muydu?",
    options: [
      { value: "working", label: "Çalışıyor" },
      { value: "not_working", label: "Çalışmıyor" },
      UNKNOWN_OPTION,
    ],
  },
];

const SECONDARY_QUESTIONS: Question[] = [
  { field: "toilet", question: "Tuvalet kullanılabiliyor muydu?", options: [{ value: "working", label: "Kullanılabiliyor" }, { value: "not_working", label: "Kullanılamıyor" }, UNKNOWN_OPTION] },
  { field: "trash_bins", question: "Çöp kutusu / atık alanı kullanılabiliyor muydu?", options: [{ value: "working", label: "Kullanılabiliyor" }, { value: "not_working", label: "Kullanılamıyor" }, UNKNOWN_OPTION] },
  { field: "price", question: "Alan ücretsiz miydi?", options: [{ value: "free", label: "Ücretsiz" }, { value: "paid", label: "Ücretli" }, UNKNOWN_OPTION] },
  { field: "camping_behavior", question: "Tente, masa/sandalye kullanımına izin veriliyor muydu?", options: [{ value: "allowed", label: "İzin veriliyor" }, { value: "not_allowed", label: "İzin verilmiyor" }, UNKNOWN_OPTION] },
  {
    field: "grey_water",
    question: "Gri su boşaltma kullanılabiliyor muydu?",
    options: [
      { value: "working", label: "Kullanılabiliyor" },
      { value: "not_working", label: "Kullanılamıyor" },
      UNKNOWN_OPTION,
    ],
  },
  {
    field: "black_water",
    question: "Siyah su (kaset) boşaltma kullanılabiliyor muydu?",
    options: [
      { value: "working", label: "Kullanılabiliyor" },
      { value: "not_working", label: "Kullanılamıyor" },
      UNKNOWN_OPTION,
    ],
  },
];

const ALL_QUESTIONS = [...PRIMARY_QUESTIONS, ...SECONDARY_QUESTIONS];

interface Props {
  spotId: string;
  mine: MyVerifications;
  onClose: () => void;
  onSubmitted: (freshness: SpotFieldFreshness) => void;
}

export default function VerifyFieldsModal({ spotId, mine, onClose, onSubmitted }: Props) {
  const [answers, setAnswers] = useState<Partial<Record<VerifiableField, VerificationAnswer>>>(
    () => ({ ...mine.current_answers }),
  );
  const [showSecondary, setShowSecondary] = useState(
    // Kullanıcı daha önce gri/siyah su cevabı verdiyse o bölüm baştan açık gelsin.
    () => SECONDARY_QUESTIONS.some((q) => mine.current_answers[q.field] !== undefined),
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const answerOf = (field: VerifiableField): VerificationAnswer => answers[field] ?? "unknown";

  // Topluluğa görünecek cevaplar = "bilmiyorum" OLMAYANLAR (bkz. önizleme + gönderim).
  const shared = ALL_QUESTIONS.flatMap((q) => {
    const value = answerOf(q.field);
    if (value === "unknown") return [];
    const label = q.options.find((o) => o.value === value)?.label ?? value;
    return [{ field: q.field, question: q.question, label }];
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (shared.length === 0) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const payload = Object.fromEntries(shared.map((s) => [s.field, answerOf(s.field)]));
      const response = await submitVerifications(spotId, payload);
      onSubmitted(response.freshness);
    } catch (err) {
      setError(extractErrorMessage(err, "Doğrulama gönderilemedi."));
      setIsSubmitting(false);
    }
  }

  const renderQuestion = (q: Question) => (
    <div key={q.field}>
      <p className="mb-1.5 text-sm text-text-primary">{q.question}</p>
      <SegmentedGroup
        options={q.options}
        value={answerOf(q.field)}
        onChange={(value) => setAnswers((prev) => ({ ...prev, [q.field]: value }))}
      />
    </div>
  );

  return (
    <Modal
      title="Saha Bilgisini Doğrula"
      onClose={onClose}
      maxWidth="lg"
      testId="verify-fields-modal"
      footer={
        <Button
          type="submit"
          form="verify-fields-form"
          variant="primary"
          className="w-full"
          disabled={isSubmitting || shared.length === 0}
        >
          {isSubmitting ? "Gönderiliyor…" : `Doğrulamayı Gönder (${shared.length})`}
        </Button>
      }
    >
      <p className="mb-4 text-sm leading-relaxed text-text-secondary">
        Sadece bu ziyarette gördüklerinizi işaretleyin. Emin değilseniz &quot;Bilmiyorum&quot; bırakın - o bilgi
        gönderilmez.
      </p>

      <form id="verify-fields-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        {PRIMARY_QUESTIONS.map(renderQuestion)}

        <button
          type="button"
          onClick={() => setShowSecondary((v) => !v)}
          aria-expanded={showSecondary}
          className="self-start text-sm font-medium text-accent-green transition-colors hover:text-accent-green-hover"
        >
          {showSecondary ? "− Diğer bilgileri gizle" : "+ Diğer bilgileri de doğrula"}
        </button>
        {showSecondary ? SECONDARY_QUESTIONS.map(renderQuestion) : null}

        {/* Gönderim öncesi: topluluğa hangi cevaplar görünecek */}
        <div className="rounded-md border border-border-light bg-surface-secondary p-3" data-testid="verify-preview">
          <p className="mb-1.5 text-xs font-semibold text-text-secondary">
            Topluluğa görünecek cevaplarınız
          </p>
          {shared.length === 0 ? (
            <p className="text-sm text-text-secondary">Henüz bir cevap seçmediniz - hiçbir şey paylaşılmayacak.</p>
          ) : (
            <ul className="mb-2 flex flex-col gap-0.5">
              {shared.map((s) => (
                <li key={s.field} className="text-sm text-text-primary">
                  {s.question} <span className="font-medium text-accent-brass">→ {s.label}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs leading-relaxed text-text-secondary">
            Cevaplarınız kişi adı olmadan, bağımsız katılımcı sayısına eklenir. Noktanın kalıcı bilgisi değişmez. Bu
            doğrulama check-in kaydınıza dayanır ve kesin bir kanıt değildir. Aynı bilgiyi tekrar göndermek sayıyı
            artırmaz.
          </p>
        </div>

        {error ? <p className="text-xs text-warning-rust">{error}</p> : null}
      </form>
    </Modal>
  );
}
