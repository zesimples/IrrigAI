// Core domain types — mirrors backend schemas

export type CropType = "olive" | "almond" | "maize" | "tomato" | "vineyard" | string;

export type IrrigationSystemType = "drip" | "center_pivot" | "sprinkler" | "flood";

export type SoilTexture = "clay" | "clay_loam" | "loam" | "sandy_loam" | "sand" | "custom";

export type RecommendationAction = "irrigate" | "skip" | "reduce" | "increase" | "defer";

export type ConfidenceLevel = "high" | "medium" | "low";

export type AlertSeverity = "critical" | "warning" | "info";

export type UserRole = "grower" | "farm_manager" | "agronomist" | "admin";

export type IrrigationStrategy = "full_etc" | "rdi" | "deficit" | "custom";

// ── Health ────────────────────────────────────────────────────────────────────

export interface HealthCheck {
  status: "ok" | "degraded";
  checks: { db: "ok" | "error"; redis: "ok" | "error" };
}

// ── Farm ──────────────────────────────────────────────────────────────────────

export interface Farm {
  id: string;
  name: string;
  location_lat: number | null;
  location_lon: number | null;
  region: string | null;
  timezone: string;
  owner_id: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FarmCreate {
  name: string;
  location_lat?: number;
  location_lon?: number;
  region?: string;
  timezone?: string;
}

// ── Plot ──────────────────────────────────────────────────────────────────────

export interface Plot {
  id: string;
  farm_id: string;
  name: string;
  area_ha: number | null;
  field_capacity: number | null;
  wilting_point: number | null;
  soil_texture: string | null;
  soil_preset_id: string | null;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlotCreate {
  name: string;
  area_ha?: number;
  field_capacity?: number;
  wilting_point?: number;
  soil_texture?: string;
  soil_preset_id?: string;
}

// ── Sector ────────────────────────────────────────────────────────────────────

export interface Sector {
  id: string;
  plot_id: string;
  name: string;
  area_ha: number | null;
  crop_type: string;
  variety: string | null;
  planting_year: number | null;
  sowing_date: string | null;
  tree_spacing_m: number | null;
  row_spacing_m: number | null;
  trees_per_ha: number | null;
  current_phenological_stage: string | null;
  irrigation_strategy: IrrigationStrategy;
  deficit_factor: number;
  rainfall_effectiveness: number;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SectorCreate {
  name: string;
  area_ha?: number;
  crop_type: string;
  variety?: string;
  planting_year?: number;
  sowing_date?: string;
  tree_spacing_m?: number;
  row_spacing_m?: number;
  trees_per_ha?: number;
  current_phenological_stage?: string;
  irrigation_strategy?: IrrigationStrategy;
  deficit_factor?: number;
  rainfall_effectiveness?: number;
}

export interface SectorDetail extends Sector {
  irrigation_system: IrrigationSystemOut | null;
  probe_count: number;
}

export interface ProbeHealthSummary {
  probe_id: string;
  external_id: string;
  health_status: string;
  last_reading_at: string | null;
}

export interface SectorStatus {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  current_stage: string | null;
  swc_current: number | null;
  swc_source: string | null;
  depletion_pct: number | null;
  latest_recommendation_id: string | null;
  latest_action: RecommendationAction | null;
  latest_confidence_score: number | null;
  latest_confidence_level: ConfidenceLevel | null;
  latest_irrigation_depth_mm: number | null;
  latest_runtime_min: number | null;
  recommendation_generated_at: string | null;
  active_alerts_critical: number;
  active_alerts_warning: number;
  active_alerts_info: number;
  last_irrigated_at: string | null;
  last_applied_mm: number | null;
  probes: ProbeHealthSummary[];
  data_freshness_hours: number | null;
  stress_projection: StressProjection | null;
}

// ── Irrigation System ─────────────────────────────────────────────────────────

export interface IrrigationSystemOut {
  id: string;
  system_type: IrrigationSystemType;
  emitter_flow_lph: number | null;
  emitter_spacing_m: number | null;
  application_rate_mm_h: number | null;
  efficiency: number;
  distribution_uniformity: number;
  max_runtime_hours: number | null;
  min_irrigation_mm: number | null;
  max_irrigation_mm: number | null;
}

export interface IrrigationSystemCreate {
  system_type: IrrigationSystemType;
  emitter_flow_lph?: number;
  emitter_spacing_m?: number;
  application_rate_mm_h?: number;
  efficiency?: number;
  distribution_uniformity?: number;
  max_runtime_hours?: number;
  min_irrigation_mm?: number;
  max_irrigation_mm?: number;
}

// ── Probe ─────────────────────────────────────────────────────────────────────

export interface Probe {
  id: string;
  sector_id: string;
  external_id: string;
  name: string | null;
  health_status: string;
  last_reading_at: string | null;
  depths: ProbeDepth[];
}

export interface ProbeDepth {
  id: string;
  depth_cm: number;
  field_capacity: number | null;
  wilting_point: number | null;
}

export interface ReadingPoint {
  timestamp: string;
  vwc: number;
  quality: "ok" | "suspect" | "invalid";
}

export interface DepthReadings {
  depth_cm: number;
  readings: ReadingPoint[];
  field_capacity: number | null;
  wilting_point: number | null;
}

export interface ReferenceLines {
  field_capacity: number | null;
  wilting_point: number | null;
}

export type ProbeDetectedEventKind = "irrigation" | "rain" | "unlogged" | "unknown";

export interface ProbeDetectedEvent {
  id: string;
  timestamp: string;
  kind: ProbeDetectedEventKind;
  confidence: ConfidenceLevel;
  depths_cm: number[];
  delta_vwc: number;
  rainfall_mm: number | null;
  irrigation_mm: number | null;
  score: number;
  probability_irrigation: number;
  probability_rain: number;
  probability_unlogged: number;
  source_match_score: number;
  depth_sequence_score: number;
  signal_strength_score: number;
  sensor_quality_score: number;
  message: string;
}

export interface ProbeReadingsResponse {
  probe_id: string;
  depths: DepthReadings[];
  reference_lines: ReferenceLines;
  events: ProbeDetectedEvent[];
}

// ── Recommendation ────────────────────────────────────────────────────────────

export interface Recommendation {
  id: string;
  sector_id: string;
  action: RecommendationAction;
  confidence_score: number;
  confidence_level: ConfidenceLevel;
  irrigation_depth_mm: number | null;
  irrigation_runtime_min: number | null;
  is_accepted: boolean | null;
  accepted_at: string | null;
  override_by: string | null;
  generated_at: string;
}

export interface RecommendationDetail extends Recommendation {
  reasons: RecommendationReason[];
  computation_log: { log: string[] };
  inputs_snapshot: {
    et0_mm?: number;
    depletion_mm?: number;
    taw_mm?: number;
    swc_current?: number;
    kc?: number;
    [key: string]: unknown;
  };
  stress_projection: StressProjection | null;
}

export interface RecommendationReason {
  order: number;
  category: string;
  message_pt: string;
  message_en: string;
  data_key: string | null;
  data_value: string | null;
}

// ── Alert ─────────────────────────────────────────────────────────────────────

export interface Alert {
  id: string;
  sector_id: string | null;
  farm_id: string;
  alert_type: string;
  severity: AlertSeverity;
  title_pt: string;
  title_en: string;
  description_pt: string;
  description_en: string;
  is_active: boolean;
  acknowledged_at: string | null;
  created_at: string;
  data: Record<string, unknown> | null;
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export interface WeatherToday {
  et0_mm: number | null;
  temperature_max_c: number | null;
  temperature_min_c: number | null;
  rainfall_mm: number | null;
  forecast_rain_next_48h_mm: number;
  forecast_rain_probability: number | null;
  humidity_pct: number | null;
  wind_speed_kmh: number | null;
}

export interface AlertCounts {
  critical: number;
  warning: number;
  info: number;
}

export interface SectorSummary {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  current_stage: string | null;
  action: RecommendationAction | null;
  confidence_score: number | null;
  confidence_level: ConfidenceLevel | null;
  irrigation_depth_mm: number | null;
  runtime_min: number | null;
  recommendation_generated_at: string | null;
  /** Total active alerts count */
  active_alerts: number;
  probe_health: string;
  last_irrigated: string | null;
  last_irrigated_mm: number | null;
  rootzone_status: string | null;
  depletion_pct: number | null;
  /** "fresh" | "stale" | "forecast_only" | "no_probe" — null when no recommendation yet */
  source_confidence: string | null;
}

export interface DashboardFarm {
  id: string;
  name: string;
  region: string | null;
}

export interface ProviderSyncStatus {
  provider: string;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_msg: string | null;
  last_latency_ms: number | null;
  last_records_inserted: number;
  consecutive_failures: number;
}

export interface DashboardResponse {
  farm: DashboardFarm;
  date: string;
  weather_today: WeatherToday;
  sectors_summary: SectorSummary[];
  active_alerts_count: AlertCounts;
  missing_data_prompts: string[];
  sync_status: ProviderSyncStatus[];
}

// ── Crop Profile ──────────────────────────────────────────────────────────────

export interface CropStage {
  name: string;
  name_pt?: string;
  start_doy: number;
  end_doy: number;
  kc: number;
  description?: string;
}

export interface CropProfileTemplate {
  id: string;
  crop_type: string;
  name_pt: string;
  name_en: string;
  is_system_default: boolean;
  mad: number;
  root_depth_mature_m: number;
  root_depth_young_m: number;
  maturity_age_years: number | null;
  stages: CropStage[];
  created_at: string;
}

export interface SoilPreset {
  id: string;
  name_pt: string;
  name_en: string;
  texture: string;
  field_capacity: number;
  wilting_point: number;
  taw_mm_per_m: number;
  is_system_default: boolean;
}

export interface SectorCropProfile {
  id: string;
  sector_id: string;
  source_template_id: string | null;
  crop_type: string;
  mad: number;
  root_depth_mature_m: number;
  root_depth_young_m: number;
  maturity_age_years: number | null;
  stages: CropStage[];
  is_customized: boolean;
  field_capacity: number | null;
  wilting_point: number | null;
  soil_preset_id: string | null;
  updated_at: string;
}

// ── Irrigation Event ──────────────────────────────────────────────────────────

export interface IrrigationEvent {
  id: string;
  sector_id: string;
  start_time: string;
  end_time: string | null;
  applied_mm: number | null;
  duration_min: number | null;
  source: string;
  notes: string | null;
}

// ── Sector Override ───────────────────────────────────────────────────────────

export type OverrideType = "fixed_depth" | "fixed_runtime" | "skip" | "force_irrigate";
export type OverrideStrategy = "one_time" | "until_next_stage";

export interface SectorOverride {
  id: string;
  sector_id: string;
  override_type: OverrideType;
  value: number | null;
  reason: string;
  override_strategy: OverrideStrategy;
  valid_until: string | null;
  is_active: boolean;
  created_at: string;
}

export interface SectorOverrideCreate {
  override_type: OverrideType;
  value?: number;
  reason: string;
  valid_until?: string;
  override_strategy?: OverrideStrategy;
}

// ── Audit Log ─────────────────────────────────────────────────────────────────

export interface AuditLog {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  user_id: string | null;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

// ── Pagination ────────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ── Stress Projection ──────────────────────────────────────────────────────────

export interface DayProjection {
  date: string;
  projected_etc_mm: number;
  projected_rain_mm: number;
  projected_depletion_mm: number;
  projected_depletion_pct: number;
  stress_triggered: boolean;
}

export type StressUrgency = "none" | "low" | "medium" | "high";

export interface StressProjection {
  current_depletion_pct: number;
  hours_to_stress: number | null;
  stress_date: string | null;
  urgency: StressUrgency;
  message_pt: string;
  message_en: string;
  projections: DayProjection[];
}

// ── Auto-Calibration ──────────────────────────────────────────────────────────

export interface SoilPresetMatch {
  preset_id: string;
  preset_name_pt: string;
  preset_name_en: string;
  preset_fc_pct: number;
  preset_wp_pct: number;
  distance: number;
}

export interface ObservedSoilPoints {
  observed_fc_pct: number;
  observed_refill_pct: number;
  num_cycles: number;
  consistency: number;
  analysis_depths_cm: number[];
}

export type CalibrationStatus = "validated" | "better_match_found" | "no_good_match";

export interface SoilMatchResult {
  current_preset: SoilPresetMatch | null;
  best_match: SoilPresetMatch;
  all_matches: SoilPresetMatch[];
  status: CalibrationStatus;
}

export interface AutoCalibrationResult {
  sector_id: string;
  sector_name: string;
  observed: ObservedSoilPoints;
  match: SoilMatchResult;
  suggestion_pt: string;
  suggestion_en: string;
  generated_at: string;
  dismissed: boolean;
}

// ── GDD Status ────────────────────────────────────────────────────────────────

export interface GDDStatus {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  reference_date: string;
  accumulated_gdd: number;
  tbase_c: number;
  current_stage: string | null;
  suggested_stage: string | null;
  suggested_stage_name_pt: string | null;
  suggested_stage_name_en: string | null;
  stage_changed: boolean;
  days_in_current_stage: number | null;
  next_stage: string | null;
  next_stage_name_pt: string | null;
  gdd_to_next_stage: number | null;
  confidence: "high" | "low";
  missing_weather_days: number;
  suggestion_pt: string | null;
  suggestion_en: string | null;
}
