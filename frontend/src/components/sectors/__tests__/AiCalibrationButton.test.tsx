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

  it("calls the run API and refreshes on success", async () => {
    mockRun.mockResolvedValue({
      sector_id: "s1",
      observed_fc: 0.46,
      observed_refill: 0.3,
      method: "envelope",
      num_cycles: 0,
      consistency: 0.5,
      window_days: 60,
      computed_at: "2026-06-26T00:00:00Z",
      max_age_days: 90,
    });
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

  it("shows loading state and disables while running", async () => {
    let resolve!: (v: unknown) => void;
    mockRun.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<AiCalibrationButton sectorId="s1" />);

    const btn = screen.getByRole("button");
    fireEvent.click(btn);

    await waitFor(() => expect(btn).toBeDisabled());
    expect(screen.getByText("A calibrar…")).toBeInTheDocument();

    resolve({
      sector_id: "s1", observed_fc: 0.46, observed_refill: 0.3, method: "envelope",
      num_cycles: 0, consistency: 0.5, window_days: 60,
      computed_at: "2026-06-26T00:00:00Z", max_age_days: 90,
    });
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("shows an error toast on insufficient data (422)", async () => {
    mockRun.mockRejectedValue(new ApiError(422, "Insufficient probe data"));
    render(<AiCalibrationButton sectorId="s1" />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Dados insuficientes",
        expect.objectContaining({ variant: "error" }),
      ),
    );
  });
});
