import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EditorialSectorCard } from "../SectorCard";
import type { SectorSummary } from "@/types";

const base: SectorSummary = {
  sector_id: "s1", sector_name: "S1 - Vinha Norte", crop_type: "vine",
  plot_id: "p1", plot_name: "P1", current_stage: null,
  action: "irrigate", irrigation_depth_mm: 6, runtime_min: null,
  confidence_level: "high", confidence_score: 0.9,
  rootzone_status: "dry", depletion_pct: 55, active_alerts: 0,
  probe_health: "ok", last_irrigated: null, last_irrigated_mm: null,
  recommendation_generated_at: null, source_confidence: "fresh",
  dose_band: "reforcada", dose_source: "mm_only",
  habitual_factor: null, estimated_runtime_min: null,
} as SectorSummary;

describe("EditorialSectorCard dose-do-dia", () => {
  it("shows the band pill and mm headline", () => {
    render(<EditorialSectorCard sector={base} farmId="f1" />);
    expect(screen.getByText("Rega reforçada")).toBeInTheDocument();
    expect(screen.getByText(/Aplicar 6 mm hoje/)).toBeInTheDocument();
  });

  it("shows habitual-factor headline for probe_learned", () => {
    render(
      <EditorialSectorCard
        sector={{ ...base, dose_band: "normal", dose_source: "probe_learned", habitual_factor: 1.3, estimated_runtime_min: 155 }}
        farmId="f1"
      />
    );
    expect(screen.getByText(/1\.3× a rega habitual/)).toBeInTheDocument();
  });

  it("falls back to legacy band for old recommendations", () => {
    render(
      <EditorialSectorCard sector={{ ...base, dose_band: null, action: "skip" }} farmId="f1" />
    );
    expect(screen.getByText("Pode saltar")).toBeInTheDocument();
  });

  it("shows a distinct no-recommendation state instead of a false 'Pode saltar'", () => {
    render(
      <EditorialSectorCard sector={{ ...base, dose_band: null, action: null }} farmId="f1" />
    );
    expect(screen.getByText("Sem recomendação gerada.")).toBeInTheDocument();
    expect(screen.getByText("Sem recomendação")).toBeInTheDocument();
    expect(screen.queryByText("Pode saltar")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/sem recomenda/i)).toBeInTheDocument();
  });
});
