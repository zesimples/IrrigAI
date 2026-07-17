import { describe, expect, it } from "vitest";
import { formatDecimal, formatMm } from "@/lib/utils";

describe("formatDecimal", () => {
  it("uses the Portuguese comma as decimal separator", () =>
    expect(formatDecimal(7.8, 1)).toBe("7,8"));
  it("renders integers without a separator", () =>
    expect(formatDecimal(214, 0)).toBe("214"));
  it("supports two decimal places", () =>
    expect(formatDecimal(3.14159, 2)).toBe("3,14"));
  it("does not add grouping separators", () =>
    expect(formatDecimal(1234.56, 2)).toBe("1234,56"));
  it("keeps a leading zero below one", () =>
    expect(formatDecimal(0.5, 1)).toBe("0,5"));
  it("defaults to one decimal place", () =>
    expect(formatDecimal(7.84)).toBe("7,8"));
});

describe("formatMm", () => {
  it("formats mm values with a comma", () =>
    expect(formatMm(7.8)).toBe("7,8 mm"));
});
