/**
 * Genel "göreli zaman" biçimlendiricisi (ör. spot `updated_at`). Backend'deki
 * `field_freshness.relative_tr` ile aynı kademeleri kullanır ama fabrikasyon
 * bir "alan güncelliği" iddiası TAŞIMAZ - yalnızca kaydın en son ne zaman
 * değiştiğini nötr biçimde söyler (ayrıntılı alan bazlı güncellik için bkz.
 * `FieldFreshnessSection` / `field-freshness` endpoint'i).
 */
export function relativeTimeTr(iso: string, now: number = Date.now()): string {
  const days = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 86_400_000));
  if (days <= 0) return "bugün güncellendi";
  if (days === 1) return "dün güncellendi";
  if (days < 7) return `${days} gün önce güncellendi`;
  if (days < 30) return `${Math.floor(days / 7)} hafta önce güncellendi`;
  if (days < 365) return `${Math.floor(days / 30)} ay önce güncellendi`;
  return `${Math.floor(days / 365)} yıl önce güncellendi`;
}
