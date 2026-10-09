/**
 * Taban harita POI'leri - CARTO vektör tile'larının `poi` katmanından (OSM
 * verisi) gelen, karavancı için anlamlı işletme/hizmet noktaları: hastane,
 * eczane, akaryakıt, market, ATM, tamirci, polis, restoran/kafe vb.
 *
 * Bunlar KaravanTR kayıtları DEĞİLDİR: veritabanına yazılmaz, tıklanamaz,
 * sadece harita altlığının bir parçasıdır. KaravanTR spot'ları ayrı ve daha
 * baskın bir katmanda (DOM marker'lar, bkz. MapView) her zaman bunların
 * ÜSTÜNDE çizilir; bu katmandaki ikonlar bilinçli olarak daha küçük ve
 * dairesel (spot pinleri köşeli kare).
 *
 * Veri sınırı: OpenMapTiles şemasında (CARTO dahil) işletme POI'leri yalnızca
 * zoom 14 tile'larında bulunur; z11-13'te bu katmanda sadece metro/istasyon/
 * üniversite vardır. Bu yüzden iki kaynak birlikte çalışır:
 *   - z11-13: backend'in `/basemap-pois` ucu (haftalık OSM içe aktarımı,
 *     bkz. backend scripts/import_basemap_pois.py) - z11-12 hastane/akaryakıt/
 *     polis, z13'te + sağlık ocağı/eczane;
 *   - z14+: vektör tile POI'leri - önemliler z14'te, küçük işletmeler z15'te. Restoran mutfağı (`cuisine`) tile'da taşınmadığından "balık
 * restoranı" ayrımı yapılamaz; `shop=seafood` (balıkçı) ayrı gösterilir.
 *
 * Yoğun bölgelerde MapLibre'nin sembol çakışma (collision) motoru kullanılır:
 * ikonlar üst üste binmez, `symbol-sort-key` ile önemli POI'ler önce
 * yerleşir; isim sığmazsa (`text-optional`) yalnızca ikon kalır.
 */
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibreMap, SymbolLayerSpecification } from "maplibre-gl";
import { type BasemapPoiCategory, fetchBasemapPois } from "./api";

const SOURCE_ID = "carto";
const LOW_ZOOM_SOURCE_ID = "kt-basemap-pois";
const LOW_ZOOM_MIN = 11;
const LOW_ZOOM_MAX = 14; // bu zoom'dan itibaren vektör tile POI'leri devralır
// Önem sırası (backend `BASEMAP_POI_CATEGORIES` ile aynı) - çakışmada öndekiler kazanır.
const LOW_ZOOM_PRIORITY: BasemapPoiCategory[] = ["hospital", "fuel", "police", "clinic", "pharmacy"];
// İstenen alanın görünür alana göre her yönde genişletme oranı - küçük kaydırmalarda yeni istek atılmaz.
const FETCH_PADDING = 0.25;
const SOURCE_LAYER = "poi";
const ICON_PREFIX = "kt-poi-";
// Positron'un kendi etiketleriyle aynı yığın - glyph sunucusunda mevcut olduğu garanti.
const FONT_STACK = ["Montserrat Medium", "Open Sans Bold", "Noto Sans Regular"];

interface PoiGroup {
  key: string;
  /** OSM değerleri - tile'daki `subclass` alanıyla eşleşir. */
  subclasses: string[];
  color: string;
  /** 24x24 viewBox'ta beyaz çizgi ikon (SVG path `d` değerleri). */
  paths: string[];
  /** true: z14'te görünür ve çakışmada önce yerleşir; false: z15+. */
  major: boolean;
}

export const POI_GROUPS: PoiGroup[] = [
  { key: "hospital", subclasses: ["hospital"], color: "#B83A3F", major: true, paths: ["M8 6v12", "M16 6v12", "M8 12h8"] },
  { key: "clinic", subclasses: ["clinic"], color: "#C65A5E", major: true, paths: ["M12 6.5v11", "M6.5 12h11"] },
  {
    key: "pharmacy", subclasses: ["pharmacy"], color: "#3C8D5A", major: true,
    paths: ["M5.5 13.5l8 -8a3.5 3.5 0 0 1 5 5l-8 8a3.5 3.5 0 0 1 -5 -5z", "M9.5 9.5l5 5"],
  },
  {
    key: "fuel", subclasses: ["fuel"], color: "#44607F", major: true,
    paths: ["M5 20v-14a2 2 0 0 1 2 -2h6a2 2 0 0 1 2 2v14", "M4 20h12", "M7 9h6", "M15 10h2a2 2 0 0 1 2 2v4a1 1 0 0 0 2 0v-7l-3 -3"],
  },
  { key: "police", subclasses: ["police"], color: "#2F4E8C", major: true, paths: ["M12 3l7 3v5c0 5 -3 8 -7 10c-4 -2 -7 -5 -7 -10v-5z"] },
  {
    key: "car_repair", subclasses: ["car_repair"], color: "#61666E", major: false,
    paths: ["M14.7 6.3a4 4 0 0 0 -5.4 5.4l-5.3 5.3l3 3l5.3 -5.3a4 4 0 0 0 5.4 -5.4l-2.5 2.5l-2.4 -.6l-.6 -2.4z"],
  },
  {
    key: "supermarket", subclasses: ["supermarket"], color: "#55813A", major: false,
    paths: ["M6 19a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0", "M15 19a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0", "M3 4h2l2.5 11h10l2 -7h-13.3"],
  },
  { key: "convenience", subclasses: ["convenience"], color: "#73904A", major: false, paths: ["M6 8h12l-1 12h-10z", "M9 8v-2a3 3 0 0 1 6 0v2"] },
  { key: "atm", subclasses: ["atm"], color: "#8C7340", major: false, paths: ["M3 7h18v10h-18z", "M10 12a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"] },
  {
    key: "restaurant", subclasses: ["restaurant"], color: "#C0682C", major: false,
    paths: ["M7 3v18", "M4 3v5a3 3 0 0 0 6 0v-5", "M17 3c-2 0 -3 2 -3 6s1 4 3 4v8"],
  },
  {
    key: "cafe", subclasses: ["cafe"], color: "#94684C", major: false,
    paths: ["M5 9h11v5a5 5 0 0 1 -5 5h-1a5 5 0 0 1 -5 -5z", "M16 11h1.5a2.5 2.5 0 0 1 0 5h-1.5", "M8 3v3", "M12 3v3"],
  },
  { key: "butcher", subclasses: ["butcher"], color: "#8E3B32", major: false, paths: ["M4 14l9 -9l6 6l-5 5h-5z", "M8 15l-4 4"] },
  {
    key: "seafood", subclasses: ["seafood"], color: "#2F7FA6", major: false,
    paths: ["M3 12c3 -4 7 -6 11 -5c3 .7 5 2.5 6 5c-1 2.5 -3 4.3 -6 5c-4 1 -8 -1 -11 -5z", "M3 12l-1 -3", "M3 12l-1 3", "M16 11v.01"],
  },
];

/** Daire zemin + beyaz halka + beyaz çizgi ikon; 2x piksel oranında (keskin). */
function drawIcon(group: PoiGroup): ImageData | null {
  const size = 40; // 2x -> ekranda 20px
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 2, 0, Math.PI * 2);
  ctx.fillStyle = group.color;
  ctx.fill();
  ctx.lineWidth = 3;
  ctx.strokeStyle = "#FFFDF7";
  ctx.stroke();

  // 24'lük ikon kutusunu 22px'lik iç alana sığdır.
  const scale = 22 / 24;
  ctx.translate((size - 24 * scale) / 2, (size - 24 * scale) / 2);
  ctx.scale(scale, scale);
  ctx.strokeStyle = "#FFFFFF";
  ctx.lineWidth = 2.4;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const d of group.paths) ctx.stroke(new Path2D(d));
  return ctx.getImageData(0, 0, size, size);
}

function iconMatchExpression(): ExpressionSpecification {
  const pairs = POI_GROUPS.flatMap((g) => [g.subclasses, `${ICON_PREFIX}${g.key}`]);
  return ["match", ["get", "subclass"], ...pairs, ""] as unknown as ExpressionSpecification;
}

function sortKeyExpression(groups: PoiGroup[]): ExpressionSpecification {
  const pairs = groups.flatMap((g, index) => [g.subclasses, index]);
  return ["match", ["get", "subclass"], ...pairs, 99] as unknown as ExpressionSpecification;
}

function layerSpec(id: string, groups: PoiGroup[], minzoom: number): SymbolLayerSpecification {
  return {
    id,
    type: "symbol",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    minzoom,
    filter: ["in", ["get", "subclass"], ["literal", groups.flatMap((g) => g.subclasses)]],
    layout: {
      "icon-image": iconMatchExpression(),
      "icon-size": ["interpolate", ["linear"], ["zoom"], 14, 0.85, 17, 1],
      "icon-allow-overlap": false,
      "icon-padding": 2,
      // Katman içinde önce hastane/eczane gibi gruplar yerleşsin (dizideki sıra = öncelik).
      "symbol-sort-key": sortKeyExpression(groups),
      "text-field": ["get", "name"],
      "text-font": FONT_STACK,
      "text-size": ["interpolate", ["linear"], ["zoom"], 15, 10, 18, 12],
      "text-anchor": "top",
      "text-offset": [0, 0.9],
      "text-max-width": 8,
      // Etiket sığmazsa ikon yine de kalır; yoğun bölgede isimler önce düşer.
      "text-optional": true,
    },
    paint: {
      "text-color": "#4F524C",
      "text-halo-color": "rgba(247, 243, 232, 0.95)",
      "text-halo-width": 1.4,
      // z14'te sadece ikon (isimler z15'ten itibaren) - ilk açılışta kalabalık olmasın.
      "text-opacity": ["step", ["zoom"], 0, 15, 1],
    },
  };
}

/**
 * POI ikonlarını kaydeder ve iki sembol katmanı ekler (önemli: z14+, küçük
 * işletmeler: z15+). `style.load` içinde çağrılır; sonraki çağrılar no-op.
 */
export function addBasemapPois(map: MapLibreMap): void {
  try {
    if (!map.getSource(SOURCE_ID)) return; // stil değişmişse (kaynak adı farklı) sessizce atla
    for (const group of POI_GROUPS) {
      const id = `${ICON_PREFIX}${group.key}`;
      if (map.hasImage(id)) continue;
      const image = drawIcon(group);
      if (image) map.addImage(id, image, { pixelRatio: 2 });
    }
    const major = POI_GROUPS.filter((g) => g.major);
    const minor = POI_GROUPS.filter((g) => !g.major);
    // Önce eklenen altta kalır; sembol yerleşimi ÜSTTEKİ katmandan başlar ->
    // önemli POI'ler üstte, çakışmada küçük işletmelere karşı kazanır.
    if (!map.getLayer("kt-poi-minor")) map.addLayer(layerSpec("kt-poi-minor", minor, 15));
    if (!map.getLayer("kt-poi-major")) map.addLayer(layerSpec("kt-poi-major", major, 14));
    addLowZoomLayer(map);
  } catch {
    // POI'ler süsleme amaçlı - eklenemezse harita onsuz çalışmaya devam eder.
  }
}

/** z11-12'de yalnızca büyük/seyrek noktalar; z13'te yoğun olanlar (eczane, sağlık ocağı) da eklenir. */
function lowZoomCategories(zoom: number): BasemapPoiCategory[] {
  return zoom >= 13 ? LOW_ZOOM_PRIORITY : ["hospital", "fuel", "police"];
}

function lowZoomLayerSpec(): SymbolLayerSpecification {
  const sortPairs = LOW_ZOOM_PRIORITY.flatMap((category, index) => [category, index]);
  return {
    id: "kt-poi-lowzoom",
    type: "symbol",
    source: LOW_ZOOM_SOURCE_ID,
    minzoom: LOW_ZOOM_MIN,
    maxzoom: LOW_ZOOM_MAX,
    layout: {
      "icon-image": ["concat", ICON_PREFIX, ["get", "category"]],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.7, 13, 0.8],
      "icon-allow-overlap": false,
      "icon-padding": 3,
      "symbol-sort-key": ["match", ["get", "category"], ...sortPairs, 99] as unknown as ExpressionSpecification,
      // z13'te yalnızca hastane isimleri - diğerleri ikon olarak kalır.
      "text-field": ["case", ["==", ["get", "category"], "hospital"], ["coalesce", ["get", "name"], ""], ""],
      "text-font": FONT_STACK,
      "text-size": 10,
      "text-anchor": "top",
      "text-offset": [0, 0.8],
      "text-max-width": 8,
      "text-optional": true,
    },
    paint: {
      "text-color": "#4F524C",
      "text-halo-color": "rgba(247, 243, 232, 0.95)",
      "text-halo-width": 1.4,
      "text-opacity": ["step", ["zoom"], 0, 13, 1],
    },
  };
}

function addLowZoomLayer(map: MapLibreMap) {
  if (!map.getSource(LOW_ZOOM_SOURCE_ID)) {
    map.addSource(LOW_ZOOM_SOURCE_ID, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  }
  // Tile POI katmanlarının ALTINA: zoom aralıkları zaten ayrık, sıra sadece tutarlılık için.
  if (!map.getLayer("kt-poi-lowzoom")) {
    map.addLayer(lowZoomLayerSpec(), map.getLayer("kt-poi-minor") ? "kt-poi-minor" : undefined);
  }
}

/**
 * z11-13 POI'lerini harita hareket ettikçe backend'den yükler. Ayrık bir
 * yükleyici: kendi isteğini iptal eder, istenen (genişletilmiş) alanın içinde
 * kalındıkça ve kategori kademesi değişmedikçe yeni istek atmaz. Hata olursa
 * sessizce atlar - bu süsleme katmanı haritanın asıl işlevini etkilememeli.
 * Dönen fonksiyon dinleyicileri kaldırır.
 */
export function attachBasemapPoiLoader(map: MapLibreMap): () => void {
  let controller: AbortController | null = null;
  let loaded: { west: number; south: number; east: number; north: number; tier: string } | null = null;

  async function update() {
    const zoom = map.getZoom();
    if (zoom < LOW_ZOOM_MIN || zoom >= LOW_ZOOM_MAX) return;
    const source = map.getSource(LOW_ZOOM_SOURCE_ID) as GeoJSONSource | undefined;
    if (!source) return;

    const bounds = map.getBounds();
    const categories = lowZoomCategories(zoom);
    const tier = categories.join(",");
    if (
      loaded &&
      loaded.tier === tier &&
      bounds.getWest() >= loaded.west &&
      bounds.getEast() <= loaded.east &&
      bounds.getSouth() >= loaded.south &&
      bounds.getNorth() <= loaded.north
    ) {
      return;
    }

    const padLng = (bounds.getEast() - bounds.getWest()) * FETCH_PADDING;
    const padLat = (bounds.getNorth() - bounds.getSouth()) * FETCH_PADDING;
    const area = {
      west: bounds.getWest() - padLng,
      east: bounds.getEast() + padLng,
      south: bounds.getSouth() - padLat,
      north: bounds.getNorth() + padLat,
    };

    controller?.abort();
    controller = new AbortController();
    try {
      const data = await fetchBasemapPois(
        { min_lng: area.west, min_lat: area.south, max_lng: area.east, max_lat: area.north, category: categories },
        controller.signal,
      );
      source.setData(data);
      loaded = { ...area, tier };
    } catch {
      // İptal veya ağ hatası - bir sonraki hareket yeniden dener.
    }
  }

  map.on("moveend", update);
  map.on("style.load", update);
  if (map.isStyleLoaded()) void update();
  return () => {
    controller?.abort();
    map.off("moveend", update);
    map.off("style.load", update);
  };
}
