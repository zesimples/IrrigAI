import { describe, expect, it } from "vitest";
import { buildSumData, countLiveDepths } from "../ProbeSumChart";
import type { DepthReadings } from "@/types";

function depth(depth_cm: number, points: Array<[string, number]>): DepthReadings {
  return {
    depth_cm,
    readings: points.map(([timestamp, vwc]) => ({ timestamp, vwc, quality: "ok" })),
  } as DepthReadings;
}

describe("countLiveDepths", () => {
  it("ignores depths with no readings in the window", () => {
    const depths = [
      depth(10, [["2026-07-10T00:00:00Z", 0.2]]),
      depth(20, [["2026-07-10T00:00:00Z", 0.3]]),
      depth(30, []), // silent sensor / stale ProbeDepth row
    ];
    expect(countLiveDepths(depths)).toBe(2);
  });
});

describe("buildSumData", () => {
  it("sums aligned timestamps across all live depths", () => {
    const depths = [
      depth(10, [["2026-07-10T00:00:00Z", 0.2], ["2026-07-10T01:00:00Z", 0.25]]),
      depth(20, [["2026-07-10T00:00:00Z", 0.3], ["2026-07-10T01:00:00Z", 0.35]]),
    ];
    const rows = buildSumData(depths);
    expect(rows).toHaveLength(2);
    expect(rows[0].sum).toBeCloseTo(50); // (0.2 + 0.3) × 100
    expect(rows[1].sum).toBeCloseTo(60);
  });

  it("normalizes rows where some depths are missing, instead of under-summing", () => {
    // Depth 20 misses the second timestamp: the naive sum would halve there
    // and read as a fake dip below the (n-scaled) PMP line.
    const depths = [
      depth(10, [["2026-07-10T00:00:00Z", 0.2], ["2026-07-10T01:00:00Z", 0.2]]),
      depth(20, [["2026-07-10T00:00:00Z", 0.3]]),
    ];
    const rows = buildSumData(depths);
    expect(rows).toHaveLength(2);
    expect(rows[0].sum).toBeCloseTo(50);
    // avg of reporting depths (0.2) × 2 live depths = 40%, not a 20% half-sum
    expect(rows[1].sum).toBeCloseTo(40);
  });

  it("is not diluted by depths with no readings at all", () => {
    const depths = [
      depth(10, [["2026-07-10T00:00:00Z", 0.2]]),
      depth(20, [["2026-07-10T00:00:00Z", 0.3]]),
      depth(30, []), // dead sensor
    ];
    const rows = buildSumData(depths);
    // sum stays the 2-live-depth sum; dead depth neither adds nor scales
    expect(rows[0].sum).toBeCloseTo(50);
  });
});
