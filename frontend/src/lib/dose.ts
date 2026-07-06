import type { DoseBand, DoseSource } from "@/types";

export const DOSE_BAND_LABELS: Record<DoseBand, string> = {
  reforcada: "Rega reforçada",
  normal: "Rega normal",
  curta: "Rega curta",
  pode_saltar: "Pode saltar",
};

/** Sort severity: most water need first. */
export const BAND_ORDER: Record<DoseBand, number> = {
  reforcada: 0,
  normal: 1,
  curta: 2,
  pode_saltar: 3,
};

export function formatRuntime(min: number): string {
  const t = Math.round(min);
  const h = Math.floor(t / 60);
  const m = t % 60;
  if (h === 0) return `${m} min`;
  return `${h}h${String(m).padStart(2, "0")}`;
}

/** Band fallback for recommendations generated before dose-do-dia existed. */
export function legacyDoseBand(action: string | null): DoseBand {
  return action === "irrigate" ? "normal" : "pode_saltar";
}

export interface DoseHeadlineInput {
  doseBand: DoseBand;
  doseSource: DoseSource | null;
  depthMm: number | null;
  runtimeMin: number | null; // configured runtime from the engine
  habitualFactor: number | null;
  estimatedRuntimeMin: number | null;
}

export function doseHeadline(d: DoseHeadlineInput): string {
  if (d.doseBand === "pode_saltar") return "Pode saltar hoje";
  if (d.doseSource === "configured" && d.runtimeMin != null) {
    const mm = d.depthMm != null ? ` (${d.depthMm.toFixed(0)} mm)` : "";
    if (d.doseBand === "curta") return `Bastam ${formatRuntime(d.runtimeMin)} hoje${mm}`;
    return `Regar ${formatRuntime(d.runtimeMin)}${mm}`;
  }
  if (d.doseSource === "probe_learned" && d.habitualFactor != null) {
    const est =
      d.estimatedRuntimeMin != null ? ` (~${formatRuntime(d.estimatedRuntimeMin)}, estimado)` : "";
    return `≈${d.habitualFactor.toFixed(1)}× a rega habitual${est}`;
  }
  if (d.depthMm != null) return `Aplicar ${d.depthMm.toFixed(0)} mm hoje`;
  return DOSE_BAND_LABELS[d.doseBand];
}
