/**
 * KaravanTR "outdoor" taban harita görünümü - CARTO Positron'un ücretsiz,
 * API anahtarsız vektör tile'ları üzerine uygulanan bir renk/katman katmanı.
 *
 * Positron bilinçli olarak monokrom bir "veri zemini": neredeyse beyaz kara,
 * gri su, beyaz yollar ve tek bir soluk yeşil. Oysa aynı tile'lar zengin
 * arazi örtüsü sınıfları taşır (orman, çayır/çalılık, tarım/bahçe/bağ, kaya,
 * kum, sulak alan) - Positron bunların çoğunu filtreyle gizler. Burada:
 *   - arazi örtüsü sınıflarına göre (data-driven `match`) ayrı renkler,
 *   - sıcak bej kara, canlı mavi su, sarı/turuncu ana yollar,
 *   - daha güçlü yer isimleri, görünür ama baskın olmayan sınırlar,
 *   - anahtarsız açık yükselti verisiyle (AWS Terrain Tiles) hafif hillshade.
 *
 * Tüm değişiklikler `style.load` anında, ilk kare çizilmeden uygulanır (beyaz
 * flaş olmaz) ve tek seferliktir - pan/zoom sırasında hiçbir JS çalışmaz.
 * Her çağrı `try/catch` ile korunur: CARTO stilini güncellerse (katman id'si
 * değişir/kalkarsa) tek bir ayar sessizce atlanır, harita KIRILMAZ.
 */
import type { FilterSpecification, Map as MapLibreMap } from "maplibre-gl";

/** Outdoor paleti - KaravanTR'ın sıcak kum/orman yeşili görsel diline uyumlu. */
export const OUTDOOR_COLORS = {
  background: "#F1ECDD",
  forest: "#C7D9B0",
  park: "#D8E5C2",
  grassland: "#E2E5C8", // çayır/çalılık - parkla ormandan daha soluk (bozkır geniş alan kaplar)
  farmland: "#E7DDBD",
  orchard: "#DFDDB5",
  rock: "#E2DBCC",
  sand: "#F0E4C2",
  wetland: "#CFE0D2",
  residential: "rgba(214, 200, 172, 0.32)",
  water: "#79B6DE",
  waterLabel: "#2C6890",
  majorRoad: "#D7A65D",
  majorRoadCase: "#B8883F",
  primaryRoad: "#E4BE7C",
  primaryRoadCase: "#C49C58",
  secondaryRoad: "#F5E7C4",
  minorRoad: "#FCF9F1",
  minorRoadCase: "#D5C7A9",
  rail: "#C9BFAC",
  building: "#E3DAC6",
  label: "#545751",
  labelStrong: "#3E413C",
  labelHalo: "#F7F3E8",
  boundaryCountry: "#9C8F80",
  boundaryState: "#B3A698",
} as const;

// AWS Open Data "Terrain Tiles" (Terrarium kodlaması) - anahtarsız, CORS açık.
const TERRAIN_SOURCE_ID = "outdoor-terrain-dem";
const HILLSHADE_LAYER_ID = "outdoor-hillshade";
const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
// z12'den sonra DEM yeniden örneklenir (overzoom) - yakın zoom'da yeni karo indirilmez.
const TERRAIN_MAX_ZOOM = 12;
// Hillshade bu katmanın ALTINA eklenir: arazi örtüsünün üstünde, su/yol/etiketlerin altında.
const HILLSHADE_BEFORE_LAYER = "waterway";

// `setPaintProperty`nin tip imzası katman TÜRÜNE göre değişen daraltılmış bir
// union kabul ediyor (`keyof AllPaintProperties`) - burada layer id'sini
// (dolayısıyla türünü) DERLEME ZAMANINDA bilmiyoruz, `prop` serbest bir
// string. Çalışma zamanında `getLayer` ile korunuyor; tip kontrolünü bu TEK
// noktada bilinçli olarak gevşetiyoruz.
type LooseSetter = (layerId: string, prop: string, value: unknown) => void;

function setPaint(map: MapLibreMap, layerId: string, prop: string, value: unknown) {
  try {
    if (map.getLayer(layerId)) (map.setPaintProperty as unknown as LooseSetter)(layerId, prop, value);
  } catch {
    // Katman/özellik artık yok - sessizce atla (harita hâlâ çalışır).
  }
}

function setFilter(map: MapLibreMap, layerId: string, filter: FilterSpecification) {
  try {
    if (map.getLayer(layerId)) map.setFilter(layerId, filter);
  } catch {
    // Aynı gerekçe - stil değişmişse atla.
  }
}

/** Stildeki id'si `pattern`e uyan tüm katmanlar. */
function layerIds(map: MapLibreMap, pattern: RegExp): string[] {
  return (map.getStyle().layers ?? []).map((l) => l.id).filter((id) => pattern.test(id));
}

function styleLandcover(map: MapLibreMap) {
  const c = OUTDOOR_COLORS;
  // Positron sadece wood/grass çizer; tile'larda zaten olan diğer sınıfları da aç.
  setFilter(map, "landcover", [
    "any",
    ["in", ["get", "class"], ["literal", ["wood", "grass", "farmland", "rock", "sand", "wetland"]]],
    ["==", ["get", "subclass"], "recreation_ground"],
  ]);
  setPaint(map, "landcover", "fill-color", [
    "match",
    ["get", "class"],
    "wood", c.forest,
    "farmland", ["match", ["get", "subclass"], ["orchard", "vineyard"], c.orchard, c.farmland],
    "rock", c.rock,
    "sand", c.sand,
    "wetland", c.wetland,
    // grass: şehir parkı/golf yeşil, bozkır/çalılık daha soluk
    ["match", ["get", "subclass"], ["park", "golf_course", "recreation_ground"], c.park, c.grassland],
  ]);
  setPaint(map, "landcover", "fill-opacity", ["interpolate", ["linear"], ["zoom"], 5, 0.85, 12, 1]);

  for (const id of ["park_national_park", "park_nature_reserve"]) {
    setPaint(map, id, "fill-color", c.park);
    setPaint(map, id, "fill-opacity", 0.55);
  }
  setPaint(map, "landuse", "fill-color", c.park);
  setPaint(map, "landuse", "fill-opacity", 0.8);
  setPaint(map, "landuse_residential", "fill-color", c.residential);
}

function styleWater(map: MapLibreMap) {
  const c = OUTDOOR_COLORS;
  setPaint(map, "water", "fill-color", c.water);
  setPaint(map, "waterway", "line-color", c.water);
  for (const id of layerIds(map, /^(watername_|waterway_label)/)) {
    setPaint(map, id, "text-color", c.waterLabel);
    setPaint(map, id, "text-halo-color", "rgba(241, 236, 221, 0.7)");
  }
}

function styleRoads(map: MapLibreMap) {
  const c = OUTDOOR_COLORS;
  // Katman adları: {road|bridge|tunnel}_{mot|trunk|pri|sec|minor|service}_{fill|case}[_ramp|_noramp]
  const tiers: [RegExp, string, string][] = [
    [/_(mot|trunk)_/, c.majorRoad, c.majorRoadCase],
    [/_pri_/, c.primaryRoad, c.primaryRoadCase],
    [/_sec_/, c.secondaryRoad, c.minorRoadCase],
    [/_(minor|service)_/, c.minorRoad, c.minorRoadCase],
  ];
  for (const id of layerIds(map, /^(road|bridge|tunnel)_/)) {
    const tier = tiers.find(([pattern]) => pattern.test(id));
    if (tier) setPaint(map, id, "line-color", /_case/.test(id) ? tier[2] : tier[1]);
    else if (/_path$/.test(id)) setPaint(map, id, "line-color", c.minorRoadCase);
  }
  for (const id of layerIds(map, /^(tunnel_)?rail$/)) setPaint(map, id, "line-color", c.rail);
  for (const id of layerIds(map, /^(tunnel_)?rail_dash$/)) setPaint(map, id, "line-color", c.background);
  for (const id of layerIds(map, /^aeroway-/)) setPaint(map, id, "line-color", "#E0D8C6");

  for (const id of layerIds(map, /^roadname_/)) {
    setPaint(map, id, "text-color", "#6B675B");
    setPaint(map, id, "text-halo-color", c.labelHalo);
  }
}

function styleBuildingsAndBoundaries(map: MapLibreMap) {
  const c = OUTDOOR_COLORS;
  setPaint(map, "building", "fill-color", "#D9CFB8");
  setPaint(map, "building-top", "fill-color", c.building);
  setPaint(map, "building-top", "fill-outline-color", "#D9CFB8");

  setPaint(map, "boundary_country_inner", "line-color", c.boundaryCountry);
  setPaint(map, "boundary_country_inner", "line-opacity", 0.75);
  setPaint(map, "boundary_country_outline", "line-color", c.background);
  setPaint(map, "boundary_state", "line-color", c.boundaryState);
  setPaint(map, "boundary_state", "line-opacity", 0.6);
  setPaint(map, "boundary_county", "line-color", c.boundaryState);
  setPaint(map, "boundary_county", "line-opacity", 0.35);
}

function styleLabels(map: MapLibreMap) {
  const c = OUTDOOR_COLORS;
  for (const id of layerIds(map, /^place_/)) {
    const isCity = /^place_(city|capital)/.test(id);
    const isRegion = /^place_(country|state|continent)/.test(id);
    setPaint(map, id, "text-color", isCity ? c.labelStrong : isRegion ? "#7C776B" : c.label);
    setPaint(map, id, "icon-color", c.labelStrong);
    setPaint(map, id, "text-halo-color", c.labelHalo);
    setPaint(map, id, "text-halo-width", isCity ? 1.6 : 1.2);
  }
  for (const id of ["poi_park", "poi_stadium"]) {
    setPaint(map, id, "text-color", "#5E7D4E");
    setPaint(map, id, "text-halo-color", c.labelHalo);
  }
}

function addHillshade(map: MapLibreMap) {
  try {
    if (!map.getSource(TERRAIN_SOURCE_ID)) {
      map.addSource(TERRAIN_SOURCE_ID, {
        type: "raster-dem",
        tiles: [TERRAIN_TILES],
        tileSize: 256,
        encoding: "terrarium",
        maxzoom: TERRAIN_MAX_ZOOM,
        attribution: '<a href="https://registry.opendata.aws/terrain-tiles/" target="_blank">Terrain Tiles (AWS/Mapzen)</a>',
      });
    }
    if (!map.getLayer(HILLSHADE_LAYER_ID)) {
      map.addLayer(
        {
          id: HILLSHADE_LAYER_ID,
          type: "hillshade",
          source: TERRAIN_SOURCE_ID,
          paint: {
            // Uzak zoom'da rölyef hissi, yakında (şehir/sokak) geri çekilir.
            "hillshade-exaggeration": ["interpolate", ["linear"], ["zoom"], 5, 0.4, 10, 0.3, 14, 0.15],
            "hillshade-shadow-color": "rgba(86, 78, 58, 0.55)",
            "hillshade-highlight-color": "rgba(255, 252, 242, 0.45)",
            "hillshade-accent-color": "rgba(120, 110, 86, 0.25)",
          },
        },
        map.getLayer(HILLSHADE_BEFORE_LAYER) ? HILLSHADE_BEFORE_LAYER : undefined,
      );
    }
  } catch {
    // Hillshade süsleme amaçlı - eklenemezse harita onsuz çalışmaya devam eder.
  }
}

/** Positron'u outdoor görünüme çevirir. `style.load` içinde, kendi katmanlarımızdan ÖNCE çağrılmalı. */
export function applyOutdoorStyle(map: MapLibreMap): void {
  setPaint(map, "background", "background-color", OUTDOOR_COLORS.background);
  styleLandcover(map);
  styleWater(map);
  styleRoads(map);
  styleBuildingsAndBoundaries(map);
  styleLabels(map);
  addHillshade(map);
}
