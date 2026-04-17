"use client";

import Link from "next/link";
import { WifiOff } from "lucide-react";
import type { ConfidenceLevel, RecommendationAction, SectorSummary } from "@/types";
import { CROP_LABELS, STAGE_LABELS } from "@/lib/cropConfig";

// ── Config ────────────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<RecommendationAction, string> = {
  irrigate: "Regar",
  skip: "Não Regar",
  reduce: "Reduzir",
  increase: "Aumentar",
  defer: "Adiar",
};

const ACTION_BADGE: Record<RecommendationAction, string> = {
  irrigate: "bg-irrigai-green-bg text-irrigai-green-dark",
  skip:     "bg-irrigai-gray-bg text-irrigai-text-muted",
  reduce:   "bg-irrigai-amber-bg text-irrigai-amber-dark",
  increase: "bg-irrigai-amber-bg text-irrigai-amber-dark",
  defer:    "bg-irrigai-amber-bg text-irrigai-amber-dark",
};

const CONF_DOT: Record<ConfidenceLevel, string> = {
  high:   "bg-irrigai-green",
  medium: "bg-irrigai-amber",
  low:    "bg-irrigai-red",
};

const CONF_LABELS: Record<ConfidenceLevel, string> = {
  high:   "Confiança alta",
  medium: "Confiança média",
  low:    "Confiança baixa",
};

const SOIL_FILL: Record<string, { bar: string; width: string }> = {
  dry:     { bar: "bg-irrigai-amber", width: "32%" },
  optimal: { bar: "bg-irrigai-green", width: "62%" },
  wet:     { bar: "bg-irrigai-blue",  width: "85%" },
  unknown: { bar: "bg-gray-200",      width: "0%" },
};


function relativeDay(dateStr: string): string {
  const days = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 86_400_000
  );
  if (days === 0) return "hoje";
  if (days === 1) return "há 1d";
  return `há ${days}d`;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface SectorCardProps {
  sector: SectorSummary;
  farmId: string;
}

export function SectorCard({ sector, farmId }: SectorCardProps) {
  const action = sector.action;
  const soil = SOIL_FILL[sector.rootzone_status ?? "unknown"] ?? SOIL_FILL.unknown;
  const stageName = STAGE_LABELS[sector.current_stage ?? ""] ?? sector.current_stage ?? null;

  const cropLabel = CROP_LABELS[sector.crop_type ?? ""] ?? sector.crop_type ?? "";

  return (
    <Link
      href={`/farms/${farmId}/sectors/${sector.sector_id}`}
      className="block rounded-xl border border-black/[0.08] bg-white p-4 transition-[border-color,box-shadow] hover:border-black/[0.14] hover:shadow-[0_1px_4px_rgba(0,0,0,0.05)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-irrigai-green/40"
      aria-label={`Abrir sector ${sector.sector_name}`}
    >
      {/* ── Header row ── */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="min-w-0">
          <p className="text-[14px] font-medium text-irrigai-text truncate">
            {sector.sector_name}
          </p>
          <p className="mt-0.5 text-[11px] text-irrigai-text-muted">
            {cropLabel}
            {stageName && (
              <>
                <span className="mx-1 text-irrigai-text-hint">·</span>
                {stageName}
              </>
            )}
          </p>
        </div>
        {action && (
          <span
            className={`shrink-0 rounded-full px-2.5 py-[3px] text-[11px] font-medium ${ACTION_BADGE[action]}`}
          >
            {ACTION_LABELS[action]}
          </span>
        )}
      </div>

      {/* ── Recommendation values ── */}
      {action === "irrigate" &&
        sector.irrigation_depth_mm != null ? (
        <div className="flex items-baseline gap-5 mb-3">
          <div>
            <span className="font-display text-[28px] font-[500] leading-none text-irrigai-text tracking-[-0.03em]">
              {sector.irrigation_depth_mm.toFixed(1)}
            </span>
            <span className="ml-1 text-[11px] text-irrigai-text-muted">mm</span>
          </div>
          {sector.runtime_min != null && (
            <div>
              <span className="font-display text-[28px] font-[500] leading-none text-irrigai-text tracking-[-0.03em]">
                {Math.round(sector.runtime_min)}
              </span>
              <span className="ml-1 text-[11px] text-irrigai-text-muted">min</span>
            </div>
          )}
        </div>
      ) : action === "skip" ? (
        <p className="mb-3 text-[12px] text-irrigai-text-muted leading-relaxed">
          Solo com humidade adequada.
        </p>
      ) : action === "reduce" ? (
        <p className="mb-3 text-[12px] text-irrigai-text-muted leading-relaxed">
          {sector.irrigation_depth_mm != null
            ? `Reduzir para ${sector.irrigation_depth_mm.toFixed(1)} mm.`
            : "Reduzir dose habitual."}
        </p>
      ) : action === "defer" ? (
        <p className="mb-3 text-[12px] text-irrigai-text-muted leading-relaxed">
          Adiar decisão — verificar amanhã.
        </p>
      ) : (
        <p className="mb-3 text-[12px] text-irrigai-text-hint italic">
          Sem recomendação gerada ainda.
        </p>
      )}

      {/* ── Alerts ── */}
      {sector.active_alerts > 0 && (
        <p className="mb-2.5 text-[11px] font-medium text-irrigai-red">
          {sector.active_alerts} alerta{sector.active_alerts !== 1 ? "s" : ""} activo
          {sector.active_alerts !== 1 ? "s" : ""}
        </p>
      )}

      {/* ── Footer meta ── */}
      <div className="flex items-center gap-3.5 pt-2.5 border-t border-black/[0.06] text-[11px] text-irrigai-text-muted">
        {/* No-probe / no-readings indicator */}
        {(sector.probe_health === "no_probes" || sector.probe_health === "no_readings") && (
          <span className="flex items-center gap-1 text-irrigai-text-hint" title="Sem leituras de sonda">
            <WifiOff className="h-3 w-3" />
            <span>Sem sonda</span>
          </span>
        )}

        {/* Confidence */}
        {sector.confidence_level && sector.probe_health !== "no_probes" && sector.probe_health !== "no_readings" && (
          <span className="flex items-center gap-1.5">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${CONF_DOT[sector.confidence_level]}`}
            />
            {CONF_LABELS[sector.confidence_level]}
          </span>
        )}

        {/* Rootzone bar */}
        <span className="flex items-center gap-1.5">
          Solo
          <span className="inline-block h-1 w-[48px] rounded-full bg-black/[0.06] overflow-hidden align-middle">
            <span
              className={`block h-full rounded-full ${soil.bar}`}
              style={{ width: soil.width }}
            />
          </span>
        </span>

        {/* Last irrigated */}
        {sector.last_irrigated && (
          <span className="ml-auto">{relativeDay(sector.last_irrigated)}</span>
        )}
      </div>
    </Link>
  );
}
