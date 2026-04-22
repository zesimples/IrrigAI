import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StressProjectionCard } from "../StressProjectionCard";
import type { StressProjection } from "@/types/index";

const base: StressProjection = {
  current_depletion_pct: 30,
  hours_to_stress: null,
  stress_date: null,
  urgency: "none",
  message_pt: "Sem risco de stress nas próximas 72h.",
  message_en: "No stress risk in the next 72h.",
  projections: [],
};

describe("StressProjectionCard", () => {
  it("shows 'Sem risco' badge for urgency=none", () => {
    render(<StressProjectionCard projection={base} />);
    expect(screen.getByText("Sem risco")).toBeInTheDocument();
  });

  it("shows 'Urgente' badge for urgency=high", () => {
    render(<StressProjectionCard projection={{ ...base, urgency: "high" }} />);
    expect(screen.getByText("Urgente")).toBeInTheDocument();
  });

  it("shows 'Provável' badge for urgency=medium", () => {
    render(<StressProjectionCard projection={{ ...base, urgency: "medium" }} />);
    expect(screen.getByText("Provável")).toBeInTheDocument();
  });

  it("shows 'Possível' badge for urgency=low", () => {
    render(<StressProjectionCard projection={{ ...base, urgency: "low" }} />);
    expect(screen.getByText("Possível")).toBeInTheDocument();
  });

  it("renders the Portuguese message", () => {
    render(<StressProjectionCard projection={base} />);
    expect(screen.getByText(base.message_pt)).toBeInTheDocument();
  });

  it("does not render accept button when urgency=none", () => {
    const onAccept = vi.fn();
    render(<StressProjectionCard projection={base} onAcceptRecommendation={onAccept} />);
    expect(screen.queryByText(/Aceitar/)).not.toBeInTheDocument();
  });

  it("renders accept button for urgent projection and calls handler", () => {
    const onAccept = vi.fn();
    render(
      <StressProjectionCard
        projection={{ ...base, urgency: "high" }}
        onAcceptRecommendation={onAccept}
      />,
    );
    const btn = screen.getByText(/Aceitar recomendação/);
    fireEvent.click(btn);
    expect(onAccept).toHaveBeenCalledOnce();
  });

  it("renders 3 day bars when projections are provided", () => {
    const projections = [
      { date: "2026-04-22", projected_etc_mm: 3, projected_rain_mm: 0, projected_depletion_mm: 10, projected_depletion_pct: 25, stress_triggered: false },
      { date: "2026-04-23", projected_etc_mm: 3, projected_rain_mm: 0, projected_depletion_mm: 13, projected_depletion_pct: 33, stress_triggered: false },
      { date: "2026-04-24", projected_etc_mm: 3, projected_rain_mm: 0, projected_depletion_mm: 16, projected_depletion_pct: 40, stress_triggered: false },
    ];
    render(<StressProjectionCard projection={{ ...base, projections }} />);
    // Each bar has a pct label
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("33%")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });
});
