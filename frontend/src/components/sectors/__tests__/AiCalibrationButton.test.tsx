import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { AiCalibrationButton } from "../AiCalibrationButton";

const toast = vi.fn();

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast, toasts: [], dismiss: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  calibrationApi: { run: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = "ApiError";
    }
  },
}));

import { calibrationApi, ApiError } from "@/lib/api";

const mockRun = calibrationApi.run as ReturnType<typeof vi.fn>;

describe("AiCalibrationButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the honest deterministic calibration label", () => {
    render(<AiCalibrationButton sectorId="s1" />);
    expect(
      screen.getByRole("button", { name: /Calibração inteligente/i }),
    ).toBeInTheDocument();
  });

  it("is disabled with a tooltip and does not call the API when unavailable", () => {
    render(<AiCalibrationButton sectorId="s1" available={false} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", expect.stringContaining("VWC"));

    fireEvent.click(btn);
    expect(mockRun).not.toHaveBeenCalled();
  });

  const result = (over: Record<string, unknown> = {}) => ({
    sector_id: "s1",
    observed_fc: 0.46,
    observed_refill: 0.3,
    method: "envelope",
    num_cycles: 0,
    consistency: 0.5,
    window_days: 60,
    computed_at: "2026-06-26T00:00:00Z",
    max_age_days: 90,
    previous_fc: 0.16,
    previous_refill: 0.07,
    effective_fc: 0.46,
    effective_pwp: 0.3,
    effective_source: "probe_calibrated",
    changed: true,
    applied: true,
    cleared_customization: false,
    ...over,
  });

  it("applies the calibration and refreshes, showing the CC transition", async () => {
    mockRun.mockResolvedValue(result());
    const onCalibrated = vi.fn();
    render(<AiCalibrationButton sectorId="s1" onCalibrated={onCalibrated} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(mockRun).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(onCalibrated).toHaveBeenCalledWith(true));
    expect(toast).toHaveBeenCalledWith(
      "Calibração aplicada",
      expect.objectContaining({ variant: "success", description: expect.stringContaining("16→46") }),
    );
  });

  it("notes when the run overrides a manual soil setting", async () => {
    mockRun.mockResolvedValue(
      result({ previous_fc: 0.171, effective_fc: 0.46, changed: true, cleared_customization: true }),
    );
    const onCalibrated = vi.fn();
    render(<AiCalibrationButton sectorId="s1" onCalibrated={onCalibrated} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Calibração aplicada",
        expect.objectContaining({
          variant: "success",
          description: expect.stringContaining("substituiu definição manual"),
        }),
      ),
    );
    await waitFor(() => expect(onCalibrated).toHaveBeenCalledWith(true));
  });

  it("shows a no-change toast and refreshes the chart but not the recommendation", async () => {
    mockRun.mockResolvedValue(result({ changed: false }));
    const onCalibrated = vi.fn();
    render(<AiCalibrationButton sectorId="s1" onCalibrated={onCalibrated} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Sem alterações",
        expect.objectContaining({ variant: "info" }),
      ),
    );
    // Chart still refreshes, but regenerate=false (nothing moved).
    await waitFor(() => expect(onCalibrated).toHaveBeenCalledWith(false));
  });

  it("shows loading state and disables while running", async () => {
    let resolve!: (v: unknown) => void;
    mockRun.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<AiCalibrationButton sectorId="s1" />);

    const btn = screen.getByRole("button");
    fireEvent.click(btn);

    await waitFor(() => expect(btn).toBeDisabled());
    expect(screen.getByText("A calibrar…")).toBeInTheDocument();

    resolve(result());
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("surfaces the backend's specific reason on a 422", async () => {
    mockRun.mockRejectedValue(
      new ApiError(422, "Este sector usa sensores de tensão (tipo Watermark)."),
    );
    render(<AiCalibrationButton sectorId="s1" />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Calibração indisponível",
        expect.objectContaining({
          variant: "error",
          description: expect.stringContaining("Watermark"),
        }),
      ),
    );
  });
});
