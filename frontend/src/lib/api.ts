import type {
  Alert,
  AuditLog,
  AutoCalibrationResult,
  CropProfileTemplate,
  DashboardResponse,
  Farm,
  FarmCreate,
  GDDStatus,
  IrrigationEvent,
  IrrigationSystemCreate,
  PaginatedResponse,
  Plot,
  PlotCreate,
  Probe,
  ProbeReadingsResponse,
  Recommendation,
  RecommendationDetail,
  Sector,
  SectorCreate,
  SectorCropProfile,
  SectorDetail,
  SectorOverride,
  SectorOverrideCreate,
  SectorStatus,
  SoilPreset,
  StressProjection,
} from "@/types";

// In production (Docker) this is a relative path — Next.js rewrites proxy it
// to the backend container. In local dev outside Docker, set NEXT_PUBLIC_API_URL
// in .env to http://localhost:8000/api/v1 to bypass the proxy.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function get<T>(path: string) {
  return request<T>(path, { method: "GET" });
}

function post<T>(path: string, body?: unknown) {
  return request<T>(path, {
    method: "POST",
    body: body != null ? JSON.stringify(body) : undefined,
  });
}

function put<T>(path: string, body?: unknown) {
  return request<T>(path, {
    method: "PUT",
    body: body != null ? JSON.stringify(body) : undefined,
  });
}

function del<T>(path: string) {
  return request<T>(path, { method: "DELETE" });
}

// ── Farms ─────────────────────────────────────────────────────────────────────

export const farmsApi = {
  list: () => get<PaginatedResponse<Farm>>("/farms").then((r) => r.items),
  get: (id: string) => get<Farm>(`/farms/${id}`),
  create: (body: FarmCreate) => post<Farm>("/farms", body),
  update: (id: string, body: Partial<FarmCreate>) => put<Farm>(`/farms/${id}`, body),
  dashboard: (id: string) => get<DashboardResponse>(`/farms/${id}/dashboard`),
  generateRecommendations: (id: string) =>
    post<Recommendation[]>(`/farms/${id}/recommendations/generate`),
};

// ── Plots ─────────────────────────────────────────────────────────────────────

export const plotsApi = {
  list: (farmId: string, page = 1, pageSize = 50) =>
    get<PaginatedResponse<Plot>>(`/farms/${farmId}/plots?page=${page}&page_size=${pageSize}`),
  get: (id: string) => get<Plot>(`/plots/${id}`),
  create: (farmId: string, body: PlotCreate) => post<Plot>(`/farms/${farmId}/plots`, body),
  update: (id: string, body: Partial<PlotCreate>) => put<Plot>(`/plots/${id}`, body),
};

// ── Sectors ───────────────────────────────────────────────────────────────────

export const sectorsApi = {
  list: (plotId: string, page = 1, pageSize = 50) =>
    get<PaginatedResponse<Sector>>(`/plots/${plotId}/sectors?page=${page}&page_size=${pageSize}`),
  get: (id: string) => get<SectorDetail>(`/sectors/${id}`),
  getStatus: (id: string) => get<SectorStatus>(`/sectors/${id}/status`),
  create: (plotId: string, body: SectorCreate) =>
    post<Sector>(`/plots/${plotId}/sectors`, body),
  update: (id: string, body: Partial<SectorCreate>) => put<Sector>(`/sectors/${id}`, body),
  createIrrigationSystem: (id: string, body: IrrigationSystemCreate) =>
    post(`/sectors/${id}/irrigation-systems`, body),
  generateRecommendation: (id: string) =>
    post<Recommendation>(`/sectors/${id}/recommendations/generate`),
  listRecommendations: (id: string, page = 1) =>
    get<PaginatedResponse<Recommendation>>(
      `/sectors/${id}/recommendations?page=${page}`,
    ),
  listAlerts: (id: string) =>
    get<PaginatedResponse<Alert>>(`/sectors/${id}/alerts`),
  stressProjection: (id: string) => get<StressProjection>(`/sectors/${id}/stress-projection`),
  cropProfile: (id: string) => get<SectorCropProfile>(`/sectors/${id}/crop-profile`),
  updateCropProfile: (id: string, body: Partial<SectorCropProfile>) =>
    put<SectorCropProfile>(`/sectors/${id}/crop-profile`, body),
  resetCropProfile: (id: string, templateId: string) =>
    post<SectorCropProfile>(`/sectors/${id}/crop-profile/reset`, { template_id: templateId }),
};

// ── Probes ────────────────────────────────────────────────────────────────────

export const probesApi = {
  list: (sectorId: string) => get<Probe[]>(`/sectors/${sectorId}/probes`),
  get: (id: string) => get<Probe>(`/probes/${id}`),
  readings: (
    id: string,
    params: {
      since?: string;
      until?: string;
      depth_cm?: string;
      interval?: string;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.depth_cm) qs.set("depth_cm", params.depth_cm);
    if (params.interval) qs.set("interval", params.interval);
    const query = qs.toString();
    return get<ProbeReadingsResponse>(`/probes/${id}/readings${query ? `?${query}` : ""}`);
  },
};

// ── Recommendations ───────────────────────────────────────────────────────────

export const recommendationsApi = {
  get: (id: string) => get<RecommendationDetail>(`/recommendations/${id}`),
  accept: (id: string, notes?: string) =>
    post<Recommendation>(`/recommendations/${id}/accept`, { notes }),
  reject: (id: string, notes?: string) =>
    post<Recommendation>(`/recommendations/${id}/reject`, { notes }),
  override: (
    id: string,
    body: {
      custom_action?: string;
      custom_depth_mm?: number;
      custom_runtime_min?: number;
      override_reason: string;
      override_strategy?: "one_time" | "until_next_stage";
    },
  ) => post<Recommendation>(`/recommendations/${id}/override`, body),
};

// ── Alerts ────────────────────────────────────────────────────────────────────

export const alertsApi = {
  listFarm: (farmId: string) =>
    get<PaginatedResponse<Alert>>(`/farms/${farmId}/alerts`),
  resolve: (id: string) => post<Alert>(`/alerts/${id}/resolve`),
  resolveAll: (farmId: string) =>
    post<{ resolved: number; farm_id: string }>(`/farms/${farmId}/alerts/resolve-all`),
};

// ── Irrigation ────────────────────────────────────────────────────────────────

export const irrigationApi = {
  list: (sectorId: string) =>
    get<PaginatedResponse<IrrigationEvent>>(`/sectors/${sectorId}/irrigation-events`),
  create: (
    sectorId: string,
    body: { start_time: string; applied_mm?: number; duration_min?: number; source?: string; notes?: string },
  ) => post<IrrigationEvent>(`/sectors/${sectorId}/irrigation-events`, body),
};

// ── Crop Profiles & Soil Presets ──────────────────────────────────────────────

export const catalogApi = {
  cropProfileTemplates: () => get<CropProfileTemplate[]>("/crop-profile-templates"),
  cropProfileTemplate: (id: string) =>
    get<CropProfileTemplate>(`/crop-profile-templates/${id}`),
  soilPresets: () => get<SoilPreset[]>("/soil-presets"),
};

// ── Overrides ─────────────────────────────────────────────────────────────────

export const overridesApi = {
  list: (sectorId: string, activeOnly = true) =>
    get<SectorOverride[]>(`/sectors/${sectorId}/overrides?active_only=${activeOnly}`),
  create: (sectorId: string, body: SectorOverrideCreate) =>
    post<SectorOverride>(`/sectors/${sectorId}/overrides`, body),
  remove: (overrideId: string) => del<void>(`/overrides/${overrideId}`),
};

// ── Audit Log ─────────────────────────────────────────────────────────────────

export const auditApi = {
  list: (params: { entity_type?: string; action?: string; entity_id?: string; page?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.entity_type) qs.set("entity_type", params.entity_type);
    if (params.action) qs.set("action", params.action);
    if (params.entity_id) qs.set("entity_id", params.entity_id);
    if (params.page) qs.set("page", String(params.page));
    const query = qs.toString();
    return get<PaginatedResponse<AuditLog>>(`/audit-log${query ? `?${query}` : ""}`);
  },
};

// ── AI Chat ───────────────────────────────────────────────────────────────────

export const chatApi = {
  chat: (farmId: string, message: string, sectorId?: string) =>
    post<{ reply: string }>(`/farms/${farmId}/chat`, {
      message,
      sector_id: sectorId ?? null,
    }),
  explainSector: (sectorId: string, userNotes?: string) =>
    post<{ explanation: string }>(`/sectors/${sectorId}/explain`, {
      user_notes: userNotes ?? null,
    }),
  farmSummary: (farmId: string) =>
    post<{ summary: string }>(`/farms/${farmId}/summary`),
  missingDataQuestions: (farmId: string) =>
    post<{ questions: string[] }>(`/farms/${farmId}/questions`),
  explainAlert: (alertId: string) =>
    post<{ explanation: string }>(`/alerts/${alertId}/explain`),
};

// ── Auto-Calibration ──────────────────────────────────────────────────────────

export const calibrationApi = {
  get: (sectorId: string) => get<AutoCalibrationResult>(`/sectors/${sectorId}/auto-calibration`),
  accept: (sectorId: string) => post<{ accepted: boolean; preset_name_pt: string; preset_name_en: string }>(`/sectors/${sectorId}/auto-calibration/accept`),
  dismiss: (sectorId: string) => post<{ dismissed: boolean; dismissed_until: string }>(`/sectors/${sectorId}/auto-calibration/dismiss`),
};

// ── GDD Phenology ─────────────────────────────────────────────────────────────

export const gddApi = {
  getSector: (sectorId: string) => get<GDDStatus>(`/sectors/${sectorId}/gdd-status`),
  getFarm: (farmId: string) => get<GDDStatus[]>(`/farms/${farmId}/gdd-status`),
  confirm: (sectorId: string, stage?: string) =>
    post<{ confirmed: boolean; stage: string }>(`/sectors/${sectorId}/gdd-status/confirm`, { stage: stage ?? null }),
};

export { ApiError };
