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

  it("renders the Calibração AI button", () => {
    render(<AiCalibrationButton sectorId="s1" />);
    expect(screen.getByRole("button", { name: /Calibração AI/i })).toBeInTheDocument();
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
    previous_fc: null,
    previous_refill: null,
    changed: true,
    ...over,
  });

  it("calls the run API and refreshes on first calibration", async () => {
    mockRun.mockResolvedValue(result());
    const onCalibrated = vi.fn();
    render(<AiCalibrationButton sectorId="s1" onCalibrated={onCalibrated} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(mockRun).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(onCalibrated).toHaveBeenCalled());
    expect(toast).toHaveBeenCalledWith(
      "Calibração concluída",
      expect.objectContaining({ variant: "success" }),
    );
  });

  it("shows an updated toast with the delta when bounds moved", async () => {
    mockRun.mockResolvedValue(result({ previous_fc: 0.41, previous_refill: 0.28, changed: true }));
    const onCalibrated = vi.fn();
    render(<AiCalibrationButton sectorId="s1" onCalibrated={onCalibrated} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Calibração atualizada",
        expect.objectContaining({ variant: "success", description: expect.stringContaining("41→46") }),
      ),
    );
    expect(onCalibrated).toHaveBeenCalled();
  });

  it("shows a no-change toast and does NOT refresh when nothing moved", async () => {
    mockRun.mockResolvedValue(result({ previous_fc: 0.46, previous_refill: 0.3, changed: false }));
    const onCalibrated = vi.fn();
    render(<AiCalibrationButton sectorId="s1" onCalibrated={onCalibrated} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Sem alterações",
        expect.objectContaining({ variant: "info" }),
      ),
    );
    expect(onCalibrated).not.toHaveBeenCalled();
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
