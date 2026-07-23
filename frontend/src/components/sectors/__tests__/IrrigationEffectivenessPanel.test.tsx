import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IrrigationEffectivenessPanel } from "../IrrigationEffectivenessPanel";

vi.mock("@/lib/api", () => ({
  sectorsApi: {
    recommendationOutcomes: vi.fn(),
  },
  calibrationApi: {
    history: vi.fn(),
    applyRun: vi.fn(),
  },
  probesApi: {
    readingsDiagnostics: vi.fn(),
  },
  chatApi: {
    effectivenessAnalysis: vi.fn(),
    changeAnalysis: vi.fn(),
  },
}));

import { calibrationApi, chatApi, probesApi, sectorsApi } from "@/lib/api";

describe("IrrigationEffectivenessPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(sectorsApi.recommendationOutcomes).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    vi.mocked(calibrationApi.history).mockResolvedValue([
      {
        id: "run-1",
        sector_id: "sector-1",
        observed_fc: 0.24,
        observed_refill: 0.14,
        method: "cycles",
        num_cycles: 4,
        consistency: 0.8,
        window_days: 30,
        computed_at: "2026-07-23T08:00:00Z",
        source: "scheduled",
        status: "candidate",
        previous_fc: 0.22,
        previous_refill: 0.13,
        applied_at: null,
      },
    ]);
    vi.mocked(probesApi.readingsDiagnostics).mockResolvedValue({
      probe_id: "probe-1",
      external_id: "ext-1",
      since: "2026-07-16T08:00:00Z",
      until: "2026-07-23T08:00:00Z",
      probe_last_reading_at: "2026-07-23T07:00:00Z",
      depth_count: 2,
      total_readings: 40,
      overall_status: "ok",
      expected_interval_minutes: 60,
      max_gap_minutes: 120,
      gap_count: 1,
      suggested_backfill_hours: 0,
      depths: [],
    });
  });

  it("shows calibration candidates, outcomes empty state, and diagnostics", async () => {
    render(
      <IrrigationEffectivenessPanel
        sectorId="sector-1"
        probeId="probe-1"
      />,
    );

    expect(await screen.findByText("Eficácia da rega")).toBeInTheDocument();
    expect(screen.getByText(/Ainda não existem recomendações/)).toBeInTheDocument();
    expect(screen.getByText("Aplicar")).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
  });

  it("requests the grounded effectiveness explanation", async () => {
    vi.mocked(chatApi.effectivenessAnalysis).mockResolvedValue({
      analysis: "ok",
      structured: {
        summary: "A dotação aplicada ficou próxima da recomendada.",
        risk_level: "low",
        irrigation_advice: "Manter a verificação da resposta da sonda.",
        evidence: [],
        missing_data: [],
        confidence_score: 0.8,
        confidence_explanation: "Existem resultados recentes.",
        recommended_actions: [],
      },
    });
    render(<IrrigationEffectivenessPanel sectorId="sector-1" />);

    fireEvent.click(await screen.findByText("Explicar eficácia com IA"));

    await waitFor(() =>
      expect(chatApi.effectivenessAnalysis).toHaveBeenCalledWith("sector-1"),
    );
    expect(
      await screen.findByText("A dotação aplicada ficou próxima da recomendada."),
    ).toBeInTheDocument();
  });
});
