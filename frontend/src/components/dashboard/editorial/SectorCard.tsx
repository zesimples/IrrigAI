"use client";

import Link from "next/link";
import type { SectorSummary } from "@/types";
import { STAGE_LABELS } from "@/lib/cropConfig";
import { VerdictPill, type Verdict } from "./VerdictPill";
import { SoilBar } from "./SoilBar";
import { ConfidenceDots, confidenceLabel, type Confidence } from "./ConfidenceDots";
import { doseHeadline, legacyDoseBand } from "@/lib/dose";

interface EditorialSectorCardProps {
  sector: SectorSummary;
  farmId: string;
}

function toVerdict(sector: SectorSummary): Verdict {
  return sector.dose_band ?? legacyDoseBand(sector.action);
}

function toConfidence(level: string | null, probeHealth: string): Confidence {
  if (probeHealth === "no_probes" || probeHealth === "no_readings") return "sem-sonda";
  if (level === "high") return "alta";
  if (level === "medium") return "media";
  if (level === "low") return "baixa";
  return "sem-sonda";
}

function dataQualityLabel(sourceConfidence: string | null, probeHealth: string): string {
  if (sourceConfidence === "no_probe" || probeHealth === "no_probes") return "Sem sondas";
  if (sourceConfidence === "forecast_only") return "Só previsão";
  if (sourceConfidence === "stale") return "Dados atrasados";
  if (sourceConfidence === "fresh") return "Dados actuais";
  // Fall back to generic confidence label when source_confidence is absent (old recs)
  return "—";
}

function toMoisture(depletionPct: number | null, rootzoneStatus: string | null): number {
  if (depletionPct != null) return Math.max(0, Math.min(1, 1 - depletionPct / 100));
  switch (rootzoneStatus) {
    case "wet": case "saturated": return 0.78;
    case "optimal": return 0.55;
    case "dry": return 0.30;
    case "critical": return 0.12;
    default: return 0.50;
  }
}

function sectorId(name: string): string {
  return name.split(" - ")[0].trim().toUpperCase();
}

function sectorSuffix(name: string, cropLabel: string): string {
  const parts = name.split(" - ");
  return parts.length > 1 ? parts.slice(1).join(" - ").trim() : cropLabel;
}

export function EditorialSectorCard({ sector, farmId }: EditorialSectorCardProps) {
  const noRecommendation = sector.dose_band == null && sector.action == null;
  const verdict = toVerdict(sector);
  const reforcada = !noRecommendation && verdict === "reforcada";
  const confidence = toConfidence(sector.confidence_level, sector.probe_health);
  const moisture = toMoisture(sector.depletion_pct, sector.rootzone_status);
  const noProbe = sector.probe_health === "no_probes" || sector.probe_health === "no_readings";
  const stageLabel = STAGE_LABELS[sector.current_stage ?? ""] ?? sector.current_stage ?? "—";
  const id = sectorId(sector.sector_name);
  const suffix = sectorSuffix(sector.sector_name, "");

  return (
    <Link
      href={`/farms/${farmId}/sectors/${sector.sector_id}`}
      className={`relative block min-h-[170px] border-r border-b border-rule p-[18px_20px_16px] transition-colors hover:bg-paper-in ${reforcada ? "bg-terra-bg" : "bg-card"} ${noProbe ? "opacity-60 grayscale-[30%]" : ""}`}
    >
      {/* Left accent bar for "reforcada" */}
      {reforcada && <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-terra rounded-l" />}

      <header className="flex items-start justify-between gap-3 mb-2">
        <div>
          <p className="font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3 mb-0.5">
            {id}
          </p>
          <h3 className="font-serif text-[17px] font-medium tracking-[-0.01em] text-ink leading-snug">
            {suffix || id}{" "}
            <span className="font-normal text-ink-3">· {stageLabel}</span>
          </h3>
        </div>
        {noRecommendation ? (
          <span
            aria-label="Recomendação: Sem recomendação"
            className="inline-flex items-center gap-1.5 rounded-full font-medium tracking-[-0.01em] whitespace-nowrap px-2.5 py-[3px] text-[11px] bg-[#f4f1ec] text-ink-3 border border-[#e3ddd2]"
          >
            Sem recomendação
          </span>
        ) : (
          <VerdictPill verdict={verdict} />
        )}
      </header>

      <p className="text-[13px] leading-[1.5] text-ink-2 mb-3" style={{ textWrap: "pretty" } as React.CSSProperties}>
        {noRecommendation
          ? "Sem recomendação gerada."
          : doseHeadline({
              doseBand: verdict === "em-rega" ? "normal" : verdict,
              doseSource: sector.dose_source,
              depthMm: sector.irrigation_depth_mm,
              runtimeMin: sector.runtime_min,
              habitualFactor: sector.habitual_factor,
              estimatedRuntimeMin: sector.estimated_runtime_min,
            })}
      </p>

      <footer className="flex items-center gap-3.5 pt-2.5 border-t border-rule-soft mt-auto">
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-mono text-[10px] tracking-[0.04em] uppercase text-ink-3">Humidade</span>
            <span className="font-mono text-[11px] text-ink-2">{Math.round(moisture * 100)}%</span>
          </div>
          <SoilBar value={moisture} tint={reforcada ? "terra" : "olive"} />
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <ConfidenceDots level={confidence} />
          <span className="font-mono text-[10px] text-ink-3">
            {dataQualityLabel(sector.source_confidence, sector.probe_health)}
          </span>
        </div>
      </footer>
    </Link>
  );
}
