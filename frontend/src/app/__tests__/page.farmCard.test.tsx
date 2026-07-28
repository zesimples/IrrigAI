/**
 * Guards the one structural rule the card must keep: the calibration controls
 * are siblings of the navigation link, never nested inside it.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: vi.fn(), toasts: [], dismiss: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  farmsApi: { list: vi.fn(), dashboard: vi.fn(), setCalibrationAutoApply: vi.fn() },
  calibrationApi: { sweepFarm: vi.fn() },
  clearToken: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = "ApiError";
    }
  },
}));

import { FarmCard } from "../FarmCard";

// FarmCard indexes VERDICT_COLORS[fd.verdict] and reads moisture/lastSync/et0/
// cultures, so every FarmData field must be present — a partial object crashes
// on VERDICT_COLORS[undefined].accent rather than failing an assertion.
const fd = {
  farm: {
    id: "f1", name: "Herdade do Esporão", location_lat: null, location_lon: null,
    elevation_m: null, region: "Alentejo", timezone: "Europe/Lisbon",
    owner_id: "u1", is_archived: false, calibration_auto_apply: false,
    archived_at: null, created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  dashboard: null,
  irrigateCount: 0,
  totalSectors: 0,
  verdict: "ok" as const,
  verdictLabel: "Sem rega hoje",
  verdictWhy: "",
  moisture: 0.62,
  lastSync: "há 5 min",
  et0: 4.2,
  cultures: ["almond"],
} as unknown as Parameters<typeof FarmCard>[0]["fd"];

describe("FarmCard calibration controls", () => {
  it("renders the switch outside the navigation anchor", () => {
    render(<FarmCard fd={fd} idx={1} />);

    const sw = screen.getByRole("switch");
    expect(sw).toBeInTheDocument();
    // The invariant: no interactive control nested in the <a>.
    expect(sw.closest("a")).toBeNull();
    expect(screen.getByRole("button", { name: /correr/i }).closest("a")).toBeNull();
  });

  it("still links through to the farm", () => {
    render(<FarmCard fd={fd} idx={1} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/farms/f1");
  });
});
