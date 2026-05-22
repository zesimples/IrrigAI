"use client";

import { useState } from "react";
import type { FlowmeterSectorDashboard } from "@/types";
import { FlowmeterSparkline } from "./FlowmeterSparkline";
import { FlowmeterSectorDetail } from "./FlowmeterSectorDetail";

interface Props {
  sector: FlowmeterSectorDashboard;
  period: "7d" | "30d" | "season";
}

function statusColor(lastIrrigation: string | null): string {
  if (!lastIrrigation) return "#d1cfc9";
  const daysAgo = (Date.now() - new Date(lastIrrigation).getTime()) / 86_400_000;
  if (daysAgo > 7) return "#dc2626";
  if (daysAgo > 3) return "#d97706";
  return "#6b9e3a";
}

function relativeDate(iso: string | null): string {
  if (!iso) return "sem dados";
  const daysAgo = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (daysAgo === 0) return "hoje " + new Date(iso).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  if (daysAgo === 1) return "ontem " + new Date(iso).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  return `há ${daysAgo} dias`;
}

export function FlowmeterSectorRow({ sector, period }: Props) {
  const [expanded, setExpanded] = useState(false);
  const dot = statusColor(sector.last_irrigation);

  return (
    <>
      <div
        className="grid items-center border-b border-rule-soft cursor-pointer hover:bg-surface-subtle transition-colors"
        style={{ gridTemplateColumns: "56px 80px 120px 110px 90px 72px 1fr", padding: "9px 18px" }}
        onClick={() => setExpanded((v) => !v)}
        role="button"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-1.5">
          <span className="shrink-0 rounded-full" style={{ width: 7, height: 7, background: dot }} />
          <span className="text-sm font-semibold text-ink-1">{sector.sector_name}</span>
        </div>
        <span className="text-xs text-ink-3 capitalize">
          {sector.crop === "almond" ? "Amendoal" : "Olival"}
        </span>
        <span className="text-xs" style={{ color: dot === "#dc2626" ? "#dc2626" : dot === "#d97706" ? "#d97706" : "#374151" }}>
          {relativeDate(sector.last_irrigation)}
        </span>
        <span className="text-sm font-semibold text-ink-1">
          {sector.last_event_m3_ha != null ? (
            <>{sector.last_event_m3_ha.toFixed(1)} <span className="text-xs font-normal text-ink-3">m³/ha</span></>
          ) : (
            <span className="text-ink-3">—</span>
          )}
        </span>
        <span className="text-sm font-semibold text-ink-1">
          {sector.total_m3_ha > 0 ? sector.total_m3_ha.toFixed(1) : <span className="text-ink-3">—</span>}
        </span>
        <span className="text-sm text-ink-2">{sector.num_events}</span>
        <FlowmeterSparkline
          data={sector.daily_breakdown.slice(-7)}
          barColor={dot === "#dc2626" ? "#dc2626" : dot === "#d97706" ? "#d97706" : "#6b9e3a"}
        />
      </div>
      {expanded && <FlowmeterSectorDetail sectorId={sector.sector_id} period={period} />}
    </>
  );
}
