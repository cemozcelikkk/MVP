/** API hata gövdelerinden kullanıcıya gösterilebilir mesaj çıkarma. */
import axios from "axios";

/**
 * Pydantic v2'nin `loc` alanındaki teknik alan adlarının Türkçe karşılığı -
 * yalnızca kullanıcı formlarında GERÇEKTEN görünen alanlar burada (bkz.
 * `translatePydanticIssue`'nun kullanıldığı yerler: VehicleProfileForm vb.).
 * Listede olmayan bir alan için sadece çeviri metni gösterilir, alan adı
 * eklenmez - yine de tam Türkçe ve anlaşılır kalır.
 */
const FIELD_LABEL_TR: Record<string, string> = {
  name: "Profil adı",
  length_m: "Uzunluk",
  width_m: "Genişlik",
  height_m: "Yükseklik",
  weight_kg: "Ağırlık",
  vehicle_type: "Araç tipi",
  drivetrain: "Çekiş tipi",
  title: "Başlık",
  description: "Açıklama",
};

/**
 * Pydantic v2'nin `type` alanına göre standart doğrulama hatalarını Türkçe
 * cümleye çevirir. Eşleşme yoksa `null` döner (çağıran taraf ham `msg`e düşer) -
 * yani bilinmeyen bir hata türü asla sessizce kaybolmaz, sadece İngilizce
 * kalır (tamamen çevrilemeyen nadir bir edge-case için makul bir geri düşüş).
 */
function translatePydanticIssue(item: Record<string, unknown>): string | null {
  const type = typeof item.type === "string" ? item.type : null;
  if (!type) return null;

  const loc = Array.isArray(item.loc) ? item.loc : [];
  const fieldKey = String(loc[loc.length - 1] ?? "");
  const label = FIELD_LABEL_TR[fieldKey];
  const prefix = label ? `${label}: ` : "";
  const ctx = (item.ctx ?? {}) as Record<string, unknown>;

  switch (type) {
    case "greater_than":
      return `${prefix}${String(ctx.gt)} değerinden büyük olmalı.`;
    case "greater_than_equal":
      return `${prefix}${String(ctx.ge)} değerinden büyük veya eşit olmalı.`;
    case "less_than":
      return `${prefix}${String(ctx.lt)} değerinden küçük olmalı.`;
    case "less_than_equal":
      return `${prefix}${String(ctx.le)} değerinden küçük veya eşit olmalı.`;
    case "string_too_short":
      return `${prefix}en az ${String(ctx.min_length)} karakter olmalı.`;
    case "string_too_long":
      return `${prefix}en fazla ${String(ctx.max_length)} karakter olabilir.`;
    case "missing":
      return `${prefix}bu alan zorunlu.`;
    case "int_parsing":
    case "float_parsing":
    case "int_type":
    case "float_type":
    case "decimal_parsing":
      return `${prefix}sayısal bir değer olmalı.`;
    case "string_type":
      return `${prefix}metin olmalı.`;
    case "bool_type":
    case "bool_parsing":
      return `${prefix}evet/hayır olmalı.`;
    case "enum":
      return `${prefix}geçersiz bir değer seçildi.`;
    default:
      return null;
  }
}

/**
 * Kendi `HTTPException(detail="...")` çağrılarımız (401/404/409 vb.) düz
 * string döner; FastAPI/Pydantic'in kendi 422 doğrulama hataları ise
 * `{detail: [{msg, loc, type, ctx, ...}, ...]}` biçiminde bir dizi - ikisini
 * de ele alır. 422 dizisindeki her öğe önce `translatePydanticIssue` ile
 * Türkçeye çevrilmeye çalışılır; çeviri yoksa ham (İngilizce) `msg`e düşülür
 * - kullanıcı çoğu zaman ANLAŞILIR Türkçe bir hata görür, hiçbir zaman boş
 * bir mesajla kalmaz.
 */
export function extractErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item !== "object" || item === null) return null;
          const record = item as Record<string, unknown>;
          return translatePydanticIssue(record) ?? (typeof record.msg === "string" ? record.msg : null);
        })
        .filter((msg): msg is string => !!msg);
      if (messages.length > 0) return messages.join(" ");
    }
  }
  return fallback;
}
