/** Küçük, paylaşılan sayı/metin biçimlendirme yardımcıları. */

/** 6.4 -> "6,4" / 4.0 -> "4" - Türkçe ondalık ayraç, gereksiz sıfır yok. Araç uzunluğu VE puan ortalamaları için ortak kullanılır. */
export function formatDecimalTr(value: number): string {
  const text = value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return text.replace(".", ",");
}

/** Google Haritalar'da yol tarifi başlatan URL - kart ve detay panelinde ortak kullanılır. */
export function googleMapsDirectionsUrl(lat: number, lon: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
}
