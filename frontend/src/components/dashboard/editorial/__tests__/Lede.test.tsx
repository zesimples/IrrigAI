import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Lede } from "../Lede";
import type { SectorSummary, WeatherToday } from "@/types";

const weather: WeatherToday = {
  et0_mm: 7.7,
  temperature_max_c: 34,
  temperature_min_c: 18,
  rainfall_mm: 0,
  forecast_rain_next_48h_mm: 0,
  forecast_rain_probability: null,
  humidity_pct: 41,
  wind_speed_kmh: 12,
};

function sector(overrides: Partial<SectorSummary>): SectorSummary {
  return {
    sector_id: overrides.sector_id ?? "sector-1",
    sector_name: overrides.sector_name ?? "Sector 1",
    crop_type: overrides.crop_type ?? "olive",
    plot_id: overrides.plot_id ?? "plot-1",
    plot_name: overrides.plot_name ?? "Olival",
    current_stage: overrides.current_stage ?? "olive_pit_hardening",
    action: overrides.action ?? "irrigate",
    confidence_score: overrides.confidence_score ?? 0.9,
    confidence_level: overrides.confidence_level ?? "high",
    irrigation_depth_mm: overrides.irrigation_depth_mm ?? 12,
    runtime_min: overrides.runtime_min ?? 90,
    dose_band: overrides.dose_band ?? null,
    dose_source: overrides.dose_source ?? null,
    habitual_factor: overrides.habitual_factor ?? null,
    estimated_runtime_min: overrides.estimated_runtime_min ?? null,
    recommendation_generated_at: overrides.recommendation_generated_at ?? "2026-07-03T06:00:00Z",
    active_alerts: overrides.active_alerts ?? 0,
    probe_health: overrides.probe_health ?? "ok",
    last_irrigated: overrides.last_irrigated ?? null,
    last_irrigated_mm: overrides.last_irrigated_mm ?? null,
    rootzone_status: overrides.rootzone_status ?? "deficit",
    depletion_pct: overrides.depletion_pct ?? 55,
    source_confidence: overrides.source_confidence ?? "fresh",
  };
}

describe("Lede", () => {
  it("does not say the whole olive crop can wait when some olive sectors need reinforced irrigation", () => {
    render(
      <Lede
        farmName="Innoliva"
        region="Alentejo"
        weather={weather}
        sectors={[
          sector({ sector_id: "sector-1", sector_name: "Sector 1", action: "irrigate", dose_band: "reforcada" }),
          sector({ sector_id: "sector-2", sector_name: "Sector 2", action: "irrigate", dose_band: "reforcada" }),
          sector({ sector_id: "sector-3", sector_name: "Sector 3", action: "skip", dose_band: "pode_saltar" }),
        ]}
      />,
    );

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Dois sectores do olival precisam de rega reforçada hoje; os restantes sectores podem esperar.",
    );
    expect(screen.queryByText(/o olival pode esperar/i)).not.toBeInTheDocument();
    expect(screen.getByText(/ET₀ hoje: 7,7 mm/)).toBeInTheDocument();
    expect(screen.getByText(/Sem chuva prevista nas próximas 48 horas/)).toBeInTheDocument();
    expect(screen.getByText(/Prioridade aos sectores em défice/)).toBeInTheDocument();
  });

  it("shows the polo name in the Boletim header when the weather is plot-scoped", () => {
    render(
      <Lede
        farmName="Innoliva"
        region="Alentejo"
        weather={weather}
        plotName="Fátima"
        sectors={[sector({ sector_id: "sector-1" })]}
      />,
    );

    expect(screen.getByText(/Boletim · hoje · Fátima/)).toBeInTheDocument();
  });

  it("shows the plain Boletim header when no plot-scoped weather applies", () => {
    render(
      <Lede
        farmName="Conqueiros"
        region="Leiria"
        weather={weather}
        sectors={[sector({ sector_id: "sector-1" })]}
      />,
    );

    expect(screen.getByText("Boletim · hoje")).toBeInTheDocument();
  });

  it("speaks the reforcada band, not the legacy irrigate action, for a pre-feature (dose_band null) recommendation", () => {
    render(
      <Lede
        farmName="Innoliva"
        region="Alentejo"
        weather={weather}
        sectors={[
          // Legacy rec: action=irrigate but no dose_band → legacyDoseBand maps to "normal",
          // not "reforcada", so this must NOT be counted as needing reinforced irrigation.
          sector({ sector_id: "sector-1", sector_name: "Sector 1", action: "irrigate", dose_band: null }),
          sector({ sector_id: "sector-2", sector_name: "Sector 2", action: "skip", dose_band: null }),
        ]}
      />,
    );

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Hoje todos os sectores podem esperar.",
    );
  });
});
