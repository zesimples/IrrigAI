import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SectorGrid } from "../SectorGrid";
import type { SectorSummary } from "@/types";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function sector(overrides: Partial<SectorSummary>): SectorSummary {
  return {
    sector_id: overrides.sector_id ?? "sector-1",
    sector_name: overrides.sector_name ?? "Sector 1",
    crop_type: overrides.crop_type ?? "olive",
    plot_id: overrides.plot_id ?? "plot-1",
    plot_name: overrides.plot_name ?? "Fátima",
    current_stage: null,
    action: overrides.action ?? "irrigate",
    confidence_score: 0.9,
    confidence_level: "high",
    irrigation_depth_mm: 12,
    runtime_min: 90,
    dose_band: overrides.dose_band ?? null,
    dose_source: null,
    habitual_factor: null,
    estimated_runtime_min: null,
    recommendation_generated_at: "2026-07-03T06:00:00Z",
    active_alerts: 0,
    probe_health: "ok",
    last_irrigated: null,
    last_irrigated_mm: null,
    rootzone_status: "optimal",
    depletion_pct: 40,
    source_confidence: "fresh",
  };
}

// Single crop across two plots → SectorGrid tabs by plot (Innoliva pattern).
const sectors = [
  sector({ sector_id: "s1", plot_id: "plot-1", plot_name: "Fátima", action: "irrigate" }),
  sector({ sector_id: "s2", plot_id: "plot-2", plot_name: "Rocio", action: "skip" }),
];

describe("SectorGrid onPlotChange", () => {
  beforeEach(() => {
    replaceMock.mockClear();
  });

  it("reports the initial active plot on mount", () => {
    const onPlotChange = vi.fn();
    render(<SectorGrid sectors={sectors} farmId="farm-1" onPlotChange={onPlotChange} />);
    // Tabs sorted with irrigate-plots first → Fátima (plot-1) is the initial tab.
    expect(onPlotChange).toHaveBeenCalledWith("plot-1");
  });

  it("reports the newly selected plot when the user switches tab", () => {
    const onPlotChange = vi.fn();
    render(<SectorGrid sectors={sectors} farmId="farm-1" onPlotChange={onPlotChange} />);

    fireEvent.click(screen.getByRole("tab", { name: /Rocio/ }));
    expect(onPlotChange).toHaveBeenLastCalledWith("plot-2");
  });

  it("reports null in crop tab mode (plot tabs not shown)", () => {
    const onPlotChange = vi.fn();
    const mixedCrops = [
      sector({ sector_id: "s1", crop_type: "olive" }),
      sector({ sector_id: "s2", crop_type: "vine", plot_id: "plot-2", plot_name: "Rocio" }),
    ];
    render(<SectorGrid sectors={mixedCrops} farmId="farm-1" onPlotChange={onPlotChange} />);
    expect(onPlotChange).toHaveBeenCalledWith(null);
  });
});
