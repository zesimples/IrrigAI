import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { AutoCalibrationCard } from "../AutoCalibrationCard";

// Mock the api module
vi.mock("@/lib/api", () => ({
  calibrationApi: {
    get: vi.fn(),
    accept: vi.fn(),
    dismiss: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
    }
  },
}));

import { calibrationApi } from "@/lib/api";

const mockCalibrationApi = calibrationApi as {
  get: ReturnType<typeof vi.fn>;
  accept: ReturnType<typeof vi.fn>;
  dismiss: ReturnType<typeof vi.fn>;
};

describe("AutoCalibrationCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing while loading", () => {
    mockCalibrationApi.get.mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(<AutoCalibrationCard sectorId="s1" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when API returns 404", async () => {
    mockCalibrationApi.get.mockRejectedValue({ status: 404 });
    const { container } = render(<AutoCalibrationCard sectorId="s1" />);
    await waitFor(() => {
      expect(container.firstChild).toBeNull();
    });
  });

  it("shows validation card when status=validated", async () => {
    mockCalibrationApi.get.mockResolvedValue({
      match: {
        status: "validated",
        current_preset: { preset_name_pt: "Franco-argilo-arenoso", preset_fc_pct: 32, preset_wp_pct: 14, distance: 0 },
        best_match: null,
      },
      observed: { observed_fc_pct: 31, observed_refill_pct: 15, num_cycles: 8, consistency: 0.9, analysis_depths_cm: [40] },
      suggestion_pt: "Solo validado",
      suggestion_en: "Soil validated",
    });
    render(<AutoCalibrationCard sectorId="s1" />);
    await waitFor(() => {
      expect(screen.getByText("Solo validado")).toBeInTheDocument();
      expect(screen.getByText("Franco-argilo-arenoso")).toBeInTheDocument();
    });
  });

  it("shows accept/dismiss buttons when status=better_match_found", async () => {
    mockCalibrationApi.get.mockResolvedValue({
      match: {
        status: "better_match_found",
        current_preset: { preset_name_pt: "Franco", preset_fc_pct: 28, preset_wp_pct: 12, distance: 0.08 },
        best_match: { preset_name_pt: "Franco-argiloso", preset_fc_pct: 35, preset_wp_pct: 18, distance: 0.02 },
      },
      observed: { observed_fc_pct: 34, observed_refill_pct: 17, num_cycles: 6, consistency: 0.85, analysis_depths_cm: [40] },
      suggestion_pt: "Sugerimos alterar o tipo de solo",
      suggestion_en: "We suggest changing the soil type",
    });
    render(<AutoCalibrationCard sectorId="s1" />);
    await waitFor(() => {
      expect(screen.getByText(/Alterar para Franco-argiloso/)).toBeInTheDocument();
      expect(screen.getByText("Manter atual")).toBeInTheDocument();
    });
  });

  it("calls accept and clears card on accept", async () => {
    const onAccepted = vi.fn();
    mockCalibrationApi.get.mockResolvedValue({
      match: {
        status: "better_match_found",
        current_preset: { preset_name_pt: "Franco", preset_fc_pct: 28, preset_wp_pct: 12, distance: 0.08 },
        best_match: { preset_name_pt: "Franco-argiloso", preset_fc_pct: 35, preset_wp_pct: 18, distance: 0.02 },
      },
      observed: { observed_fc_pct: 34, observed_refill_pct: 17, num_cycles: 6, consistency: 0.85, analysis_depths_cm: [40] },
      suggestion_pt: "Sugerimos alterar",
      suggestion_en: "We suggest",
    });
    mockCalibrationApi.accept.mockResolvedValue({ accepted: true, preset_name_pt: "Franco-argiloso", preset_name_en: "Sandy clay loam" });

    const { container } = render(<AutoCalibrationCard sectorId="s1" onAccepted={onAccepted} />);
    await waitFor(() => screen.getByText(/Alterar para/));

    fireEvent.click(screen.getByText(/Alterar para/));
    await waitFor(() => {
      expect(mockCalibrationApi.accept).toHaveBeenCalledWith("s1");
      expect(onAccepted).toHaveBeenCalledOnce();
      expect(container.firstChild).toBeNull();
    });
  });
});
