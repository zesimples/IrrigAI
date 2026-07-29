/**
 * The sweep is a background job now: POST returns 202 {run_id} and the result
 * arrives by polling GET /calibration-sweep-runs/{run_id}.
 *
 * Migration inventory (evidence that no coverage was dropped):
 *  UNCHANGED — none of these inspect the sweep's payload:
 *    "reflects the initial flag state", "turns the flag on and warns…",
 *    "reverts the switch when the toggle write fails",
 *    "cancelling the confirm runs nothing",
 *    "disables the trigger while the TOGGLE write is in flight",
 *    "explains a rate-limit rejection"
 *  FIXTURE ONLY (assertions untouched, `sweepFarm` now resolves to `queued`):
 *    "asks for confirmation before sweeping an ENABLED farm",
 *    "sweeps a DISABLED farm immediately — nothing to protect"
 *  MOVED TO QUEUED-THEN-POLL (asserted on the result payload):
 *    "renders the tally and per-sector detail, blocked rows included",
 *    "disables the trigger while a sweep is in flight",
 *    "warns that applied limits only take effect on the next recommendation",
 *    "does NOT claim a pending effect when nothing was applied",
 *    "clears the previous tally when re-running"
 *  NEW: progress, terminal-stops-polling, unmount, 409-attach, interrupted run.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { FarmCalibrationControls } from "../FarmCalibrationControls";

const toast = vi.fn();

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast, toasts: [], dismiss: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  farmsApi: { setCalibrationAutoApply: vi.fn() },
  calibrationApi: { sweepFarm: vi.fn(), sweepRun: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public detail: string,
      public body?: unknown,
    ) {
      super(detail);
      this.name = "ApiError";
    }
  },
}));

import { farmsApi, calibrationApi, ApiError } from "@/lib/api";

const mockToggle = farmsApi.setCalibrationAutoApply as ReturnType<typeof vi.fn>;
const mockSweep = calibrationApi.sweepFarm as ReturnType<typeof vi.fn>;
const mockSweepRun = calibrationApi.sweepRun as ReturnType<typeof vi.fn>;

const queued = { run_id: "r1", status: "queued", auto_apply: false };

const runAt = (over: Record<string, unknown> = {}) => ({
  run_id: "r1", farm_id: "f1", status: "running", auto_apply: false,
  sectors_total: 77, sectors_done: 34,
  counts: { applied: 5, skipped: 2, no_candidate: 1, candidates: 0, failed: 0 },
  outcomes: null, error: null,
  queued_at: "2026-07-28T18:00:00Z", started_at: "2026-07-28T18:00:05Z", finished_at: null,
  ...over,
});

const OUTCOMES = [
  {
    sector_id: "s1", sector_name: "Talhão A3", reason: "applied", applied: true,
    fc_before: 0.16, fc_candidate: 0.31, refill_before: 0.07, refill_candidate: 0.2,
    method: "envelope", before_source: "plot_preset",
  },
  {
    sector_id: "s2", sector_name: "Talhão B1", reason: "delta_exceeds_cap", applied: false,
    fc_before: 0.16, fc_candidate: 0.44, refill_before: 0.07, refill_candidate: 0.2,
    method: "envelope", before_source: "plot_preset",
  },
  // No moisture probe: structurally uncalibratable, not a data gap.
  {
    sector_id: "s3", sector_name: "Só caudalímetro", reason: "not_applicable", applied: false,
    fc_before: null, fc_candidate: null, refill_before: null, refill_candidate: null,
    method: null, before_source: null,
  },
  // A real probe below the reading floor: someone can actually fix this one.
  {
    sector_id: "s4", sector_name: "Sonda nova", reason: "insufficient_data", applied: false,
    fc_before: null, fc_candidate: null, refill_before: null, refill_candidate: null,
    method: null, before_source: null,
  },
];

/** A terminal run. `over` lands on the run, so counts can be replaced wholesale. */
const finished = (over: Record<string, unknown> = {}) => runAt({
  status: "success", sectors_done: 77, finished_at: "2026-07-28T18:09:00Z",
  counts: { applied: 12, skipped: 40, no_candidate: 25, candidates: 0, failed: 0 },
  outcomes: OUTCOMES,
  ...over,
});

/**
 * Advance fake timers and let React flush.
 *
 * `act` is load-bearing: React 18 flushes updates through its scheduler
 * (MessageChannel), which vi.useFakeTimers() does not fake, so awaiting
 * advanceTimersByTimeAsync alone leaves the render pending — and RTL's
 * RTL's findBy / waitFor helpers never drive vitest's fake clock, so they hang
 * instead of failing. Advance inside act, then assert synchronously.
 */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("FarmCalibrationControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
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
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(runAt());
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
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(runAt());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() => expect(mockSweep).toHaveBeenCalledWith("f1"));
  });

  it("renders the tally and per-sector detail, blocked rows included", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(finished());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByText(/aplicadas 12/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /detalhe/i }));

    expect(screen.getByText("Talhão A3")).toBeInTheDocument();
    expect(screen.getByText(/16 → 31/)).toBeInTheDocument();
    // A blocked sector shows WHY and what it measured — the payload's whole point.
    expect(screen.getByText("Talhão B1")).toBeInTheDocument();
    expect(screen.getByText(/variação demasiado grande/i)).toBeInTheDocument();
    expect(screen.getByText(/16 ⇢ 44/)).toBeInTheDocument();
  });

  it("distinguishes a sector with no probe from one merely short of data", async () => {
    // Both used to render "sem dados suficientes", which told an agronomist to go
    // fix a flowmeter-only sector that can never be calibrated.
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(finished());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);
    fireEvent.click(screen.getByRole("button", { name: /detalhe/i }));

    expect(screen.getByText("Só caudalímetro")).toBeInTheDocument();
    expect(screen.getByText(/sem sonda de humidade/i)).toBeInTheDocument();
    expect(screen.getByText("Sonda nova")).toBeInTheDocument();
    expect(screen.getByText(/dados insuficientes na sonda/i)).toBeInTheDocument();
  });

  it("disables the trigger while a sweep is in flight", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    // Still running after the first poll: the button must stay disabled until a
    // TERMINAL status arrives, not merely until the POST resolves.
    mockSweepRun.mockResolvedValue(runAt());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByRole("button", { name: /a calibrar/i })).toBeDisabled();

    mockSweepRun.mockResolvedValue(finished());
    await tick(2100);

    expect(screen.getByText(/aplicadas 12/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /correr/i })).toBeEnabled();
  });

  it("disables the trigger while the TOGGLE write is in flight", async () => {
    // The race this guards: the farm's flag is TRUE in the DB, the user switches
    // it off (optimistic `enabled=false`) and hits `correr` before the PUT lands.
    // With the trigger live, handleTriggerClick would see enabled=false, skip the
    // confirmation, and the backend — still reading calibration_auto_apply=true —
    // would apply new bounds on every sector with nothing confirmed.
    let resolveToggle!: (v: unknown) => void;
    mockToggle.mockReturnValue(new Promise((r) => { resolveToggle = r; }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);

    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /correr/i })).toBeDisabled(),
    );

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    expect(mockSweep).not.toHaveBeenCalled();

    resolveToggle({ calibration_auto_apply: false });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /correr/i })).toBeEnabled(),
    );
  });

  it("warns that applied limits only take effect on the next recommendation", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(finished());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByText(/próxima recomendação/i)).toBeInTheDocument();
  });

  it("does NOT claim a pending effect when nothing was applied", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(
      finished({
        counts: { applied: 0, skipped: 0, no_candidate: 2, candidates: 1, failed: 0 },
      }),
    );
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByText(/candidatas 1/i)).toBeInTheDocument();
    expect(screen.queryByText(/próxima recomendação/i)).not.toBeInTheDocument();
  });

  it("clears the previous tally when re-running", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(finished());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);
    expect(screen.getByText(/aplicadas 12/i)).toBeInTheDocument();

    // Second run still queued: the old numbers must not sit beside "a calibrar…"
    // and be read as the new answer.
    mockSweepRun.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByRole("button", { name: /a calibrar/i })).toBeInTheDocument();
    expect(screen.queryByText(/aplicadas 12/i)).not.toBeInTheDocument();
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

  it("shows sector progress while the sweep runs", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(runAt());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByText(/34\/77/)).toBeInTheDocument();
  });

  it("stops polling once the run reaches a terminal status", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(finished());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByText(/aplicadas 12/i)).toBeInTheDocument();
    const callsAfterDone = mockSweepRun.mock.calls.length;
    await tick(10_000);
    // Polling must stop on a terminal status, not keep hammering.
    expect(mockSweepRun.mock.calls.length).toBe(callsAfterDone);
  });

  it("stops polling when unmounted mid-sweep", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(runAt());
    const { unmount } = render(
      <FarmCalibrationControls farmId="f1" initialEnabled={false} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);
    const before = mockSweepRun.mock.calls.length;

    unmount();
    await tick(20_000);
    expect(mockSweepRun.mock.calls.length).toBe(before);
  });

  it("attaches to the already-running sweep on a 409", async () => {
    vi.useFakeTimers();
    mockSweep.mockRejectedValue(
      new ApiError(409, "já está a correr", { detail: "já está a correr", run_id: "r1" }),
    );
    mockSweepRun.mockResolvedValue(runAt());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(mockSweepRun).toHaveBeenCalledWith("r1");
    expect(screen.getByText(/34\/77/)).toBeInTheDocument();
  });

  it("renders an interrupted run honestly", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(runAt({ status: "stale", error: "no heartbeat" }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await tick(2100);

    expect(screen.getByText(/interrompida/i)).toBeInTheDocument();
  });

  it("gives up rather than spinning forever", async () => {
    vi.useFakeTimers();
    mockSweep.mockResolvedValue(queued);
    mockSweepRun.mockResolvedValue(runAt());
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    // Past the 20-minute cap: a spinner that never ends is what made the
    // synchronous version look broken.
    await tick(21 * 60 * 1_000);

    expect(screen.getByText(/recarregue a página/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /correr/i })).toBeEnabled();
  });
});
