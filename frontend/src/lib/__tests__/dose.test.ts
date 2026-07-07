import { describe, expect, it } from "vitest";
import { DOSE_BAND_LABELS, doseHeadline, formatRuntime, legacyDoseBand } from "@/lib/dose";

describe("formatRuntime", () => {
  it("formats minutes only", () => expect(formatRuntime(45)).toBe("45 min"));
  it("formats hours+minutes", () => expect(formatRuntime(155)).toBe("2h35"));
  it("pads minutes", () => expect(formatRuntime(125)).toBe("2h05"));
  it("rolls over fractional minutes", () => expect(formatRuntime(119.6)).toBe("2h00"));
});

describe("legacyDoseBand", () => {
  it("maps irrigate to normal", () => expect(legacyDoseBand("irrigate")).toBe("normal"));
  it("maps skip to pode_saltar", () => expect(legacyDoseBand("skip")).toBe("pode_saltar"));
  it("maps null to pode_saltar", () => expect(legacyDoseBand(null)).toBe("pode_saltar"));
});

describe("doseHeadline", () => {
  const base = { depthMm: 6, runtimeMin: null, habitualFactor: null, estimatedRuntimeMin: null };

  it("pode_saltar", () => {
    expect(doseHeadline({ ...base, doseBand: "pode_saltar", doseSource: "mm_only" }))
      .toBe("Pode saltar hoje");
  });

  it("configured runtime", () => {
    expect(doseHeadline({ ...base, doseBand: "normal", doseSource: "configured", runtimeMin: 90 }))
      .toBe("Regar 1h30 (6 mm)");
  });

  it("configured curta uses bastam", () => {
    expect(doseHeadline({ ...base, doseBand: "curta", doseSource: "configured", runtimeMin: 40, depthMm: 2 }))
      .toBe("Bastam 40 min hoje (2 mm)");
  });

  it("probe_learned with estimate", () => {
    expect(doseHeadline({
      ...base, doseBand: "normal", doseSource: "probe_learned",
      habitualFactor: 1.3, estimatedRuntimeMin: 155,
    })).toBe("≈1.3× a rega habitual (~2h35, estimado)");
  });

  it("probe_learned without estimate", () => {
    expect(doseHeadline({
      ...base, doseBand: "normal", doseSource: "probe_learned", habitualFactor: 0.5,
    })).toBe("≈0.5× a rega habitual");
  });

  it("mm_only", () => {
    expect(doseHeadline({ ...base, doseBand: "normal", doseSource: "mm_only" }))
      .toBe("Aplicar 6 mm hoje");
  });

  it("falls back to band label with no data", () => {
    expect(doseHeadline({ doseBand: "normal", doseSource: null, depthMm: null, runtimeMin: null, habitualFactor: null, estimatedRuntimeMin: null }))
      .toBe(DOSE_BAND_LABELS.normal);
  });

  it("shows configured runtime for a pre-feature rec (dose_source null but a runtime is set)", () => {
    expect(doseHeadline({ ...base, doseBand: "normal", doseSource: null, runtimeMin: 90 }))
      .toBe("Regar 1h30 (6 mm)");
  });
});
