"use client";

import Link from "next/link";
import type { SectorSummary } from "@/types";
import { STAGE_LABELS } from "@/lib/cropConfig";
import { VerdictPill, type Verdict } from "./VerdictPill";
import { SoilBar } from "./SoilBar";
import { ConfidenceDots, confidenceLabel, type Confidence } from "./ConfidenceDots";

interface EditorialSectorCardProps {
  sector: SectorSummary;
  farmId: string;
}

function toVerdict(action: string | null): Verdict {
  if (action === "irrigate") return "regar";
  return "nao";
}

function toConfidence(level: string | null, probeHealth: string): Confidence {
  if (probeHealth === "no_probes" || probeHealth === "no_readings") return "sem-sonda";
  if (level === "high") return "alta";
  if (level === "medium") return "media";
  if (level === "low") return "baixa";
  return "sem-sonda";
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
  const verdict = toVerdict(sector.action);
  const confidence = toConfidence(sector.confidence_level, sector.probe_health);
  const moisture = toMoisture(sector.depletion_pct, sector.rootzone_status);
  const regar = verdict === "regar";
  const stageLabel = STAGE_LABELS[sector.current_stage ?? ""] ?? sector.current_stage ?? "—";
  const id = sectorId(sector.sector_name);
  const suffix = sectorSuffix(sector.sector_name, "");

  return (
    <Link
      href={`/farms/${farmId}/sectors/${sector.sector_id}`}
      className={`relative block min-h-[170px] border-r border-b border-rule p-[18px_20px_16px] transition-colors hover:bg-paper-in ${regar ? "bg-terra-bg" : "bg-card"}`}
    >
      {/* Left accent bar for "regar" */}
      {regar && <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-terra rounded-l" />}

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
        <VerdictPill verdict={verdict} />
      </header>

      {sector.action === "irrigate" && sector.irrigation_depth_mm != null && (
        <p className="text-[13px] leading-[1.5] text-ink-2 mb-3" style={{ textWrap: "pretty" } as React.CSSProperties}>
          Regar {sector.irrigation_depth_mm.toFixed(0)} mm
          {sector.runtime_min != null && ` · ${Math.floor(sector.runtime_min / 60)}h ${String(Math.round(sector.runtime_min % 60)).padStart(2, "0")}m`}
        </p>
      )}
      {sector.action !== "irrigate" && (
        <p className="text-[13px] leading-[1.5] text-ink-2 mb-3" style={{ textWrap: "pretty" } as React.CSSProperties}>
          {sector.rootzone_status === "wet" || sector.rootzone_status === "optimal"
            ? "Solo com humidade adequada."
            : sector.rootzone_status === "dry"
            ? "Solo a secar — reavaliar em breve."
            : "Sem recomendação gerada."}
        </p>
      )}

      <footer className="flex items-center gap-3.5 pt-2.5 border-t border-rule-soft mt-auto">
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-mono text-[10px] tracking-[0.04em] uppercase text-ink-3">Humidade</span>
            <span className="font-mono text-[11px] text-ink-2">{Math.round(moisture * 100)}%</span>
          </div>
          <SoilBar value={moisture} tint={regar ? "terra" : "olive"} />
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <ConfidenceDots level={confidence} />
          <span className="font-mono text-[10px] text-ink-3">{confidenceLabel(confidence)}</span>
        </div>
      </footer>
    </Link>
  );
}
