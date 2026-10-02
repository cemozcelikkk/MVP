/**
 * Taban harita (CARTO Voyager) üzerinde KONTROLLÜ katman düzenlemeleri -
 * yeni bir harita servisine/API anahtarına bağımlılık YOK. Voyager zaten
 * açık, canlı ve navigasyon hissi veren bir stil (krem zemin, yeşil
 * yeşil alanlar, mavi su, sarı/krem yol hiyerarşisi) - burada sadece iki
 * ölçülü ayar yapılır:
 *   - Yeşil/doğal alanlar (orman, çayır, park) düşük zoom'da stilin
 *     varsayılanında çok soluk kalıyor; "canlı ve doğal" hissi için
 *     her zoom'da belirgin bir yeşile sabitlenir.
 *   - İl/ilçe sınırları soluklaştırılır, pin/etiketlerin önüne geçmez.
 *
 * Her çağrı `try/catch` ile korunur: CARTO stilini güncellerse (katman id'si
 * değişir/kalkarsa) tek bir ayar sessizce atlanır, harita KIRILMAZ.
 */
import type { Map as MapLibreMap } from "maplibre-gl";

const GREEN_NATURAL = "#cfe8ba";

// `setPaintProperty`nin tip imzası katman TÜRÜNE göre değişen daraltılmış bir
// union kabul ediyor (`keyof AllPaintProperties`) - burada layer id'sini
// (dolayısıyla türünü) DERLEME ZAMANINDA bilmiyoruz, `prop` serbest bir
// string. Çalışma zamanında `getLayer` ile korunuyor; tip kontrolünü bu TEK
// noktada bilinçli olarak gevşetiyoruz.
type LoosePaintSetter = (layerId: string, prop: string, value: unknown) => void;

function setPaint(map: MapLibreMap, layerId: string, prop: string, value: unknown) {
  try {
    if (map.getLayer(layerId)) (map.setPaintProperty as unknown as LoosePaintSetter)(layerId, prop, value);
  } catch {
    // Katman/özellik artık yok - sessizce atla (harita hâlâ çalışır).
  }
}

export function applyMapLegibility(map: MapLibreMap): void {
  // --- Yeşil/doğal alanlar: her zoom'da belirgin, canlı bir yeşil ---
  for (const id of ["landcover", "park_national_park", "park_nature_reserve", "landuse"]) {
    setPaint(map, id, "fill-color", GREEN_NATURAL);
    setPaint(map, id, "fill-opacity", 0.65);
  }

  // --- İl/ilçe sınırları: soluklaştır, ana içeriğin önüne geçmesin ---
  setPaint(map, "boundary_state", "line-opacity", 0.5);
  setPaint(map, "boundary_county", "line-opacity", 0.35);
}
