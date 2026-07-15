import { describe, expect, it } from "vitest";
import {
  buildRootzoneData,
  calculateSumDomain,
  computeRootzoneDepletionPct,
} from "../ProbeSumChart";

describe("computeRootzoneDepletionPct", () => {
  it("is the exact complement of available water between CC and PMP", () => {
    // Turno-shaped values: CC=11%, PMP=1%, weighted VWC=7.5%.
    // Depletion=(11-7.5)/(11-1)=35%; available water=65%.
    const depletion = computeRootzoneDepletionPct(0.075, 0.11, 0.01);
    expect(depletion).toBeCloseTo(35);
    expect(100 - depletion!).toBeCloseTo(65);
  });

  it("matches the engine by clamping wetter-than-CC readings to zero depletion", () => {
    expect(computeRootzoneDepletionPct(0.4, 0.3, 0.1)).toBe(0);
  });

  it("matches the engine by clamping drier-than-PMP readings to full depletion", () => {
    expect(computeRootzoneDepletionPct(0.05, 0.3, 0.1)).toBe(100);
  });

  it("returns null for missing or invalid soil bounds", () => {
    expect(computeRootzoneDepletionPct(0.2, null, 0.1)).toBeNull();
    expect(computeRootzoneDepletionPct(0.2, 0.1, 0.1)).toBeNull();
  });
});

describe("buildRootzoneData", () => {
  it("sorts the weighted series and derives depletion for every point", () => {
    const data = buildRootzoneData(
      [
        { timestamp: "2026-07-15T01:00:00Z", vwc: 0.075 },
        { timestamp: "2026-07-15T00:00:00Z", vwc: 0.11 },
      ],
      { field_capacity: 0.11, wilting_point: 0.01 },
    );

    expect(data).toHaveLength(2);
    expect(data[0].vwcPct).toBeCloseTo(11);
    expect(data[0].depletionPct).toBeCloseTo(0);
    expect(data[1].vwcPct).toBeCloseTo(7.5);
    expect(data[1].depletionPct).toBeCloseTo(35);
    expect(data[1].availablePct).toBeCloseTo(65);
  });
});

describe("calculateSumDomain", () => {
  it("zooms around weighted VWC and the unscaled CC/PMP bounds", () => {
    expect(calculateSumDomain(5.2, 8.4, 1, 11)).toEqual([0, 13]);
  });

  it("keeps both agronomic thresholds visible", () => {
    const [min, max] = calculateSumDomain(7, 8, 1, 11);
    expect(min).toBeLessThanOrEqual(1);
    expect(max).toBeGreaterThan(11);
  });

  it("uses minimum padding for a flat series without reference lines", () => {
    expect(calculateSumDomain(20, 20, null, null)).toEqual([19, 21]);
  });

  it("never creates a negative lower bound", () => {
    expect(calculateSumDomain(1, 3, 0, 4)[0]).toBe(0);
  });
});
