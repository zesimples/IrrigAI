import type {
  Alert,
  AITextResponse,
  AuditLog,
  AutoCalibrationResult,
  CalibrationHistoryRun,
  ChatResult,
  ChatConversation,
  ChatConversationDetail,
  ChatTurn,
  ProbeCalibrationRun,
  CropProfileTemplate,
  DashboardResponse,
  DetectedWaterEventOut,
  Farm,
  FarmCreate,
  FlowmeterAnalysisResponse,
  FlowmeterDashboardResponse,
  FlowmeterDeviationsResponse,
  FlowmeterEventsResponse,
  FlowmeterFlowRateAlert,
  FlowmeterOut,
  FlowmeterReadingsResponse,
  FlowmeterReferenceOut,
  FlowmeterSectorAnalysisResponse,
  FieldObservation,
  GDDStatus,
  IngestionRunOut,
  IrrigationEvent,
  IrrigationSystemCreate,
  PaginatedResponse,
  Plot,
  PlotCreate,
  Probe,
  ProbeReadingsDiagnosticsResponse,
  ProbeReadingsResponse,
  ProposedAction,
  Recommendation,
  RecommendationDetail,
  RecommendationOutcome,
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

export const TOKEN_KEY = "irrigai_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

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
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    if (res.status === 401) {
      clearToken();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
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
  archive: (id: string) => post<Farm>(`/farms/${id}/archive`),
  unarchive: (id: string) => post<Farm>(`/farms/${id}/unarchive`),
  dashboard: (id: string) => get<DashboardResponse>(`/farms/${id}/dashboard`),
  generateRecommendations: (id: string) =>
    post<Recommendation[]>(`/farms/${id}/recommendations/generate`),
  saveCredentials: (id: string, body: import("@/types").FarmCredentialsInput) =>
    put<import("@/types").FarmCredentialsStatus>(`/farms/${id}/credentials`, body),
  discoverProviderResources: (id: string) =>
    get<import("@/types").ProviderDiscovery>(`/farms/${id}/provider-resources`),
};

// ── Plots ─────────────────────────────────────────────────────────────────────

export const plotsApi = {
  list: (farmId: string, page = 1, pageSize = 50) =>
    get<PaginatedResponse<Plot>>(`/farms/${farmId}/plots?page=${page}&page_size=${pageSize}`),
  get: (id: string) => get<Plot>(`/plots/${id}`),
  create: (farmId: string, body: PlotCreate) => post<Plot>(`/farms/${farmId}/plots`, body),
  update: (id: string, body: Partial<PlotCreate>) => put<Plot>(`/plots/${id}`, body),
  archive: (id: string) => post<Plot>(`/plots/${id}/archive`),
  unarchive: (id: string) => post<Plot>(`/plots/${id}/unarchive`),
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
  archive: (id: string) => post<Sector>(`/sectors/${id}/archive`),
  unarchive: (id: string) => post<Sector>(`/sectors/${id}/unarchive`),
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
  recommendationOutcomes: (id: string, page = 1) =>
    get<PaginatedResponse<RecommendationOutcome>>(
      `/sectors/${id}/recommendation-outcomes?page=${page}`,
    ),
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
  create: (sectorId: string, body: { external_id: string; serial_number?: string }) =>
    post<Probe>(`/sectors/${sectorId}/probes`, body),
  interpret: (id: string) =>
    post<AITextResponse & { interpretation: string }>(`/probes/${id}/interpret`),
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
  readingsDiagnostics: (
    id: string,
    params: { since?: string; until?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    const query = qs.toString();
    return get<ProbeReadingsDiagnosticsResponse>(
      `/probes/${id}/readings/diagnostics${query ? `?${query}` : ""}`,
    );
  },
  waterEvents: (
    id: string,
    params: { since?: string; until?: string; limit?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.limit) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return get<DetectedWaterEventOut[]>(
      `/probes/${id}/water-events${query ? `?${query}` : ""}`,
    );
  },
  refreshWaterEvents: (
    id: string,
    params: { since?: string; until?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    const query = qs.toString();
    return post<DetectedWaterEventOut[]>(
      `/probes/${id}/water-events/refresh${query ? `?${query}` : ""}`,
    );
  },
  ingestionRuns: (
    id: string,
    params: { since?: string; until?: string; limit?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.limit) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return get<IngestionRunOut[]>(
      `/probes/${id}/ingestion-runs${query ? `?${query}` : ""}`,
    );
  },
};

export const waterEventsApi = {
  confirm: (id: string, body: { notes?: string; kind?: string } = {}) =>
    post<DetectedWaterEventOut>(`/water-events/${id}/confirm`, body),
  reject: (id: string, body: { notes?: string } = {}) =>
    post<DetectedWaterEventOut>(`/water-events/${id}/reject`, body),
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
    body: { start_time: string; applied_mm?: number; duration_min?: number; source?: string; notes?: string; recommendation_id?: string },
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
  chat: (
    farmId: string,
    message: string,
    sectorId?: string,
    history: ChatTurn[] = [],
    conversationId?: string,
  ) =>
    post<ChatResult>(`/farms/${farmId}/chat`, {
      message,
      sector_id: sectorId ?? null,
      history,
      conversation_id: conversationId ?? null,
    }),
  conversations: (farmId: string) =>
    get<ChatConversation[]>(`/farms/${farmId}/chat/conversations`),
  conversation: (farmId: string, conversationId: string) =>
    get<ChatConversationDetail>(
      `/farms/${farmId}/chat/conversations/${conversationId}`,
    ),
  deleteConversation: (farmId: string, conversationId: string) =>
    del<void>(`/farms/${farmId}/chat/conversations/${conversationId}`),
  streamChat: async (
    farmId: string,
    body: {
      message: string;
      sector_id?: string | null;
      conversation_id?: string | null;
    },
    callbacks: {
      onDelta: (text: string) => void;
      onConversation?: (conversationId: string, messageId: string) => void;
    },
  ): Promise<ChatResult> => {
    const token = getToken();
    const response = await fetch(`${API_BASE}/farms/${farmId}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, payload.detail ?? response.statusText);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let reply = "";
    let conversationId = body.conversation_id ?? "";
    let messageId = "";
    let donePayload: Partial<ChatResult> = {};

    const consumeEvent = (block: string) => {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) return;
      const payload = JSON.parse(data) as Record<string, unknown>;
      if (event === "conversation") {
        conversationId = String(payload.conversation_id ?? "");
        messageId = String(payload.message_id ?? "");
        callbacks.onConversation?.(conversationId, messageId);
      } else if (event === "delta") {
        const text = String(payload.text ?? "");
        reply += text;
        callbacks.onDelta(text);
      } else if (event === "done") {
        donePayload = payload;
      } else if (event === "error") {
        throw new ApiError(500, String(payload.detail ?? "Erro no assistente."));
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        consumeEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) consumeEvent(buffer);

    return {
      reply,
      conversation_id: conversationId,
      message_id: messageId,
      proposed_action: (donePayload.proposed_action as ProposedAction | null) ?? null,
      degraded: Boolean(donePayload.degraded),
      model_name: (donePayload.model_name as string | null) ?? null,
    };
  },
  explainSector: (sectorId: string, userNotes?: string) =>
    post<AITextResponse & { explanation: string }>(`/sectors/${sectorId}/explain`, {
      user_notes: userNotes ?? null,
    }),
  diagnoseSector: (sectorId: string) =>
    post<AITextResponse & { diagnosis: string }>(`/sectors/${sectorId}/diagnosis`),
  farmSummary: (farmId: string) =>
    post<AITextResponse & { summary: string }>(`/farms/${farmId}/summary`),
  changeAnalysis: (sectorId: string, windowHours = 72) =>
    post<AITextResponse & { analysis: string }>(`/sectors/${sectorId}/change-analysis`, {
      window_hours: windowHours,
    }),
  effectivenessAnalysis: (sectorId: string) =>
    post<AITextResponse & { analysis: string }>(
      `/sectors/${sectorId}/effectiveness-analysis`,
    ),
  missingDataQuestions: (farmId: string) =>
    post<{ questions: string[] }>(`/farms/${farmId}/questions`),
  explainAlert: (alertId: string) =>
    post<AITextResponse & { explanation: string }>(`/alerts/${alertId}/explain`),
  feedback: (body: {
    surface: string;
    rating: -1 | 1;
    farm_id?: string;
    chat_message_id?: string;
    entity_id?: string;
    comment?: string;
  }) => post<{ id: string }>("/ai/feedback", body),
};

export const fieldObservationsApi = {
  list: (sectorId: string, activeOnly = true) =>
    get<FieldObservation[]>(
      `/sectors/${sectorId}/field-observations?active_only=${activeOnly}`,
    ),
  create: (
    sectorId: string,
    body: {
      observation_type: string;
      structured_value?: Record<string, unknown> | null;
      text?: string | null;
      observed_at?: string;
      expires_at?: string | null;
    },
  ) => post<FieldObservation>(`/sectors/${sectorId}/field-observations`, body),
  verify: (observationId: string, isVerified: boolean) =>
    request<FieldObservation>(
      `/field-observations/${observationId}/verification`,
      {
        method: "PATCH",
        body: JSON.stringify({ is_verified: isVerified }),
      },
    ),
  remove: (observationId: string) =>
    del<void>(`/field-observations/${observationId}`),
};

// ── Auto-Calibration ──────────────────────────────────────────────────────────

export const calibrationApi = {
  get: (sectorId: string) => get<AutoCalibrationResult>(`/sectors/${sectorId}/auto-calibration`),
  run: (sectorId: string) => post<ProbeCalibrationRun>(`/sectors/${sectorId}/auto-calibration/run`),
  history: (sectorId: string) =>
    get<CalibrationHistoryRun[]>(`/sectors/${sectorId}/calibration-runs`),
  applyRun: (runId: string) =>
    post<CalibrationHistoryRun>(`/calibration-runs/${runId}/apply`),
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

// ── Flowmeter ─────────────────────────────────────────────────────────────────

export const flowmeterApi = {
  create: (
    sectorId: string,
    body: { external_device_id: number; name: string; serial_number?: string },
  ) => post<FlowmeterOut>(`/sectors/${sectorId}/flowmeter`, body),
  getSector: (sectorId: string) =>
    get<FlowmeterOut>(`/sectors/${sectorId}/flowmeter`),

  readings: (
    sectorId: string,
    params: { since?: string; until?: string; interval?: "15m" | "1h" | "1d" } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.interval) qs.set("interval", params.interval);
    const query = qs.toString();
    return get<FlowmeterReadingsResponse>(
      `/sectors/${sectorId}/flowmeter/readings${query ? `?${query}` : ""}`,
    );
  },

  events: (
    sectorId: string,
    params: { since?: string; until?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    const query = qs.toString();
    return get<FlowmeterEventsResponse>(
      `/sectors/${sectorId}/flowmeter/events${query ? `?${query}` : ""}`,
    );
  },

  dashboard: (farmId: string, period: "7d" | "30d" | "season" = "7d") =>
    get<FlowmeterDashboardResponse>(
      `/farms/${farmId}/flowmeter-dashboard?period=${period}`,
    ),

  analysis: (
    farmId: string,
    params: { period_days: number; language?: string; force_refresh?: boolean },
  ) => post<FlowmeterAnalysisResponse>(`/farms/${farmId}/flowmeter-analysis`, params),

  sectorAnalysis: (
    sectorId: string,
    params: { period_days: number; language?: string; force_refresh?: boolean },
  ) => post<FlowmeterSectorAnalysisResponse>(
    `/sectors/${sectorId}/flowmeter-analysis`,
    params,
  ),

  deviations: (farmId: string, period: "7d" | "30d" | "season" = "7d") =>
    get<FlowmeterDeviationsResponse>(
      `/farms/${farmId}/flowmeter-deviations?period=${period}`,
    ),

  getReference: (sectorId: string) =>
    get<FlowmeterReferenceOut>(`/sectors/${sectorId}/flowmeter-reference`),

  recomputeReference: (sectorId: string) =>
    post<FlowmeterReferenceOut>(`/sectors/${sectorId}/flowmeter-reference/recompute`),

  setManualReference: (
    sectorId: string,
    body: { reference_rate_m3_ha: number; tolerance_pct: number },
  ) => put<FlowmeterReferenceOut>(`/sectors/${sectorId}/flowmeter-reference`, body),

  getFarmReferences: (farmId: string) =>
    get<FlowmeterReferenceOut[]>(`/farms/${farmId}/flowmeter-references`),

  getFlowRateAlerts: (farmId: string) =>
    get<FlowmeterFlowRateAlert[]>(`/farms/${farmId}/flowmeter-flow-rate-alerts`),
};

export { ApiError };
