import { describe, expect, it } from "vitest";
import {
  buildSumData,
  calculateSumDomain,
  countLiveDepths,
  filterRootzoneDepths,
  sumReferenceBound,
} from "../ProbeSumChart";
import type { DepthReadings } from "@/types";

function depth(
  depth_cm: number,
  points: Array<[string, number]>,
  bounds?: { fc?: number | null; wp?: number | null },
): DepthReadings {
  return {
    depth_cm,
    readings: points.map(([timestamp, vwc]) => ({ timestamp, vwc, quality: "ok" })),
    field_capacity: bounds?.fc ?? null,
    wilting_point: bounds?.wp ?? null,
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

describe("filterRootzoneDepths", () => {
  it("excludes wet depths below the effective root zone", () => {
    const depths = [depth(30, []), depth(60, []), depth(90, [])];
    expect(filterRootzoneDepths(depths, 60).map((d) => d.depth_cm)).toEqual([30, 60]);
  });

  it("keeps all depths when no sensor falls inside the configured root zone", () => {
    const depths = [depth(30, []), depth(60, [])];
    expect(filterRootzoneDepths(depths, 20)).toEqual(depths);
  });

  it("keeps all depths when root depth is unavailable", () => {
    const depths = [depth(30, []), depth(60, [])];
    expect(filterRootzoneDepths(depths, null)).toEqual(depths);
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

describe("calculateSumDomain", () => {
  it("zooms around the readings and CC/PMP instead of always starting at zero", () => {
    // Production-shaped values from the reported chart: readings 162.9–197.2,
    // PMP 154 and CC 201. The old domain was 0–226.
    expect(calculateSumDomain(162.9, 197.2, 154, 201)).toEqual([148, 207]);
  });

  it("keeps both agronomic thresholds visible when readings sit between them", () => {
    const [min, max] = calculateSumDomain(170, 180, 150, 200);
    expect(min).toBeLessThan(150);
    expect(max).toBeGreaterThan(200);
  });

  it("uses a minimum padding for a flat series without reference lines", () => {
    expect(calculateSumDomain(20, 20, null, null)).toEqual([15, 25]);
  });

  it("never creates a negative lower bound", () => {
    expect(calculateSumDomain(1, 3, 0, 4)[0]).toBe(0);
  });
});

describe("sumReferenceBound", () => {
  const pt: [string, number] = ["2026-07-10T00:00:00Z", 0.2];

  it("sums per-depth envelope bounds when every live depth has one", () => {
    const depths = [
      depth(10, [pt], { fc: 0.3 }),
      depth(30, [pt], { fc: 0.1 }),
    ];
    // (0.3 + 0.1) × 100 — real per-layer bounds, not depths[0] × n
    expect(sumReferenceBound(depths, (d) => d.field_capacity, 0.25)).toBeCloseTo(40);
  });

  it("falls back to the resolved per-depth value for depths without an envelope", () => {
    const depths = [
      depth(10, [pt], { fc: 0.3 }),
      depth(30, [pt]), // no envelope for this depth
    ];
    expect(sumReferenceBound(depths, (d) => d.field_capacity, 0.2)).toBeCloseTo(50);
  });

  it("uses resolved × live-count when no depth has an envelope (old behavior)", () => {
    const depths = [depth(10, [pt]), depth(30, [pt])];
    expect(sumReferenceBound(depths, (d) => d.field_capacity, 0.2)).toBeCloseTo(40);
  });

  it("ignores dead depths entirely", () => {
    const depths = [
      depth(10, [pt], { fc: 0.3 }),
      depth(30, [], { fc: 0.5 }), // dead sensor: neither its envelope nor fallback counts
    ];
    expect(sumReferenceBound(depths, (d) => d.field_capacity, 0.2)).toBeCloseTo(30);
  });

  it("returns null when a depth has no envelope and there is no fallback", () => {
    const depths = [depth(10, [pt], { fc: 0.3 }), depth(30, [pt])];
    expect(sumReferenceBound(depths, (d) => d.field_capacity, null)).toBeNull();
  });
});
