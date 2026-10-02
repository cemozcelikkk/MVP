import { useTripStore } from "../store/useTripStore";
/**
 * MapLibre haritası - artık tam ekran değil, `DiscoverPanel`in YANINDA akışa
 * dahil bir flex kardeş (bkz. App.tsx). Panel açılıp kapandığında container'ın
 * genişliği CSS ile değişir; bir `ResizeObserver` bunu izleyip `map.resize()`
 * çağırır - bu hem panel geçişini hem pencere yeniden boyutlanmasını TEK
 * mekanizmayla (harita boyutu değiştiren her olayı ayrı ayrı dinlemeye gerek
 * kalmadan) doğru şekilde ele alır.
 *
 * Her `moveend` (pan/zoom bitişi) olayında görünür sınırları (bounding box)
 * backend'in `/spots/bbox` endpoint'ine gönderir; sonucu hem harita
 * pinlerinde HEM `useMapDataStore` üzerinden Keşif listesinde kullanır (AYRI
 * bir liste API çağrısı YOK).
 *
 * ## Kümelenme
 *
 * MapLibre'nin yerleşik GeoJSON `cluster:true` kaynağı bir "kümeleme motoru"
 * olarak kullanılır (supercluster); GÖRSEL üretim ise bilinçli olarak GL
 * katmanlarıyla DEĞİL, eski koddaki gibi DOM `Marker`larla yapılır - hem
 * küme baloncukları HEM tekil pinler gerçek, odaklanabilir `<button>`
 * elemanlarıdır (klavye/`aria-label` erişilebilirliği tamamen korunur, bkz.
 * görev tanımı). Kaynağa bağlı, opaklığı sıfır tek bir devre dışı katman
 * SADECE tiling/kümeleme hesaplamasını tetiklemek için eklenir (resmi
 * MapLibre/Mapbox "DOM marker kümeleme" örneklerindeki bilinen teknik) -
 * hiçbir zaman render EDİLMEZ. Her `render` olayında (kaynak yüklendiyse)
 * `querySourceFeatures` ile o anki küme/tekil nokta dağılımı okunur; ucuz
 * bir imza karşılaştırmasıyla DEĞİŞMEDİYSE marker'lar YENİDEN KURULMAZ.
 */
import {
  AttributionControl,
  GeoJSONSource,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre 6 worker'ını kendi JS dosyasının yanında (`./maplibre-gl-worker.mjs`)
// arar; Vite production build'i bu dosyayı dist'e kopyalamadığı için canlıda
// worker 404 alıyor ve tile'lar hiç işlenmiyor (harita boş/gri kalıyor - dev
// sunucusunda node_modules'tan servis edildiği için sorun görünmüyor).
// `?worker&url` worker'ı bağımlılıklarıyla (maplibre-gl-shared) birlikte ayrı
// bir chunk olarak derletir; URL'sini MapLibre'ye açıkça veriyoruz.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

setWorkerUrl(maplibreWorkerUrl);
import { AlertTriangle, ChevronDown, Loader2, MapPinned, Navigation, Plus, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSpotsInBbox, type SpotFeature } from "../lib/api";
import { applyCategoryPinVars, hasActiveWarning, pinInnerHtml } from "../lib/pinStyle";
import { useAuthStore } from "../store/useAuthStore";
import { useCreateSpotStore } from "../store/useCreateSpotStore";
import { useFavoritesStore } from "../store/useFavoritesStore";
import { useMapDataStore } from "../store/useMapDataStore";
import { filtersToQueryParams, useFilterStore } from "../store/filters";
import { useVehicleProfileStore } from "../store/useVehicleProfileStore";
import { applyMapLegibility } from "../lib/mapStyle";

// Ücretsiz, API anahtarı gerektirmeyen CARTO Voyager stili - açık, canlı,
// yeşil/doğal alanları ve yol hiyerarşisini net gösteren bir taban harita
// (navigasyon uygulamalarına yakın his). `applyMapLegibility` bunun
// üzerine ölçülü katman düzenlemeleri uygular (bkz. lib/mapStyle.ts) -
// ücretli/API anahtarlı yeni bir servise BAĞIMLILIK yok.
const MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

const SPOTS_SOURCE_ID = "spots";
const CLUSTER_ENGINE_LAYER_ID = "spots-cluster-engine"; // görünmez - sadece tiling/kümeleme tetikler

// Türkiye'nin coğrafi merkezi - ilk açılış görünümü.
const INITIAL_CENTER: [number, number] = [35.2433, 38.9637];
const INITIAL_ZOOM = 6;
// Kullanıcı tüm Türkiye'yi tek ekranda görebilir ama uzaya kadar uzaklaşamaz.
const MIN_ZOOM = 5.2;
const MAX_ZOOM = 18;
// Bu zoom'a kadar kümelenir; sonrasında tekil kategori piktogramları görünür.
const CLUSTER_MAX_ZOOM = 13;
const CLUSTER_RADIUS = 56;
// Harita bu kutunun dışına sürüklenemez/kaydırılamaz - Türkiye + kıyı
// sularını (Ege/Akdeniz güneybatı, Karadeniz/Doğu kuzeydoğu) kapsar.
const TURKEY_BOUNDS: [[number, number], [number, number]] = [
  [25.5, 35.5], // Güneybatı
  [45.0, 42.5], // Kuzeydoğu
];

interface Props {
  onSelectSpot?: (feature: SpotFeature | null) => void;
  selectedSpotId?: string | null;
}

type RenderedItem =
  | { kind: "point"; id: string; lng: number; lat: number; feature: SpotFeature }
  | { kind: "cluster"; id: string; clusterId: number; lng: number; lat: number; count: number };

/** Reconciliation'ı atlamak için ucuz bir "değişti mi" imzası. */
function signatureOf(items: RenderedItem[]): string {
  return items
    .map((it) =>
      it.kind === "point"
        ? `p:${it.id}:${it.lng.toFixed(5)}:${it.lat.toFixed(5)}:${it.feature.properties.compatibility?.status ?? ""}`
        : `c:${it.clusterId}:${it.lng.toFixed(4)}:${it.lat.toFixed(4)}:${it.count}`,
    )
    .sort()
    .join("|");
}

export default function MapView({ onSelectSpot, selectedSpotId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Map<string, Marker>>(new Map());
  const abortRef = useRef<AbortController | null>(null);
  const pendingMarkerRef = useRef<Marker | null>(null);
  const featuresByIdRef = useRef<Map<string, SpotFeature>>(new Map());
  const lastSignatureRef = useRef<string>("");
  // `renderMarkers`/reconciliation (useCallback) `onSelectSpot` değişmediği
  // sürece asla yeniden yaratılmıyor - bu yüzden `selectedSpotId` prop'unu
  // doğrudan kapatırsa (closure) değeri donar. Güncel değeri bir ref
  // üzerinden okutuyoruz.
  const selectedSpotIdRef = useRef<string | null>(null);

  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isPickingLocation = useCreateSpotStore((s) => s.isPickingLocation);
  const pendingCoordinates = useCreateSpotStore((s) => s.pendingCoordinates);
  const tripRoute = useTripStore(s=>s.route);
  const focusedLocation = useCreateSpotStore((s) => s.focusedLocation);
  const focusedSpot = useCreateSpotStore((s) => s.focusedSpot);
  const deletedSpotId = useCreateSpotStore((s) => s.deletedSpotId);
  const updatedSpot = useCreateSpotStore((s) => s.updatedSpot);

  const geoError = useCreateSpotStore((s) => s.geoError);
  const clearGeoError = useCreateSpotStore((s) => s.clearGeoError);

  const hasToilet = useFilterStore((s) => s.hasToilet);
  const hasTrashBins = useFilterStore((s) => s.hasTrashBins);
  const freeOnly = useFilterStore((s) => s.freeOnly);
  const campingAllowed = useFilterStore((s) => s.campingAllowed);
  const overnightAllowed = useFilterStore((s) => s.overnightAllowed);
  const hasFreshWater = useFilterStore((s) => s.hasFreshWater);
  const hasElectricity = useFilterStore((s) => s.hasElectricity);
  const no4x4Required = useFilterStore((s) => s.no4x4Required);
  const caravanOnly = useFilterStore((s) => s.caravanOnly);
  const onlyVerified = useFilterStore((s) => s.onlyVerified);
  const onlyFavorites = useFilterStore((s) => s.onlyFavorites);
  const vehicleCompatibleOnly = useFilterStore((s) => s.vehicleCompatibleOnly);
  const favoriteIds = useFavoritesStore((s) => s.favoriteIds);
  const fetchFavorites = useFavoritesStore((s) => s.fetchFavorites);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hasActiveVehicle = useVehicleProfileStore((s) => s.profiles.some((p) => p.is_active));

  const setMapDataResult = useMapDataStore((s) => s.setResult);
  const setMapDataLoading = useMapDataStore((s) => s.setLoading);
  const setMapDataError = useMapDataStore((s) => s.setError);
  const retryToken = useMapDataStore((s) => s.retryToken);

  // "Sadece Favorilerim" açıldığında favori id listesi henüz hiç
  // çekilmemiş olabilir (kullanıcı çekmeceyi hiç açmadıysa) - garanti altına al.
  useEffect(() => {
    if (onlyFavorites) fetchFavorites();
  }, [onlyFavorites, fetchFavorites]);

  const buildPointMarker = useCallback(
    (feature: SpotFeature) => {
      const id = feature.properties.id;
      const el = document.createElement("button");
      el.type = "button";
      el.className = "spot-pin";
      if (id === selectedSpotIdRef.current) el.classList.add("spot-pin--selected");
      // "caution" uyumluluğu (fiziksel sınırlar dikkat gerektiriyor) renkten
      // BAĞIMSIZ ayrı bir rozetle işaretlenir (bkz. lib/pinStyle.ts).
      if (feature.properties.compatibility?.status === "caution") {
        el.classList.add("spot-pin--caution");
      }
      applyCategoryPinVars(el, feature.properties.category);
      el.innerHTML = pinInnerHtml(feature);
      el.setAttribute(
        "aria-label",
        hasActiveWarning(feature) ? `${feature.properties.title} (aktif uyarı)` : feature.properties.title,
      );
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        onSelectSpot?.(feature);
      });
      return el;
    },
    [onSelectSpot],
  );

  const buildClusterMarker = useCallback((clusterId: number, count: number) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "spot-cluster";
    const size = count >= 50 ? 44 : count >= 10 ? 38 : 32;
    el.style.width = `${size}px`;
    el.style.height = `${size}px`;
    el.style.fontSize = count >= 100 ? "11px" : "12px";
    el.textContent = count >= 1000 ? `${Math.round(count / 1000)}k` : String(count);
    el.setAttribute("aria-label", `${count} nokta içeren küme - yakınlaşmak için seçin`);
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      const map = mapRef.current;
      const source = map?.getSource(SPOTS_SOURCE_ID) as GeoJSONSource | undefined;
      if (!map || !source) return;
      source.getClusterExpansionZoom(clusterId).then((zoom) => {
        const marker = markersRef.current.get(`cluster-${clusterId}`);
        const center = marker?.getLngLat();
        if (center) map.easeTo({ center, zoom: Math.min(zoom, MAX_ZOOM), duration: 400 });
      });
    });
    return el;
  }, []);

  /** Kaynağın o anki (kümeli+tekil) render listesini `querySourceFeatures`ten çıkarır. */
  const computeRenderedItems = useCallback((): RenderedItem[] | null => {
    const map = mapRef.current;
    if (!map || !map.getLayer(CLUSTER_ENGINE_LAYER_ID) || !map.isSourceLoaded(SPOTS_SOURCE_ID)) return null;
    const rendered = map.querySourceFeatures(SPOTS_SOURCE_ID);
    const items: RenderedItem[] = [];
    const seenClusters = new Set<number>();
    for (const f of rendered) {
      if (f.geometry.type !== "Point") continue;
      const [lng, lat] = f.geometry.coordinates as [number, number];
      if (f.properties?.cluster) {
        const clusterId = f.properties.cluster_id as number;
        if (seenClusters.has(clusterId)) continue; // aynı küme birden fazla tile'da tekrar edebilir
        seenClusters.add(clusterId);
        items.push({ kind: "cluster", id: `cluster-${clusterId}`, clusterId, lng, lat, count: f.properties.point_count as number });
      } else {
        const id = f.properties?.id as string;
        const original = featuresByIdRef.current.get(id);
        if (!original) continue;
        items.push({ kind: "point", id: `spot-${id}`, lng, lat, feature: original });
      }
    }
    return items;
  }, []);

  const reconcileMarkers = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const items = computeRenderedItems();
    if (!items) return;

    const signature = signatureOf(items);
    if (signature === lastSignatureRef.current) return;
    lastSignatureRef.current = signature;

    const next = new Map<string, Marker>();
    for (const item of items) {
      const existing = markersRef.current.get(item.id);
      if (existing) {
        markersRef.current.delete(item.id);
        next.set(item.id, existing);
        continue;
      }
      const el = item.kind === "point" ? buildPointMarker(item.feature) : buildClusterMarker(item.clusterId, item.count);
      next.set(item.id, new Marker({ element: el, anchor: "center" }).setLngLat([item.lng, item.lat]).addTo(map));
    }
    // Artık render listesinde olmayanları kaldır.
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = next;
  }, [buildPointMarker, buildClusterMarker, computeRenderedItems]);

  const loadSpotsForCurrentView = useCallback(async () => {
    const map = mapRef.current;
    if (!map) return;

    // Önceki (hâlâ süren) isteği iptal et - hızlı ardışık pan/zoom'larda
    // eski bir yanıtın geç gelip haritayı yanlış veriyle güncellemesini önler.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const bounds = map.getBounds();
    setMapDataLoading(true);
    setErrorMessage(null);
    setMapDataError(null);
    try {
      // Uyumluluk özeti: filtre kapalıyken de (yalnızca göstermek için,
      // ELEMEDEN) istenir - liste satırları ve pinlerdeki "dikkatli giriş"
      // rozeti bu sayede filtre açılmadan da görünebilir. Backend hiçbir
      // spot'u bu bayrak yüzünden elemez (bkz. spots.py::read_spots_in_bbox).
      const withCompatibility = vehicleCompatibleOnly || (isAuthenticated && hasActiveVehicle);
      const collection = await fetchSpotsInBbox(
        {
          min_lon: bounds.getWest(),
          min_lat: bounds.getSouth(),
          max_lon: bounds.getEast(),
          max_lat: bounds.getNorth(),
          ...filtersToQueryParams({
            hasToilet,
            hasTrashBins,
            freeOnly,
            campingAllowed,
            overnightAllowed,
            hasFreshWater,
            hasElectricity,
            no4x4Required,
            caravanOnly,
            onlyVerified,
            vehicleCompatibleOnly,
          }),
          ...(withCompatibility ? { with_compatibility: true } : {}),
        },
        controller.signal,
      );
      // "Sadece Favorilerim": backend'in `/bbox`'ı favori filtresi desteklemiyor,
      // bu yüzden istemci tarafında eleniyor (bkz. spec'teki "opsiyonel" not).
      let features = onlyFavorites
        ? collection.features.filter((f) => favoriteIds.has(f.properties.id))
        : collection.features;
      // "Aracıma Uygun" filtresi AÇIKKEN: not_compatible olanlar gizlenir.
      // Yalnızca GÖSTERMEK için çekilen (filtre kapalı) uyumluluk verisi
      // hiçbir noktayı elemez.
      if (vehicleCompatibleOnly) {
        features = features.filter((f) => f.properties.compatibility?.status !== "not_compatible");
      }

      featuresByIdRef.current = new Map(features.map((f) => [f.properties.id, f]));
      setMapDataResult(features);

      const map2 = mapRef.current;
      const source = map2?.getSource(SPOTS_SOURCE_ID) as GeoJSONSource | undefined;
      if (source) {
        source.setData({
          type: "FeatureCollection",
          features: features.map((f) => ({
            type: "Feature",
            id: f.properties.id,
            geometry: f.geometry,
            properties: { id: f.properties.id },
          })),
        });
      }
    } catch (err) {
      if (axiosWasCancelled(err)) return;
      console.error("Spot verisi çekilemedi:", err);
      const message = "Sunucuya bağlanılamadı. Backend çalışıyor mu?";
      setErrorMessage(message);
      setMapDataError(message);
    } finally {
      setMapDataLoading(false);
    }
  }, [
    hasToilet,
    hasTrashBins,
    freeOnly,
    campingAllowed,
    overnightAllowed,
    hasFreshWater,
    hasElectricity,
    no4x4Required,
    caravanOnly,
    onlyVerified,
    onlyFavorites,
    vehicleCompatibleOnly,
    favoriteIds,
    isAuthenticated,
    hasActiveVehicle,
    setMapDataResult,
    setMapDataLoading,
    setMapDataError,
  ]);

  // Harita yalnızca bir kez kurulur.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new MapLibreMap({
      container: containerRef.current,
      style: MAP_STYLE_URL,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      maxBounds: TURKEY_BOUNDS,
      attributionControl: false,
    });

    map.addControl(new AttributionControl({ compact: true }), "bottom-right");
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");

    mapRef.current = map;

    map.on("style.load", () => {
      applyMapLegibility(map);
      map.addSource(SPOTS_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        cluster: true,
        clusterMaxZoom: CLUSTER_MAX_ZOOM,
        clusterRadius: CLUSTER_RADIUS,
      });
      // Görsel üretim DOM Marker'larla yapılır (bkz. modül docstring'i) - bu
      // katman tamamen görünmezdir, TEK amacı kaynağın tiling/kümeleme
      // hesaplamasını (querySourceFeatures'ın veri döndürebilmesi için)
      // tetiklemektir.
      map.addLayer({
        id: CLUSTER_ENGINE_LAYER_ID,
        type: "circle",
        source: SPOTS_SOURCE_ID,
        paint: { "circle-radius": 0, "circle-opacity": 0 },
      });
      loadSpotsForCurrentView();
    });
    map.on("moveend", loadSpotsForCurrentView);
    map.on("render", reconcileMarkers);

    // Pinlerin dışında (boş) bir noktaya tıklanınca: konum seçim modundaysak
    // o noktayı seç, değilsek paneli kapat. Marker'lar kendi click
    // handler'ında stopPropagation() çağırdığı için bu olay sadece boş
    // harita alanına tıklandığında tetiklenir. `useCreateSpotStore`'u
    // `.getState()` ile okuyoruz ki bu (sadece mount'ta bağlanan) handler
    // her zaman güncel picking-mode değerini görsün.
    map.on("click", (event) => {
      const createSpotState = useCreateSpotStore.getState();
      if (createSpotState.isPickingLocation) {
        createSpotState.locationPicked([event.lngLat.lng, event.lngLat.lat]);
        return;
      }
      onSelectSpot?.(null);
    });
    // Sağ tık: picking modunda olmasak bile doğrudan o noktada nokta
    // ekleme formunu tetikler (oturum yoksa `locationPicked` kendi içinde
    // giriş modalını açar). Tarayıcının varsayılan sağ-tık menüsünü engelle.
    map.on("contextmenu", (event) => {
      event.originalEvent.preventDefault();
      useCreateSpotStore.getState().locationPicked([event.lngLat.lng, event.lngLat.lat]);
    });

    // Panel açılıp kapandığında (veya pencere yeniden boyutlandığında)
    // container'ın GERÇEK piksel boyutu değişir - ResizeObserver bunu
    // izleyip haritayı doğru şekilde yeniden boyutlandırır (bkz. modül
    // docstring'i); manuel timeout tahmini veya panel state'ine
    // abone olmaya gerek YOK.
    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
    // Bu efekt sadece mount/unmount için - `loadSpotsForCurrentView`/
    // `reconcileMarkers`'ın en güncel halini closure üzerinden görmesi
    // aşağıdaki ayrı efektte ele alınıyor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Filtreler (veya loadSpotsForCurrentView referansı) değiştiğinde:
  // 1) "moveend" handler'ını güncel closure ile yeniden bağla,
  // 2) haritayı hareket ettirmeden mevcut görünümü yeni filtrelerle sorgula.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    map.off("moveend", loadSpotsForCurrentView);
    map.on("moveend", loadSpotsForCurrentView);

    if (map.loaded() && map.getSource(SPOTS_SOURCE_ID)) {
      loadSpotsForCurrentView();
    }

    return () => {
      map.off("moveend", loadSpotsForCurrentView);
    };
  }, [loadSpotsForCurrentView]);

  // "Tekrar Dene" - toast eylemi bu sayacı artırır.
  useEffect(() => {
    if (retryToken > 0) loadSpotsForCurrentView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retryToken]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.off("render", reconcileMarkers);
    map.on("render", reconcileMarkers);
    return () => {
      map.off("render", reconcileMarkers);
    };
  }, [reconcileMarkers]);

  // `buildPointMarker`'ın (mount'ta donan closure yerine) her zaman güncel
  // seçimi görebilmesi için ref'i senkron tut.
  useEffect(() => {
    selectedSpotIdRef.current = selectedSpotId ?? null;
  }, [selectedSpotId]);

  // Seçili pin değişince: sadece ilgili marker elementinin sınıfını
  // toggle'la (mat pirinç sarısı çerçeve) - pinleri yeniden çizmeye gerek yok.
  useEffect(() => {
    markersRef.current.forEach((marker, id) => {
      if (id.startsWith("spot-")) {
        marker.getElement().classList.toggle("spot-pin--selected", id === `spot-${selectedSpotId}`);
      }
    });
  }, [selectedSpotId]);

  // Seçili pine yumuşakça ortala - panel artık akışa dahil (overlay değil),
  // bu yüzden haritanın GÖRÜNÜR genişliği zaten paneli hariç tutuyor; eski
  // sol-padding hilesine gerek YOK.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedSpotId) return;
    const marker = markersRef.current.get(`spot-${selectedSpotId}`);
    if (marker) map.easeTo({ center: marker.getLngLat(), duration: 400 });
  }, [selectedSpotId]);

  // Konum seçim modu: imleci crosshair'e çevir (MapLibre canvas'ının
  // kendi stilini doğrudan set ediyoruz - drag/hover'da üzerine yazılmasın
  // diye her `isPickingLocation` değişiminde yeniden uyguluyoruz).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor = isPickingLocation ? "crosshair" : "";
  }, [isPickingLocation]);

  // Haritaya bırakılan geçici (pirinç sarısı) pin - form açıkken görünür,
  // form kapanınca (iptal veya başarı) kaldırılır.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    pendingMarkerRef.current?.remove();
    pendingMarkerRef.current = null;
    if (pendingCoordinates) {
      const el = document.createElement("div");
      el.className = "spot-pin spot-pin--pending";
      pendingMarkerRef.current = new Marker({ element: el, anchor: "center" })
        .setLngLat(pendingCoordinates)
        .addTo(map);
    }
  }, [pendingCoordinates]);

  useEffect(() => {
    if (focusedLocation) mapRef.current?.flyTo({ center: focusedLocation, zoom: 12 });
  }, [focusedLocation]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (map.getLayer("trip-route-line")) map.removeLayer("trip-route-line");
      if (map.getSource("trip-route")) map.removeSource("trip-route");
      if (!tripRoute) return;
      map.addSource("trip-route", {type:"geojson",data:{type:"Feature",properties:{},geometry:tripRoute}});
      map.addLayer({id:"trip-route-line",type:"line",source:"trip-route",paint:{"line-color":"#28755c","line-width":4,"line-opacity":0.8}});
      const coords=tripRoute.coordinates;
      const lons=coords.map(point=>point[0]), lats=coords.map(point=>point[1]);
      map.fitBounds([[Math.min(...lons),Math.min(...lats)],[Math.max(...lons),Math.max(...lats)]],{padding:60,maxZoom:13});
    };
    if (map.isStyleLoaded()) apply(); else map.once("load",apply);
    return () => {map.off("load",apply);};
  }, [tripRoute]);

  // Bir spot "odaklandığında" (yeni oluşturma sonrası ya da Favoriler
  // çekmecesindeki [Haritada Göster]) haritayı o noktaya uçur.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusedSpot) return;
    map.flyTo({
      center: focusedSpot.geometry.coordinates,
      zoom: Math.max(map.getZoom(), 14),
      duration: 800,
    });
  }, [focusedSpot]);

  // Bir spot silinince: bir sonraki pan/zoom'u (moveend) beklemeden pinini
  // haritadan hemen kaldır.
  useEffect(() => {
    if (!deletedSpotId) return;
    const marker = markersRef.current.get(`spot-${deletedSpotId}`);
    if (marker) {
      marker.remove();
      markersRef.current.delete(`spot-${deletedSpotId}`);
    }
    featuresByIdRef.current.delete(deletedSpotId);
    lastSignatureRef.current = ""; // bir sonraki render'da yeniden kur
  }, [deletedSpotId]);

  // Bir spot düzenlenince (kategori değişmiş olabilir) veya yeni durum
  // bildirimi alınca (uyarı rozeti): ilgili pini bir sonraki bbox
  // yenilemesini beklemeden yerinde günceller.
  useEffect(() => {
    if (!updatedSpot) return;
    const id = updatedSpot.properties.id;
    featuresByIdRef.current.set(id, updatedSpot);
    const marker = markersRef.current.get(`spot-${id}`);
    if (!marker) return;
    const el = marker.getElement();
    applyCategoryPinVars(el, updatedSpot.properties.category);
    el.innerHTML = pinInnerHtml(updatedSpot);
    el.setAttribute(
      "aria-label",
      hasActiveWarning(updatedSpot) ? `${updatedSpot.properties.title} (aktif uyarı)` : updatedSpot.properties.title,
    );
  }, [updatedSpot]);

  // GPS hata mesajı toast'u: 6 saniye sonra otomatik kapanır.
  useEffect(() => {
    if (!geoError) return;
    const timer = setTimeout(() => clearGeoError(), 6000);
    return () => clearTimeout(timer);
  }, [geoError, clearGeoError]);

  return (
    <div className="relative h-full flex-1">
      <div ref={containerRef} className="h-full w-full" />

      <MapFloatingControls />
      <MapStatusBadge />
      {errorMessage ? <MapErrorToast message={errorMessage} onRetry={() => useMapDataStore.getState().retry()} /> : null}
      {geoError ? <GeoErrorToast message={geoError} onDismiss={clearGeoError} /> : null}
    </div>
  );
}

/** "+ Nokta Ekle" (birincil eylem) + konum seçim dropdown'u - haritanın kendi kutusunun sol üstü. */
function MapFloatingControls() {
  const isPickingLocation = useCreateSpotStore((s) => s.isPickingLocation);
  const startPicking = useCreateSpotStore((s) => s.startPicking);
  const cancelPicking = useCreateSpotStore((s) => s.cancelPicking);
  const isLocating = useCreateSpotStore((s) => s.isLocating);
  const locateCurrentPosition = useCreateSpotStore((s) => s.useCurrentLocation);
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Dropdown dışına tıklanınca kapat.
  useEffect(() => {
    if (!showDropdown) return;
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showDropdown]);

  if (isPickingLocation) {
    return (
      <div className="pointer-events-none absolute left-3 right-3 top-3 z-10 flex justify-center sm:left-4 sm:right-auto sm:justify-start">
        <div className="map-float-surface pointer-events-auto flex items-center gap-3 rounded-full py-2 pl-4 pr-2 text-sm font-medium text-text-primary">
          Konum seçmek için haritaya tıklayın
          <button
            type="button"
            onClick={cancelPicking}
            className="rounded-full border border-text-primary/25 px-3 py-1 text-xs font-semibold transition-colors hover:bg-surface-secondary"
          >
            İptal
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="pointer-events-none absolute left-3 top-3 z-10 sm:left-4 sm:top-4" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setShowDropdown((prev) => !prev)}
        data-testid="add-spot-button"
        className="pointer-events-auto flex min-h-touch items-center gap-1.5 rounded-full bg-accent-green px-5 text-sm font-semibold text-text-on-dark shadow-float transition-colors hover:bg-accent-green-hover"
      >
        <Plus size={17} />
        Nokta Ekle
        <ChevronDown size={14} className={`ml-0.5 transition-transform ${showDropdown ? "rotate-180" : ""}`} />
      </button>

      {showDropdown && (
        <div className="pointer-events-auto mt-2 min-w-[220px] overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-float">
          <button
            type="button"
            onClick={() => {
              setShowDropdown(false);
              startPicking();
            }}
            className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-text-primary transition-colors hover:bg-surface-secondary"
          >
            <MapPinned size={18} className="shrink-0 text-accent-green" />
            <div>
              <span className="block">Haritadan Seç</span>
              <span className="block text-xs font-normal text-text-secondary">Harita üzerinde bir konum seçin</span>
            </div>
          </button>
          <div className="mx-3 border-t border-border-light" />
          <button
            type="button"
            disabled={isLocating}
            onClick={() => {
              setShowDropdown(false);
              locateCurrentPosition();
            }}
            className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-text-primary transition-colors hover:bg-surface-secondary disabled:opacity-50"
          >
            {isLocating ? (
              <Loader2 size={18} className="shrink-0 animate-spin text-accent-green" />
            ) : (
              <Navigation size={18} className="shrink-0 text-accent-green" />
            )}
            <div>
              <span className="block">{isLocating ? "Konum alınıyor…" : "Konumumu Kullan"}</span>
              <span className="block text-xs font-normal text-text-secondary">GPS ile mevcut konumunuz</span>
            </div>
          </button>
        </div>
      )}
    </div>
  );
}

/** Görünen bölgedeki nokta sayısı - okunaklı bir harita durum rozeti (eski "52 NOKTA" mono kutusunun yerine). */
function MapStatusBadge() {
  const count = useMapDataStore((s) => s.features.length);
  const isLoading = useMapDataStore((s) => s.isLoading);

  return (
    <div className="map-float-surface pointer-events-none absolute bottom-4 left-3 z-10 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-text-primary sm:left-4">
      {isLoading ? (
        <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent-brass" aria-hidden />
      ) : null}
      <span className="font-semibold tabular-nums">{count}</span>
      <span className="text-text-secondary">{isLoading ? "yükleniyor…" : "nokta bu bölgede"}</span>
    </div>
  );
}

/** Bağlantı hatası - eski "sol altta küçük mono kutu" yerine, tekrar dene eylemi olan kısa bir toast. */
function MapErrorToast({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex justify-center sm:top-4">
      <div className="map-float-surface pointer-events-auto flex items-center gap-3 rounded-md px-3.5 py-2.5 text-sm text-text-primary">
        <AlertTriangle size={16} className="shrink-0 text-warning-rust" />
        <span>{message}</span>
        <button
          type="button"
          onClick={onRetry}
          className="flex shrink-0 items-center gap-1 rounded-md border border-text-primary/25 px-2.5 py-1 text-xs font-semibold transition-colors hover:bg-surface-secondary"
        >
          <RotateCcw size={12} />
          Tekrar Dene
        </button>
      </div>
    </div>
  );
}

function axiosWasCancelled(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: string }).name === "CanceledError"
  );
}

/** GPS konum hatası toast'u - izin reddedildi, timeout vb. */
function GeoErrorToast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="pointer-events-none absolute inset-x-3 bottom-14 z-20 flex justify-center sm:bottom-12">
      <div className="map-float-surface pointer-events-auto flex items-center gap-3 rounded-md px-3.5 py-2.5 text-sm text-text-primary">
        <Navigation size={16} className="shrink-0 text-warning-rust" />
        <span>{message}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 rounded-md p-1 transition-colors hover:bg-surface-secondary"
          aria-label="Kapat"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
