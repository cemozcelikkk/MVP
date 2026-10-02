/**
 * Backend API client ve tip tanımları.
 *
 * Tipler, backend'deki `app/schemas/*.py` içindeki Pydantic şemalarının
 * (özellikle `SpotProperties` / GeoJSON `Feature`) birebir TypeScript
 * karşılığıdır - alan adları ve null/optional durumları kasıtlı olarak
 * backend ile aynı tutuldu ki iki taraf arasında sessiz uyumsuzluk olmasın.
 */
import axios from "axios";

// Ortam değişkeniyle override edilebilir (Vercel proje ayarları ya da .env.local):
// - VITE_API_BASE_URL: tam API yolu (örn. https://api.ornek.com/api/v1 veya /api/v1)
// - VITE_API_URL: sadece backend adresi (örn. https://api.ornek.com) - /api/v1 eklenir
// İkisi de yoksa lokal backend'e gider. `||` kullanıyoruz ki boş bırakılmış
// bir değişken de varsayılana düşsün.
const API_ORIGIN_ENV = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, "");
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (API_ORIGIN_ENV ? `${API_ORIGIN_ENV}/api/v1` : "http://127.0.0.1:8000/api/v1");

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

// API_BASE_URL "/api/v1" sonekini taşır; fotoğraf gibi statik dosyalar
// (`storage_url`/`thumbnail_url`) backend'den `/uploads/...` gibi KÖKE göre
// bağıl bir yol olarak dönüyor - bu yüzden aynı ayardan backend'in kök
// origin'ini türetiyoruz (VITE_API_BASE_URL override edilse bile doğru kalır).
export const BACKEND_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

/**
 * Backend'den gelen bir medya URL'ini (fotoğraf `storage_url`/`thumbnail_url`
 * gibi) tarayıcıda kullanılabilir mutlak bir URL'e çevirir. Zaten mutlaksa
 * (http/https) olduğu gibi bırakır - aksi halde başına backend origin'ini ekler.
 */
export function resolveMediaUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return `${BACKEND_ORIGIN}${url.startsWith("/") ? "" : "/"}${url}`;
}

// Token'ın tek doğruluk kaynağı localStorage - `useAuthStore` da aynı
// anahtarı kullanır. Interceptor'ı store'a değil doğrudan localStorage'a
// bağlıyoruz ki `store/useAuthStore.ts` <-> `lib/api.ts` arasında dairesel
// import oluşmasın (store zaten login/register için bu dosyayı import ediyor).
export const AUTH_TOKEN_STORAGE_KEY = "karavantr_auth_token";

apiClient.interceptors.request.use((config) => {
  let token: string | null = null;
  try {
    token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  } catch {
    // localStorage kullanılamıyor (gizli sekme/kısıtlı ortam) - token'sız devam et.
  }
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// --- Domain enum'ları (bkz. backend app/models/enums.py) ---

export type SpotCategory =
  | "wild_camping"
  | "campsite"
  | "sanistation_only"
  | "day_parking"
  | "farm_stay";

export type RoadType = "asphalt" | "gravel" | "dirt" | "rocky";
export type ClearanceRequired = "low" | "standard" | "high_4x4";
export type PoliceInterventionStatus = "none" | "warning" | "fine" | "banned" | "unknown";
export type CrowdLevel = "empty" | "low" | "medium" | "high" | "full";

// --- İlişkili alt kayıtlar ---

export interface SpotPassability {
  road_type: RoadType;
  max_vehicle_length: number | null;
  // Karavan Profili uyumluluk motoru için (bkz. backend compatibility_service).
  // Saha verisi bilinmiyorsa null - asla 0/tahmini bir değer DEĞİL.
  max_vehicle_width: number | null;
  max_vehicle_height: number | null;
  max_vehicle_weight_kg: number | null;
  clearance_required: ClearanceRequired;
  caravan_types_allowed: string[];
  steep_incline: boolean;
}

export interface SpotAmenities {
  fresh_water_thread: boolean;
  black_water: boolean;
  grey_water: boolean;
  electricity_220v: boolean;
  has_toilet: boolean;
  has_trash_bins: boolean;
  is_free: boolean;
  price_description: string | null;
  camping_behavior_allowed: boolean;
  rule_information_known: boolean;
  gsm_signals: Record<string, string>;
}

export interface DynamicStatus {
  id: string;
  spot_id: string;
  police_intervention: PoliceInterventionStatus;
  note: string | null;
  crowd_level: CrowdLevel | null;
  valid_until: string | null;
  /** Gizlilik: herkese açık yanıtta HEP null (bildiren kimliği dönmez). */
  reported_by: string | null;
  reported_at: string;
  /** Süreli canlı bildirim alanları (eski kayıtlarda null/`pending` olabilir). */
  report_type?: LiveReportType | null;
  moderation_state?: ReportModerationState;
  duration_hours?: number | null;
}

export interface SpotPhoto {
  photo_kind: "general" | "entrance";
  id: string;
  spot_id: string;
  storage_url: string;
  thumbnail_url: string | null;
  caption: string | null;
  uploaded_by: string | null;
  created_at: string;
  is_cover: boolean;
}

// --- GeoJSON Feature.properties (bkz. backend app/schemas/spot.py::SpotProperties) ---

export type OvernightStatus = "allowed" | "not_allowed" | "unknown";
export interface SpotTravelInfo {
  overnight_status: OvernightStatus;
  max_stay_nights: number | null;
  rule_description: string | null;
  rule_source: string | null;
  rule_checked_on: string | null;
  private_property_permission: "required" | "not_required" | "unknown";
  entry_latitude: number | null;
  entry_longitude: number | null;
  approach_description: string | null;
  access_season: string | null;
}
export const EMPTY_TRAVEL_INFO: SpotTravelInfo = {
  overnight_status: "unknown", max_stay_nights: null, rule_description: null,
  rule_source: null, rule_checked_on: null, private_property_permission: "unknown",
  entry_latitude: null, entry_longitude: null, approach_description: null, access_season: null,
};

export interface SpotProperties extends SpotTravelInfo {
  id: string;
  title: string;
  description: string | null;
  category: SpotCategory;
  altitude: number | null;
  is_verified: boolean;
  // Sahiplik kontrolü (düzenle/sil butonlarının görünürlüğü) için - auth
  // eklenmeden önce oluşturulmuş seed verisinde null olabilir.
  created_by: string | null;
  created_at: string;
  updated_at: string;
  passability: SpotPassability | null;
  amenities: SpotAmenities | null;
  latest_status: DynamicStatus | null;
  /** Hafif aktif canlı durum özeti (bbox dahil; ham bildirim/geçmiş YOK). */
  live_status?: SpotLiveSummary | null;
  average_rating: number | null;
  review_count: number;
  photos: SpotPhoto[];
  // Sadece `fetchSpotsInBbox({ withCompatibility: true })` ile ve kullanıcının
  // aktif bir araç profili varsa dolu gelir - aksi halde `undefined`. Tam
  // gerekçe listesi TAŞIMAZ (bkz. backend `SpotCompatibilitySummary`
  // docstring'i) - detay için `fetchSpotCompatibility` kullanılır.
  compatibility?: { status: CompatibilityStatus };
  // Sadece `fetchSpotById` (tekil detay) ile dolu gelir - bbox listesinde
  // YOK (bkz. backend `spots.py::read_spots_in_bbox` docstring'i, harita
  // performansı için kasıtlı). `SpotDetailSidebar` bunu göstermeden önce
  // `fetchSpotById`i bekler (bkz. `SpotReviewsSection`).
  dimension_ratings?: SpotDimensionRatings;
}

export interface SpotFeature {
  type: "Feature";
  id: string;
  geometry: {
    type: "Point";
    // GeoJSON sırası: [boylam, enlem] - [lat, lon] DEĞİL.
    coordinates: [number, number];
  };
  properties: SpotProperties;
}

export interface SpotFeatureCollection {
  type: "FeatureCollection";
  features: SpotFeature[];
}

// --- /spots/bbox sorgu parametreleri (bkz. backend spot_service.get_spots_in_bbox) ---

export interface BboxQueryParams {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  category?: SpotCategory[];
  only_verified?: boolean;
  has_fresh_water?: boolean;
  has_black_water?: boolean;
  has_electricity?: boolean;
  has_toilet?: boolean;
  has_trash_bins?: boolean;
  is_free?: boolean;
  camping_behavior_allowed?: boolean;
  overnight_allowed?: boolean;

  max_vehicle_length?: number;
  requires_4x4?: boolean;
  caravan_type?: string;
  // true ise (VE kullanıcı kimliği doğrulanmışsa + aktif araç profili
  // varsa) her feature'a hafif bir `compatibility.status` eklenir - harita
  // "Aracıma Uygun" filtresi için. Bayrak kapalıyken (varsayılan) backend
  // hiçbir ekstra sorgu çalıştırmaz (bkz. backend endpoint docstring'i).
  with_compatibility?: boolean;
}

export async function fetchSpotsInBbox(
  params: BboxQueryParams,
  signal?: AbortSignal,
): Promise<SpotFeatureCollection> {
  const { data } = await apiClient.get<SpotFeatureCollection>("/spots/bbox", {
    params,
    signal,
    // axios varsayılan olarak diziyi "category[]=x" biçiminde serileştirir;
    // FastAPI/Starlette ise tekrarlanan düz parametre bekliyor ("category=x&category=y").
    paramsSerializer: { indexes: null },
  });
  return data;
}

// --- /spots/{id}/favorite (bkz. backend app/api/v1/endpoints/spot_interactions.py) ---

export interface FavoriteToggleResponse {
  is_favorited: boolean;
}

/** Kimlik doğrulama gerektirir (Bearer token) - backend `get_current_user` bağımlılığı. */
export async function toggleSpotFavorite(spotId: string): Promise<FavoriteToggleResponse> {
  const { data } = await apiClient.post<FavoriteToggleResponse>(`/spots/${spotId}/favorite`);
  return data;
}

// --- POST /spots/{id}/status (bkz. backend app/schemas/dynamic_status.py) ---

export interface DynamicStatusCreatePayload {
  police_intervention: PoliceInterventionStatus;
  note?: string | null;
  crowd_level?: CrowdLevel | null;
  /** Bildirimin kaç saat sonra süresi dolsun (1-168, varsayılan 24). */
  expires_in_hours?: number;
}

/** Kimlik doğrulama gerektirir. Yanıt doğrudan `SpotProperties.latest_status` ile aynı şekildedir. */
export async function reportSpotStatus(
  spotId: string,
  payload: DynamicStatusCreatePayload,
): Promise<DynamicStatus> {
  const { data } = await apiClient.post<DynamicStatus>(`/spots/${spotId}/status`, payload);
  return data;
}

// --- POST /spots/{id}/check-in (bkz. backend app/schemas/check_in.py) ---

export interface CheckIn {
  id: string;
  spot_id: string;
  user_id: string;
  checked_in_at: string;
  planned_nights: number | null;
}

/**
 * Kimlik doğrulama gerektirir. `latitude`/`longitude`, check-in anındaki
 * GERÇEK GPS konumu olmalı - backend bunu spot'un koordinatıyla PostGIS
 * `ST_DWithin` üzerinden karşılaştırıp 500 metreden uzaksa 400 ile
 * reddediyor (bkz. `checkin_service.add_check_in`); aynı gün ikinci
 * denemede 409 döner. Başarılıysa backend kullanıcının `trust_score`'unu
 * +1 artırır (bu yanıtın gövdesinde dönmez - `useAuthStore.incrementTrustScore`
 * istemci tarafında iyimser olarak aynı hizaya getirir).
 */
export async function checkInSpot(
  spotId: string,
  latitude: number,
  longitude: number,
): Promise<CheckIn> {
  const { data } = await apiClient.post<CheckIn>(`/spots/${spotId}/check-in`, { latitude, longitude });
  return data;
}

// --- POST /spots (bkz. backend app/schemas/spot.py::SpotCreate) ---
// Not: multipart DEĞİL, düz JSON - fotoğraflar ayrı bir uçla (aşağıda
// `uploadSpotPhoto`) spot oluşturulduktan SONRA, dönen id ile yükleniyor.

export interface SpotCreatePayload extends Partial<SpotTravelInfo> {
  title: string;
  description: string | null;
  category: SpotCategory;
  coordinates: { latitude: number; longitude: number };
  passability: {
    road_type: RoadType;
    max_vehicle_length: number | null;
    max_vehicle_width: number | null;
    max_vehicle_height: number | null;
    max_vehicle_weight_kg: number | null;
    clearance_required: ClearanceRequired;
    caravan_types_allowed: string[];
    steep_incline: boolean;
  };
  amenities: SpotAmenities;
}

/** Kimlik doğrulama gerektirir. Yanıt, harita/detay panelinin beklediği aynı `SpotFeature` şeklidir. */
export async function createSpot(payload: SpotCreatePayload): Promise<SpotFeature> {
  const { data } = await apiClient.post<SpotFeature>("/spots", payload);
  return data;
}

export async function fetchSpotById(spotId: string): Promise<SpotFeature> {
  const { data } = await apiClient.get<SpotFeature>(`/spots/${spotId}`);
  return data;
}

/** Kimlik doğrulama gerektirir (multipart/form-data). */
export async function uploadSpotPhoto(spotId: string, file: File, photoKind: "general" | "entrance" = "general"): Promise<SpotPhoto> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("photo_kind", photoKind);
  const { data } = await apiClient.post<SpotPhoto>(`/spots/${spotId}/photos`, formData);
  return data;
}

/** Çoklu fotoğraf yükleme (multipart/form-data). `coverIndex` kapak fotoğrafının sırasını belirler. */
export async function uploadSpotPhotos(
  spotId: string,
  files: File[],
  coverIndex: number = 0,
  approachIndices: number[] = [],
): Promise<SpotPhoto[]> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  formData.append("cover_index", String(coverIndex));
  for (const index of approachIndices) formData.append("approach_indices",String(index));
  const { data } = await apiClient.post<SpotPhoto[]>(
    `/spots/${spotId}/photos/batch`,
    formData,
  );
  return data;
}

// --- PATCH /spots/{id} (bkz. backend app/schemas/spot.py::SpotUpdate) ---
// Not: `coordinates` kasıtlı olarak yok - konum bu uçla taşınamaz.

export interface SpotUpdatePayload extends Partial<SpotTravelInfo> {
  coordinates?: { latitude: number; longitude: number };
  title?: string;
  description?: string | null;
  category?: SpotCategory;
  passability?: SpotCreatePayload["passability"];
  amenities?: Partial<SpotAmenities>;
}

/** Kimlik doğrulama gerektirir. Sadece spot sahibi veya moderator/admin (aksi halde 403). */
export async function updateSpot(spotId: string, payload: SpotUpdatePayload): Promise<SpotFeature> {
  const { data } = await apiClient.patch<SpotFeature>(`/spots/${spotId}`, payload);
  return data;
}

// --- DELETE /spots/{id} ---

/** Kimlik doğrulama gerektirir. Soft-delete - sadece spot sahibi veya moderator/admin (aksi halde 403). */
export async function deleteSpot(spotId: string): Promise<void> {
  await apiClient.delete(`/spots/${spotId}`);
}

// --- /auth/* (bkz. backend app/api/v1/endpoints/auth.py, app/schemas/user.py) ---

export type UserRole = "user" | "moderator" | "admin";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  trust_score: number;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
}

export interface RegisterPayload {
  email: string;
  // API sözleşmesi: `username` - backend bunu `display_name` kolonuna yazar.
  username: string;
  password: string;
}

/**
 * Backend `OAuth2PasswordRequestForm` bekliyor: JSON değil,
 * `application/x-www-form-urlencoded` gövde, e-posta `username` alanında.
 */
export async function loginRequest(email: string, password: string): Promise<AuthToken> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  const { data } = await apiClient.post<AuthToken>("/auth/login", body, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}

export async function registerRequest(payload: RegisterPayload): Promise<User> {
  const { data } = await apiClient.post<User>("/auth/register", payload);
  return data;
}

export async function fetchCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<User>("/auth/me");
  return data;
}

// --- /users/me/favorites (bkz. backend app/api/v1/endpoints/users.py) ---

/**
 * `SpotRead`in hafif bir alt kümesi - liste/kart görünümleri için yeterli
 * (passability/amenities/photos/latest_status YOK, bkz. backend
 * `app/schemas/spot.py::SpotSummary` docstring'i).
 */
export interface SpotSummary extends Partial<SpotTravelInfo> {
  id: string;
  title: string;
  description: string | null;
  category: SpotCategory;
  altitude: number | null;
  is_verified: boolean;
  average_rating: number | null;
  review_count: number;
  latitude: number;
  longitude: number;
}

/** Kimlik doğrulama gerektirir. Hiç favori yoksa boş dizi döner (404 değil). */
export async function getUserFavorites(): Promise<SpotSummary[]> {
  const { data } = await apiClient.get<SpotSummary[]>("/users/me/favorites");
  return data;
}

// --- /vehicle-profiles (bkz. backend app/api/v1/endpoints/vehicle_profiles.py) ---
// "Karavan Profili ve Otomatik Nokta Uyumluluğu" özelliği. Tüm uçlar kimlik
// doğrulama gerektirir; kullanıcı yalnızca kendi profillerini görebilir.

export type VehicleType = "motorhome" | "campervan" | "travel_trailer" | "other";
export type Drivetrain = "4x2" | "4x4";

export interface VehicleProfile {
  id: string;
  user_id: string;
  name: string;
  vehicle_type: VehicleType;
  length_m: number;
  width_m: number | null;
  height_m: number | null;
  weight_kg: number | null;
  drivetrain: Drivetrain;
  has_grey_water_tank: boolean;
  has_black_water_cassette: boolean;
  has_solar_power: boolean;
  travels_with_pet: boolean;
  // Kullanıcı başına en fazla BİR profil aktif olabilir (backend'de kısmi
  // unique index ile garanti edilir) - uyumluluk motoru varsayılan olarak
  // bunu kullanır.
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface VehicleProfilePayload {
  name: string;
  vehicle_type: VehicleType;
  length_m: number;
  width_m?: number | null;
  height_m?: number | null;
  weight_kg?: number | null;
  drivetrain?: Drivetrain;
  has_grey_water_tank?: boolean;
  has_black_water_cassette?: boolean;
  has_solar_power?: boolean;
  travels_with_pet?: boolean;
  is_active?: boolean;
}

export type VehicleProfileUpdatePayload = Partial<VehicleProfilePayload>;

export async function listVehicleProfiles(): Promise<VehicleProfile[]> {
  const { data } = await apiClient.get<VehicleProfile[]>("/vehicle-profiles");
  return data;
}

export async function createVehicleProfile(payload: VehicleProfilePayload): Promise<VehicleProfile> {
  const { data } = await apiClient.post<VehicleProfile>("/vehicle-profiles", payload);
  return data;
}

export async function fetchVehicleProfile(profileId: string): Promise<VehicleProfile> {
  const { data } = await apiClient.get<VehicleProfile>(`/vehicle-profiles/${profileId}`);
  return data;
}

export async function updateVehicleProfile(
  profileId: string,
  payload: VehicleProfileUpdatePayload,
): Promise<VehicleProfile> {
  const { data } = await apiClient.patch<VehicleProfile>(`/vehicle-profiles/${profileId}`, payload);
  return data;
}

export async function deleteVehicleProfile(profileId: string): Promise<void> {
  await apiClient.delete(`/vehicle-profiles/${profileId}`);
}

/** Bu profili aktif yapar - kullanıcının varsa önceki aktif profili backend'de deaktive edilir. */
export async function activateVehicleProfile(profileId: string): Promise<VehicleProfile> {
  const { data } = await apiClient.post<VehicleProfile>(`/vehicle-profiles/${profileId}/activate`);
  return data;
}

// --- GET /spots/{id}/compatibility (bkz. backend app/schemas/compatibility.py) ---

export type CompatibilityStatus = "compatible" | "caution" | "not_compatible" | "insufficient_data";
export type CompatibilityReasonSeverity = "blocking" | "warning" | "unknown" | "info";

export interface CompatibilityReason {
  /** Makine-okunur, stabil kod - karar mantığını BUNA dayandır, `message`e değil. */
  code: string;
  severity: CompatibilityReasonSeverity;
  message: string;
}

/** Uyumluluk yanıtındaki "şu an erişilebilir mi" - fiziksel uygunluktan (`status`) AYRIDIR. */
export interface SpotLiveAccess {
  status: LiveAccess;
  headline: string | null;
  physical_text: string;
  live_text: string | null;
  reasons: LiveReportGroup[];
}

export interface SpotCompatibilityResult {
  live_access?: SpotLiveAccess | null;
  spot_id: string;
  vehicle_profile_id: string;
  status: CompatibilityStatus;
  summary: string;
  reasons: CompatibilityReason[];
  checked_at: string;
}

/**
 * Kimlik doğrulama gerektirir. `vehicleProfileId` verilmezse kullanıcının
 * AKTİF profili kullanılır; kullanıcının hiç (aktif) profili yoksa ve
 * `vehicleProfileId` de verilmemişse backend 404 döner.
 */
export async function fetchSpotCompatibility(
  spotId: string,
  vehicleProfileId?: string,
): Promise<SpotCompatibilityResult> {
  const { data } = await apiClient.get<SpotCompatibilityResult>(`/spots/${spotId}/compatibility`, {
    params: vehicleProfileId ? { vehicle_profile_id: vehicleProfileId } : undefined,
  });
  return data;
}

// --- /spots/{id}/reviews (bkz. backend app/schemas/review.py) ---
// "Çok boyutlu saha değerlendirmesi" özelliği.

/**
 * Yedi sabit ölçüt, hepsi opsiyonel (1-5 veya bilinmiyorsa `null` -
 * "Değerlendirmedim"). Alan adları backend `DIMENSION_KEYS` ile birebir
 * aynı - sırası da "en yararlı 3" gösterimiyle tutarlı (ilk 3: safety/
 * quietness/road_access).
 */
export interface DimensionRatings {
  safety: number | null;
  quietness: number | null;
  road_access: number | null;
  ground_suitability: number | null;
  cleanliness: number | null;
  view: number | null;
  signal: number | null;
}

/** Bir ölçütün spot genelindeki özeti - `count` olmadan `average` tek başına yanıltıcı olabilir. */
export interface DimensionRatingStat {
  average: number | null;
  count: number;
}

export interface SpotDimensionRatings {
  safety: DimensionRatingStat;
  quietness: DimensionRatingStat;
  road_access: DimensionRatingStat;
  ground_suitability: DimensionRatingStat;
  cleanliness: DimensionRatingStat;
  view: DimensionRatingStat;
  signal: DimensionRatingStat;
}

/** Yorumun yazıldığı ANDAKİ araç türü/uzunluğu - araç adı/plaka/profil ID'si YOK (gizlilik, bkz. backend). */
export interface ReviewVehicleSnapshot {
  vehicle_type: VehicleType;
  length_m: number;
}

export interface Review {
  id: string;
  spot_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
  dimension_ratings: DimensionRatings;
  vehicle_snapshot: ReviewVehicleSnapshot | null;
  /** Yorumun yazarının bu noktada GEÇERLİ bir check-in kaydı var mı - kesin GPS kanıtı DEĞİLDİR. */
  is_verified_checkin: boolean;
}

export interface ReviewCreatePayload {
  rating: number;
  comment?: string | null;
  dimension_ratings?: Partial<DimensionRatings>;
}

/**
 * PATCH gövdesi - `rating`/`comment` PATCH semantiği (gönderilmezse
 * değişmez). `dimension_ratings` İÇİNDEKİ her alt-alan AYRI davranır:
 * bir ölçütü `null` göndermek onu "Değerlendirmedim"e döndürür, hiç
 * göndermemek dokunmaz (bkz. backend `ReviewUpdate` docstring'i).
 */
export type ReviewUpdatePayload = Partial<ReviewCreatePayload>;

export async function fetchSpotReviews(spotId: string, limit = 50, offset = 0): Promise<Review[]> {
  const { data } = await apiClient.get<Review[]>(`/spots/${spotId}/reviews`, {
    params: { limit, offset },
  });
  return data;
}

/** Kimlik doğrulama gerektirir. Kullanıcının aktif araç profili varsa tür/uzunluk anlık görüntüsü otomatik eklenir. */
export async function createReview(spotId: string, payload: ReviewCreatePayload): Promise<Review> {
  const { data } = await apiClient.post<Review>(`/spots/${spotId}/reviews`, payload);
  return data;
}

/** Kimlik doğrulama gerektirir. Sadece yorumun sahibi veya moderator/admin (aksi halde 403). */
export async function updateReview(
  spotId: string,
  reviewId: string,
  payload: ReviewUpdatePayload,
): Promise<Review> {
  const { data } = await apiClient.patch<Review>(`/spots/${spotId}/reviews/${reviewId}`, payload);
  return data;
}

/**
 * Kimlik doğrulama gerektirir. Kullanıcının bu noktadaki AKTİF değerlendirmesi;
 * yoksa `null`. Kullanıcı+nokta başına tek aktif değerlendirme olduğu için (backend
 * ikinci POST'a 409 döner) arayüz "yaz" yerine "düzenle" göstermek için bunu kullanır.
 */
export async function fetchMyReview(spotId: string): Promise<Review | null> {
  const { data } = await apiClient.get<Review | null>(`/spots/${spotId}/reviews/me`);
  return data;
}

// --- Saha bilgisi güncelliği / yerinde doğrulama (bkz. backend app/schemas/field_verification.py) ---
// Karar mantığı (eşikler, çelişki, güven) tamamen backend'de; buradaki tipler sadece
// KARARLI makine kodlarını taşır - istemci metne değil koda dayanmalı.

export type VerifiableField =
  | "road_access"
  | "overnight"
  | "fresh_water"
  | "electricity"
  | "grey_water"
  | "black_water"
  | "toilet"
  | "trash_bins"
  | "price"
  | "camping_behavior";

export type VerificationAnswer =
  | "working"
  | "not_working"
  | "allowed"
  | "not_allowed"
  | "passable"
  | "difficult"
  | "impassable"
  | "free"
  | "paid"
  | "unknown";

export type FreshnessStatus =
  | "recently_confirmed"
  | "stale"
  | "conflicting_reports"
  | "unverified"
  | "service_issue_reported";
export type FreshnessTone = "positive" | "caution" | "negative" | "neutral";
export type FreshnessConfidence = "low" | "medium" | "high";

/** Süreli canlı durumdan (ör. zabıta bildirimi) gelen sinyal - kalıcı doğrulamadan AYRIDIR. */
export interface FreshnessLiveSignal {
  code: string;
  severity: "warning" | "blocking";
  message: string;
  conflicts_with_verification: boolean;
  report_type?: LiveReportType | null;
  reporter_count?: number;
  trust_level?: LiveTrustLevel | null;
  expires_at?: string | null;
}

export interface FieldFreshness {
  field: VerifiableField;
  label: string;
  status: FreshnessStatus;
  tone: FreshnessTone;
  status_text: string;
  consensus_answer: VerificationAnswer | null;
  conflicting_answers: VerificationAnswer[];
  participant_count: number;
  supporting_count: number;
  /** Sadece GÜN (YYYY-MM-DD) - tam saat herkese açık değil. */
  last_verified_on: string | null;
  age_days: number | null;
  confidence: FreshnessConfidence;
  fresh_days: number;
  /** Noktanın KALICI bildirilen bilgisi - doğrulama bunu değiştirmez. */
  reported_text: string | null;
  live_signal: FreshnessLiveSignal | null;
  /** Bu satırı etkileyen TÜM aktif süreli sorunlar (en ciddi ilk). */
  live_signals?: FreshnessLiveSignal[];
  /** true: olumlu (eski) doğrulama aktif bir süreli sorunla çelişiyor - yeşil/baskın gösterilmemeli. */
  live_overrides?: boolean;
}

export interface SpotFieldFreshness {
  spot_id: string;
  primary: FieldFreshness[];
  secondary: FieldFreshness[];
}

export interface MyVerifications {
  eligible: boolean;
  eligibility_code: "ELIGIBLE" | "NO_RECENT_CHECKIN";
  eligibility_message: string;
  check_in_at: string | null;
  has_pending_prompt: boolean;
  current_answers: Partial<Record<VerifiableField, VerificationAnswer>>;
  history: { field: VerifiableField; answer: VerificationAnswer; created_at: string; is_current: boolean }[];
}

export interface VerificationSubmitResponse {
  results: { field: VerifiableField; action: "created" | "updated" | "unchanged" | "skipped" }[];
  freshness: SpotFieldFreshness;
}

/** Herkese açık; kullanıcı kimliği içermez. Sadece nokta detayında çağrılır (bbox'ta yok). */
export async function fetchFieldFreshness(spotId: string): Promise<SpotFieldFreshness> {
  const { data } = await apiClient.get<SpotFieldFreshness>(`/spots/${spotId}/field-freshness`);
  return data;
}

/** Kimlik doğrulama gerektirir. Kendi geçmişin + son 72 saatte bu noktada check-in şartı. */
export async function fetchMyVerifications(spotId: string): Promise<MyVerifications> {
  const { data } = await apiClient.get<MyVerifications>(`/spots/${spotId}/verifications/me`);
  return data;
}

/** Kimlik doğrulama + geçerli check-in gerektirir (aksi halde 403). `unknown` gönderilen alan saklanmaz. */
export async function submitVerifications(
  spotId: string,
  answers: Partial<Record<VerifiableField, VerificationAnswer>>,
): Promise<VerificationSubmitResponse> {
  const { data } = await apiClient.post<VerificationSubmitResponse>(`/spots/${spotId}/verifications`, {
    answers,
  });
  return data;
}

// --- Süreli canlı saha bildirimleri (bkz. backend app/schemas/live_report.py) ---

export type LiveReportType =
  | "overnight_restriction"
  | "official_warning"
  | "fine_reported"
  | "road_closed"
  | "access_difficult"
  | "full"
  | "fresh_water_unavailable"
  | "electricity_unavailable"
  | "grey_water_unavailable"
  | "black_water_unavailable"
  | "mud_risk"
  | "fire_or_flood_access_issue";

export type ReportModerationState = "pending" | "confirmed" | "rejected" | "withdrawn";
export type LiveSeverity = "critical" | "serious" | "caution" | "info";
export type LiveTrustLevel = "moderator_confirmed" | "well_supported" | "supported" | "single_report";
export type LiveAccess = "ok" | "caution" | "not_recommended";
export type LiveReportOutcome = "active" | "expired" | "withdrawn" | "rejected";
export type LiveDurationHours = 6 | 12 | 24 | 48;

export interface SpotLiveSummary {
  access: LiveAccess;
  severity: LiveSeverity | "none";
  active_count: number;
  top_type: LiveReportType | null;
  types: LiveReportType[];
  expires_at: string | null;
  /** Haritada pin rozeti gösterilsin mi (karar backend'de). */
  badge: boolean;
}

export interface LiveReportGroup {
  report_type: LiveReportType;
  label: string;
  severity: LiveSeverity;
  reporter_count: number;
  on_site_count: number;
  trust_level: LiveTrustLevel;
  trust_text: string;
  evidence_text: string;
  moderator_confirmed: boolean;
  moderation_state: "confirmed" | "pending";
  latest_reported_at: string;
  expires_at: string;
  remaining_minutes: number;
  remaining_text: string;
  notes: string[];
  my_report_id: string | null;
}

export interface SpotLiveReports {
  spot_id: string;
  generated_at: string;
  summary: SpotLiveSummary;
  headline: string | null;
  groups: LiveReportGroup[];
}

export interface LiveReportRead {
  id: string;
  spot_id: string;
  report_type: LiveReportType;
  label: string;
  moderation_state: ReportModerationState;
  outcome: LiveReportOutcome;
  duration_hours: number | null;
  starts_at: string;
  expires_at: string;
  note: string | null;
  reporter_on_site: boolean;
}

export interface LiveReportActionResponse {
  report: LiveReportRead;
  live: SpotLiveReports;
}

export interface LiveReportHistoryItem {
  id: string;
  report_type: LiveReportType;
  label: string;
  outcome: LiveReportOutcome;
  moderation_state: ReportModerationState;
  starts_at: string;
  expires_at: string;
  reporter_on_site: boolean;
  is_mine: boolean;
}

export interface LiveReportHistoryPage {
  items: LiveReportHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface LiveReportCreatePayload {
  report_type: LiveReportType;
  duration_hours: LiveDurationHours;
  note?: string | null;
}

/** Herkese açık (giriş opsiyonel: token varsa kendi bildirimin `my_report_id` ile işaretlenir). */
export async function fetchLiveReports(spotId: string): Promise<SpotLiveReports> {
  const { data } = await apiClient.get<SpotLiveReports>(`/spots/${spotId}/live-reports`);
  return data;
}

/** Süresi geçmiş / geri çekilmiş / reddedilmiş bildirimler (sayfalı). */
export async function fetchLiveReportHistory(
  spotId: string,
  limit = 10,
  offset = 0,
): Promise<LiveReportHistoryPage> {
  const { data } = await apiClient.get<LiveReportHistoryPage>(`/spots/${spotId}/live-reports/history`, {
    params: { limit, offset },
  });
  return data;
}

/** Kimlik doğrulama gerektirir. Aynı türde aktif bildirimin varsa 409. */
export async function createLiveReport(
  spotId: string,
  payload: LiveReportCreatePayload,
): Promise<LiveReportActionResponse> {
  const { data } = await apiClient.post<LiveReportActionResponse>(`/spots/${spotId}/live-reports`, payload);
  return data;
}

/** Kendi bildirimini geri çeker (satır silinmez). Moderatör/admin başkasınınkini de çekebilir. */
export async function withdrawLiveReport(reportId: string): Promise<LiveReportActionResponse> {
  const { data } = await apiClient.post<LiveReportActionResponse>(`/live-reports/${reportId}/withdraw`);
  return data;
}

// --- Moderasyon (yalnızca moderatör/admin) ---

export type ModerationView = "pending" | "active" | "closed" | "expired";
export type ModerationAction = "confirm" | "reject" | "withdraw";

export interface ModerationEvent {
  id: string;
  report_id: string;
  actor_id: string | null;
  actor_name: string | null;
  actor_role: UserRole;
  from_state: ReportModerationState;
  to_state: ReportModerationState;
  note: string | null;
  created_at: string;
}

export interface ModerationReportRow {
  id: string;
  spot_id: string;
  spot_title: string;
  report_type: LiveReportType;
  label: string;
  severity: LiveSeverity;
  moderation_state: ReportModerationState;
  outcome: LiveReportOutcome;
  duration_hours: number | null;
  starts_at: string;
  expires_at: string;
  note: string | null;
  reporter_id: string | null;
  reporter_name: string | null;
  reporter_on_site: boolean;
  is_legacy: boolean;
  last_event: ModerationEvent | null;
}

export interface ModerationReportPage {
  items: ModerationReportRow[];
  total: number;
  limit: number;
  offset: number;
}

export async function fetchModerationReports(
  view: ModerationView,
  limit = 20,
  offset = 0,
): Promise<ModerationReportPage> {
  const { data } = await apiClient.get<ModerationReportPage>("/moderation/live-reports", {
    params: { view, limit, offset },
  });
  return data;
}

export async function moderateLiveReport(
  reportId: string,
  action: ModerationAction,
  note?: string | null,
): Promise<ModerationReportRow> {
  const { data } = await apiClient.post<ModerationReportRow>(`/moderation/live-reports/${reportId}/action`, {
    action,
    note: note || null,
  });
  return data;
}

export async function fetchModerationEvents(reportId: string): Promise<ModerationEvent[]> {
  const { data } = await apiClient.get<ModerationEvent[]>(`/moderation/live-reports/${reportId}/events`);
  return data;
}

export interface VerificationAuditRow {
  id: string;
  user_id: string;
  check_in_id: string | null;
  field: VerifiableField;
  answer: VerificationAnswer;
  created_at: string;
  is_current: boolean;
}

/** Yalnızca moderatör/admin: bir noktanın tüm saha doğrulama geçmişi (kullanıcı kimlikleriyle). */
export async function fetchVerificationAudit(spotId: string): Promise<VerificationAuditRow[]> {
  const { data } = await apiClient.get<VerificationAuditRow[]>(`/spots/${spotId}/verifications/audit`);
  return data;
}


export interface PlaceResult { label: string; latitude: number; longitude: number; attribution: string; }
export async function searchSpots(q: string, location?: { latitude: number; longitude: number }, radius_km = 25) {
  return (await apiClient.get<SpotFeatureCollection>("/spots/search", { params: { q, ...location, radius_km } })).data;
}
export async function searchPlaces(q: string) {
  return (await apiClient.get<PlaceResult[]>("/places/search", { params: { q } })).data;
}
export type ContentReason = "wrong_location" | "duplicate" | "closed" | "incorrect_information" | "inappropriate" | "other";
export interface ContentReport {
  id: string; spot_id: string; target_kind: "spot" | "photo" | "review"; target_id: string;
  reason: ContentReason; description: string; state: string; resolution_note: string | null;
  created_at: string; resolved_at: string | null;
}
export async function reportContent(spotId: string, payload: Pick<ContentReport,"target_kind"|"target_id"|"reason"|"description">) {
  return (await apiClient.post<ContentReport>(`/spots/${spotId}/content-reports`, payload)).data;
}
export async function fetchContentReports(state = "pending", offset = 0) {
  return (await apiClient.get<ContentReport[]>("/moderation/content-reports", { params: { state, offset } })).data;
}
export async function resolveContentReport(id: string, action: "resolve"|"reject"|"hide", note: string) {
  return (await apiClient.post<ContentReport>(`/moderation/content-reports/${id}/resolve`, { action, note })).data;
}
export interface SpotChange { id: string; action: string; before: Record<string,unknown> | null; after: Record<string,unknown>; created_at: string; }
export async function fetchSpotChanges(id: string, offset = 0) { return (await apiClient.get<SpotChange[]>(`/spots/${id}/changes`, { params: { offset } })).data; }
export async function forgotPassword(email: string) { return (await apiClient.post<{message:string}>("/auth/forgot-password", { email })).data; }
export async function resetPassword(token: string, password: string) { return (await apiClient.post<{message:string}>("/auth/reset-password", { token, password })).data; }
export async function requestEmailVerification() { return (await apiClient.post<{message:string}>("/auth/request-verification")).data; }
export async function verifyEmail(token: string) { return (await apiClient.post<{message:string}>("/auth/verify-email", { token })).data; }
export async function deleteMyAccount(password: string, confirmation: string) { await apiClient.delete("/users/me", { data: {password, confirmation} }); }


export interface TripListSummary { id:string; title:string; is_public:boolean; created_at:string; }
export interface TripItem { id:string; spot_id:string; notes:string|null; position:number; planned_on:string|null; spot:SpotSummary; }
export interface TripList extends TripListSummary { items:TripItem[]; }
export interface TripRoute { geometry:{type:"LineString";coordinates:[number,number][]}; distance_km:number; duration_minutes:number; nearby_spots:SpotSummary[]; notice:string; }
export async function fetchTripLists(){return (await apiClient.get<TripListSummary[]>("/lists")).data;}
export async function createTripList(title:string){return (await apiClient.post<TripList>("/lists",{title,is_public:false})).data;}
export async function fetchTripList(id:string){return (await apiClient.get<TripList>(`/lists/${id}`)).data;}
export async function addTripStop(id:string,spot_id:string){await apiClient.post(`/lists/${id}/items`,{spot_id});}
export async function removeTripStop(id:string,spot_id:string){await apiClient.delete(`/lists/${id}/items/${spot_id}`);}
export async function updateTripStop(id:string,spot_id:string,notes:string|null,planned_on:string|null){return (await apiClient.patch<TripList>(`/lists/${id}/items/${spot_id}`,{notes,planned_on})).data;}
export async function reorderTripStops(id:string,spot_ids:string[]){return (await apiClient.put<TripList>(`/lists/${id}/order`,{spot_ids})).data;}
export async function deleteTripList(id:string){await apiClient.delete(`/lists/${id}`);}
export async function fetchTripRoute(id:string,corridor_km:number){return (await apiClient.get<TripRoute>(`/lists/${id}/route`,{params:{corridor_km}})).data;}
