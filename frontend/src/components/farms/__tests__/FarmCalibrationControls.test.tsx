import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { FarmCalibrationControls } from "../FarmCalibrationControls";

const toast = vi.fn();

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast, toasts: [], dismiss: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  farmsApi: { setCalibrationAutoApply: vi.fn() },
  calibrationApi: { sweepFarm: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = "ApiError";
    }
  },
}));

import { farmsApi, calibrationApi, ApiError } from "@/lib/api";

const mockToggle = farmsApi.setCalibrationAutoApply as ReturnType<typeof vi.fn>;
const mockSweep = calibrationApi.sweepFarm as ReturnType<typeof vi.fn>;

const sweep = (over: Record<string, unknown> = {}) => ({
  auto_apply: true,
  counts: { applied: 1, skipped: 1, no_candidate: 0, candidates: 0, failed: 0 },
  outcomes: [
    {
      sector_id: "s1", sector_name: "Talhão A3", reason: "applied", applied: true,
      fc_before: 0.16, fc_candidate: 0.31, refill_before: 0.07,
      refill_candidate: 0.2, method: "envelope", before_source: "plot_preset",
    },
    {
      sector_id: "s2", sector_name: "Talhão B1", reason: "delta_exceeds_cap",
      applied: false, fc_before: 0.16, fc_candidate: 0.44, refill_before: 0.07,
      refill_candidate: 0.2, method: "envelope", before_source: "plot_preset",
    },
  ],
  ...over,
});

describe("FarmCalibrationControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reflects the initial flag state on the switch", () => {
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("turns the flag on and warns that Monday will apply bounds", async () => {
    mockToggle.mockResolvedValue({ calibration_auto_apply: true });
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(mockToggle).toHaveBeenCalledWith("f1", true));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/segunda-feira/i)).toBeInTheDocument();
  });

  it("reverts the switch when the toggle write fails", async () => {
    mockToggle.mockRejectedValue(new ApiError(500, "boom"));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false"),
    );
    expect(toast).toHaveBeenCalledWith(
      expect.stringMatching(/não foi possível/i),
      expect.objectContaining({ variant: "error" }),
    );
    expect(mockSweep).not.toHaveBeenCalled();
  });

  it("asks for confirmation before sweeping an ENABLED farm", async () => {
    mockSweep.mockResolvedValue(sweep());
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    // First click only arms the confirm — nothing has run yet.
    expect(mockSweep).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /cancelar/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /confirmar/i }));
    await waitFor(() => expect(mockSweep).toHaveBeenCalledWith("f1"));
  });

  it("cancelling the confirm runs nothing", () => {
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);
    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));
    expect(mockSweep).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /correr/i })).toBeInTheDocument();
  });

  it("sweeps a DISABLED farm immediately — nothing to protect", async () => {
    mockSweep.mockResolvedValue(sweep({ auto_apply: false }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() => expect(mockSweep).toHaveBeenCalledWith("f1"));
  });

  it("renders the tally and per-sector detail, blocked rows included", async () => {
    mockSweep.mockResolvedValue(sweep({ auto_apply: false }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() => expect(screen.getByText(/aplicadas 1/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /detalhe/i }));

    expect(screen.getByText("Talhão A3")).toBeInTheDocument();
    expect(screen.getByText(/16 → 31/)).toBeInTheDocument();
    // A blocked sector shows WHY and what it measured — the payload's whole point.
    expect(screen.getByText("Talhão B1")).toBeInTheDocument();
    expect(screen.getByText(/variação demasiado grande/i)).toBeInTheDocument();
    expect(screen.getByText(/16 ⇢ 44/)).toBeInTheDocument();
  });

  it("disables the trigger while a sweep is in flight", async () => {
    let resolve!: (v: unknown) => void;
    mockSweep.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /a calibrar/i })).toBeDisabled(),
    );

    resolve(sweep({ auto_apply: false }));
    await waitFor(() => expect(screen.getByText(/aplicadas 1/i)).toBeInTheDocument());
  });

  it("explains a rate-limit rejection", async () => {
    mockSweep.mockRejectedValue(new ApiError(429, "rate limited"));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.stringMatching(/demasiados pedidos/i),
        expect.objectContaining({ variant: "error" }),
      ),
    );
  });
});
