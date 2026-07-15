// Core domain types — mirrors backend schemas

export type CropType = "olive" | "almond" | "maize" | "tomato" | "vineyard" | string;

export type IrrigationSystemType = "drip" | "center_pivot" | "sprinkler" | "flood";

export type SoilTexture = "clay" | "clay_loam" | "loam" | "sandy_loam" | "sand" | "custom";

export type RecommendationAction = "irrigate" | "skip" | "reduce" | "increase" | "defer";

export type DoseBand = "reforcada" | "normal" | "curta" | "pode_saltar";

export type DoseSource = "configured" | "probe_learned" | "mm_only";

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
  elevation_m: number | null;
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
  elevation_m?: number;
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
  plot_id: string | null;
  plot_name: string | null;
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
  calibration_available?: boolean;
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

export interface FarmCredentialsInput {
  username: string;
  password: string;
  client_id: string;
  client_secret: string;
  project_id?: string;
  weather_device_id?: string;
}

export interface FarmCredentialsStatus {
  configured: boolean;
  has_username: boolean;
  has_password: boolean;
  has_client_id: boolean;
  has_client_secret: boolean;
  project_id: string | null;
  weather_device_id: string | null;
}

export interface ProviderResource {
  id: string;
  name: string;
  kind: string | null;
  project_id: string | null;
  serial_number: string | null;
}

export interface ProviderDiscovery {
  projects: ProviderResource[];
  devices: ProviderResource[];
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
  status?: DetectedWaterEventStatus;
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
  rootzone_swc?: { timestamp: string; vwc: number; quality?: string }[];
  root_depth_cm?: number | null;
}

export interface ProbeReadingGap {
  start: string;
  end: string;
  duration_minutes: number;
  expected_missing_readings: number;
}

export type ProbeDiagnosticsStatus = "ok" | "partial" | "stale" | "no_data";

export interface ProbeDepthDiagnostics {
  depth_cm: number;
  sensor_type: string;
  unit: string | null;
  reading_count: number;
  first_reading_at: string | null;
  last_reading_at: string | null;
  latest_quality: string | null;
  quality_counts: Record<string, number>;
  median_interval_minutes: number | null;
  expected_interval_minutes: number | null;
  max_gap_minutes: number | null;
  gap_threshold_minutes: number | null;
  gap_count: number;
  gaps: ProbeReadingGap[];
  coverage_pct: number | null;
  freshness_hours: number | null;
  status: ProbeDiagnosticsStatus;
  notes: string[];
}

export interface ProbeReadingsDiagnosticsResponse {
  probe_id: string;
  external_id: string;
  since: string;
  until: string;
  probe_last_reading_at: string | null;
  depth_count: number;
  total_readings: number;
  overall_status: ProbeDiagnosticsStatus;
  expected_interval_minutes: number | null;
  max_gap_minutes: number | null;
  gap_count: number;
  suggested_backfill_hours: number;
  depths: ProbeDepthDiagnostics[];
}

// ── Persisted Water Events ────────────────────────────────────────────────────

export type DetectedWaterEventStatus = "active" | "confirmed" | "rejected";

export interface DetectedWaterEventOut {
  id: string;
  probe_id: string;
  sector_id: string;
  farm_id: string | null;
  timestamp: string;
  kind: ProbeDetectedEventKind;
  confidence: ConfidenceLevel;
  score: number;
  probability_irrigation: number;
  probability_rain: number;
  probability_unlogged: number;
  source_match_score: number;
  depth_sequence_score: number;
  signal_strength_score: number;
  sensor_quality_score: number;
  depths_cm: number[];
  delta_vwc: number;
  rainfall_mm: number | null;
  irrigation_mm: number | null;
  matched_irrigation_event_id: string | null;
  matched_weather_observation_id: string | null;
  status: DetectedWaterEventStatus;
  confirmed_by: string | null;
  confirmed_at: string | null;
  notes: string | null;
  message: string;
  created_at: string;
  updated_at: string;
}

// ── AI Structured Output ─────────────────────────────────────────────────────

export interface AgronomicEvidence {
  source: string;
  value: string;
}

export interface AgronomicInterpretation {
  summary: string;
  risk_level: "low" | "medium" | "high";
  irrigation_advice: string;
  evidence: AgronomicEvidence[];
  missing_data: string[];
  confidence_score: number;
  confidence_explanation: string;
  recommended_actions: string[];
}

export interface AITextResponse {
  reply?: string;
  explanation?: string;
  summary?: string;
  diagnosis?: string;
  interpretation?: string;
  analysis?: string;
  structured?: AgronomicInterpretation | null;
}

// ── Provider Ingestion Runs ──────────────────────────────────────────────────

export interface IngestionRunOut {
  id: string;
  farm_id: string;
  probe_id: string | null;
  probe_external_id: string | null;
  provider: string;
  source_type: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  latency_ms: number | null;
  requested_since: string | null;
  requested_until: string | null;
  provider_first_timestamp: string | null;
  provider_last_timestamp: string | null;
  provider_records_seen: number;
  provider_records_parsed: number;
  skipped_null: number;
  skipped_sentinel: number;
  skipped_unknown_depth: number;
  skipped_duplicate: number;
  inserted: number;
  flagged_invalid: number;
  flagged_suspect: number;
  error_message: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
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
  dose_band?: DoseBand | null;
  dose_source?: DoseSource | null;
  habitual_factor?: number | null;
  estimated_runtime_min?: number | null;
  fingerprint_n_events?: number | null;
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
  plot_id: string;
  plot_name: string;
  current_stage: string | null;
  action: RecommendationAction | null;
  confidence_score: number | null;
  confidence_level: ConfidenceLevel | null;
  irrigation_depth_mm: number | null;
  runtime_min: number | null;
  dose_band: DoseBand | null;
  dose_source: DoseSource | null;
  habitual_factor: number | null;
  estimated_runtime_min: number | null;
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
  /** Plot-scoped weather keyed by plot_id — only plots with their own station/forecast. */
  weather_by_plot?: Record<string, WeatherToday>;
  sectors_summary: SectorSummary[];
  active_alerts_count: AlertCounts;
  missing_data_prompts: string[];
  sync_status: ProviderSyncStatus[];
  has_flowmeters?: boolean;
}

// ── Crop Profile ──────────────────────────────────────────────────────────────

export interface CropStage {
  key: string;
  name_pt?: string;
  name_en?: string;
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

// Result of the manual deterministic calibration run (POST .../auto-calibration/run).
// observed_fc = calibrated CC; observed_refill = effective refill / operational lower bound.
export interface ProbeCalibrationRun {
  sector_id: string;
  observed_fc: number;
  observed_refill: number;
  method: string;
  num_cycles: number;
  consistency: number;
  window_days: number;
  computed_at: string;
  max_age_days: number;
  // Effective bounds the engine used before vs. now (the CC/refill the chart shows).
  previous_fc: number | null;
  previous_refill: number | null;
  effective_fc: number | null;
  effective_pwp: number | null;
  effective_source: string;
  changed: boolean;        // effective bounds moved before→after
  applied: boolean;        // calibration is what the engine now uses
  cleared_customization: boolean; // the run overrode a prior manual soil setting
}

export interface CalibrationHistoryRun {
  id: string;
  sector_id: string;
  observed_fc: number;
  observed_refill: number;
  method: string;
  num_cycles: number;
  consistency: number;
  window_days: number;
  computed_at: string;
  source: string;
  status: "candidate" | "applied" | "superseded";
  previous_fc: number | null;
  previous_refill: number | null;
  applied_at: string | null;
}

export interface RecommendationOutcome {
  id: string;
  recommendation_id: string;
  sector_id: string;
  irrigation_event_id: string | null;
  detected_event_id: string | null;
  evaluated_at: string;
  status: "executed" | "followed_skip" | "no_event";
  recommended_depth_mm: number | null;
  actual_applied_mm: number | null;
  dose_error_mm: number | null;
  dose_error_pct: number | null;
  pre_irrigation_vwc: number | null;
  post_irrigation_vwc: number | null;
  probe_response_delta: number | null;
  details: Record<string, unknown>;
}

// ── Flowmeter ─────────────────────────────────────────────────────────────────

export interface FlowmeterOut {
  id: string;
  sector_id: string;
  external_device_id: number;
  serial_number: string | null;
  name: string;
  is_active: boolean;
  last_reading_at: string | null;
}

export interface FlowmeterReadingPoint {
  timestamp: string;
  value: number;
}

export interface FlowmeterReadingsResponse {
  flowmeter_id: string;
  sector_name: string;
  crop: string;
  unit: string;
  interval: string;
  readings: FlowmeterReadingPoint[];
}

export interface IrrigationEventOut {
  id: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  total_m3_ha: number;
  date: string;
}

export interface FlowmeterEventsSummary {
  total_events: number;
  total_m3_ha: number;
  avg_m3_ha_per_event: number;
  period_days: number;
}

export interface FlowmeterEventsResponse {
  events: IrrigationEventOut[];
  summary: FlowmeterEventsSummary;
}

export interface SectorDailyBreakdown {
  date: string;
  m3_ha: number;
}

export interface FlowmeterSectorDashboard {
  sector_id: string;
  sector_name: string;
  crop: string;
  has_flowmeter: boolean;
  total_m3_ha: number;
  num_events: number;
  last_irrigation: string | null;
  last_event_m3_ha: number | null;
  daily_breakdown: SectorDailyBreakdown[];
}

export interface CropSummary {
  total_m3_ha: number;
  num_sectors: number;
  num_events: number;
}

export interface FlowmeterDashboardResponse {
  farm_name: string;
  period: string;
  period_start: string;
  period_end: string;
  total_m3_ha: number;
  sectors: FlowmeterSectorDashboard[];
  by_crop: Record<string, CropSummary>;
}

// ── Flowmeter AI Analysis ─────────────────────────────────────────────────────

export interface FlowmeterCropStats {
  total_m3_ha: number;
  avg_per_sector: number;
  avg_per_event: number;
  num_events: number;
}

export interface FlowmeterAnalysisStatistics {
  total_m3_ha: number;
  total_events: number;
  sectors_with_data: number;
  sectors_without_data: number;
  by_crop: Record<string, FlowmeterCropStats>;
  stopped_sectors: string[];
  top_consumers: string[];
  trend: string;
  typical_start_hour: number | null;
}

export interface FlowmeterSectorStatistics {
  total_m3_ha: number;
  num_events: number;
  avg_m3_ha_per_event: number;
  avg_interval_days: number | null;
  pattern: string;
  consistency_score: number;
  vs_crop_avg_pct: number | null;
  typical_start_hour: number | null;
  avg_duration_minutes: number | null;
}

export interface FlowmeterAnalysisResponse {
  analysis: string;
  statistics: FlowmeterAnalysisStatistics;
}

export interface FlowmeterSectorAnalysisResponse {
  analysis: string;
  statistics: FlowmeterSectorStatistics;
}

export interface FlowmeterDeviationSector {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  status: "normal" | "info" | "warning" | "insufficient_data" | "insufficient_peer_data";
  direction: "above" | "below" | null;
  deviation_pct: number | null;
  absolute_delta_m3ha: number | null;
  sector_avg_m3ha: number | null;
  crop_avg_m3ha: number | null;
  event_count: number;
  peer_sector_count: number;
}

export interface FlowmeterInsufficientDataSector {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  event_count: number;
  reason: "insufficient_events" | "insufficient_peers";
}

export interface FlowmeterDeviationsResponse {
  period_days: number;
  sectors: FlowmeterDeviationSector[];
  deviating: FlowmeterDeviationSector[];
  insufficient_data: FlowmeterInsufficientDataSector[];
  crop_averages: Record<string, number>;
  evaluated_at: string;
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

// ── Flowmeter flow rate reference ─────────────────────────────────────────────

export interface FlowmeterReferenceOut {
  id: string;
  flowmeter_id: string;
  reference_rate_m3_ha: number | null;
  tolerance_pct: number;
  upper_limit_m3_ha: number | null;
  lower_limit_m3_ha: number | null;
  num_events_analyzed: number;
  std_dev: number;
  status: "established" | "provisional" | "insufficient";
  computed_at: string;
  is_manual_override: boolean;
  sector_id: string | null;
  sector_name: string | null;
  crop_type: string | null;
}

export interface FlowmeterFlowRateAlert {
  id: string;
  alert_type: "flowmeter_flow_rate_high" | "flowmeter_flow_rate_low" | "flowmeter_mid_event_zeros";
  severity: "warning" | "info";
  title_pt: string;
  title_en: string;
  description_pt: string;
  description_en: string;
  sector_id: string | null;
  is_active: boolean;
  created_at: string | null;
  data: {
    stable_rate_m3_ha?: number;
    reference_rate_m3_ha?: number;
    deviation_pct?: number;
    event_start_time?: string;
    zero_count?: number;
  } | null;
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export type ProposedActionType =
  | "override_recommendation"
  | "accept_recommendation"
  | "reject_recommendation"
  | "regenerate_recommendation"
  | "run_calibration";

export interface ProposedAction {
  type: ProposedActionType;
  summary: string;
  sector_id?: string | null;
  recommendation_id?: string | null;
  params: Record<string, unknown>;
}

export interface ChatResult {
  reply: string;
  proposed_action: ProposedAction | null;
}
