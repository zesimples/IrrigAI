"use client";

import { useEffect, useMemo, useState } from "react";
import type { FlowmeterSectorDashboard } from "@/types";
import { flowmeterApi } from "@/lib/api";
import { FlowmeterSectorRow } from "./FlowmeterSectorRow";
import type { DeviationInfo } from "./FlowmeterSectorRow";

type SortKey = "name" | "last_irrigation" | "total" | "events";
type CropFilter = "all" | "almond" | "olive";

interface Props {
  sectors: FlowmeterSectorDashboard[];
  period: "7d" | "30d" | "season";
  farmId: string;
}

export function FlowmeterSectorTable({ sectors, period, farmId }: Props) {
  const [cropFilter, setCropFilter] = useState<CropFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [deviationMap, setDeviationMap] = useState<Record<string, DeviationInfo>>({});

  // Fetch deviation data once on mount / farmId change
  useEffect(() => {
    flowmeterApi.deviations(farmId).then((data) => {
      const map: Record<string, DeviationInfo> = {};
      for (const s of data.deviating) {
        map[s.sector_id] = {
          type: "deviation",
          direction: s.direction,
          deviation_pct: s.deviation_pct,
        };
      }
      for (const s of data.insufficient_data) {
        map[s.sector_id] = { type: "insufficient" };
      }
      setDeviationMap(map);
    }).catch(() => {
      // Silent fail — deviation badges are non-critical
    });
  }, [farmId]);

  const filtered = useMemo(() => {
    const list = cropFilter === "all" ? sectors : sectors.filter((s) => s.crop === cropFilter);
    return [...list].sort((a, b) => {
      switch (sortKey) {
        case "last_irrigation":
          return (b.last_irrigation ?? "").localeCompare(a.last_irrigation ?? "");
        case "total":
          return b.total_m3_ha - a.total_m3_ha;
        case "events":
          return b.num_events - a.num_events;
        default:
          return a.sector_name.localeCompare(b.sector_name);
      }
    });
  }, [sectors, cropFilter, sortKey]);

  const almonds = filtered.filter((s) => s.crop === "almond");
  const olives = filtered.filter((s) => s.crop === "olive");

  return (
    <div>
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-4 sm:px-[18px] py-2 border-b border-rule-soft bg-white text-sm">
        <span className="text-xs text-ink-3">Cultura:</span>
        {(["all", "almond", "olive"] as const).map((c) => (
          <button
            key={c}
            onClick={() => setCropFilter(c)}
            className={[
              "px-2.5 py-0.5 rounded text-xs font-medium transition-colors",
              cropFilter === c
                ? "bg-olive/20 text-olive border border-olive/30"
                : "text-ink-3 border border-rule-soft hover:text-ink-2",
            ].join(" ")}
          >
            {c === "all" ? "Todos" : c === "almond" ? "Amendoal" : "Olival"}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-xs text-ink-3">
          Ordenar:
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="border border-rule-soft rounded px-1.5 py-0.5 text-xs text-ink-2 bg-white"
          >
            <option value="name">Setor</option>
            <option value="last_irrigation">Última rega</option>
            <option value="total">Total</option>
            <option value="events">Nº regas</option>
          </select>
        </div>
      </div>

      {/* Column headers */}
      <div
        className="grid text-[10px] font-semibold text-ink-3 uppercase tracking-wide bg-surface-subtle border-b border-rule-soft"
        style={{ gridTemplateColumns: "56px 80px 120px 110px 90px 72px 1fr 80px", padding: "6px 18px" }}
      >
        <span>Setor</span>
        <span>Cultura</span>
        <span>Último evento</span>
        <span>Última dotação</span>
        <span>Total período</span>
        <span>Nº regas</span>
        <span>Gráfico 7d</span>
        <span className="text-right">Desvio</span>
      </div>

      {almonds.length > 0 && cropFilter !== "olive" && (
        <>
          <div className="px-[18px] py-1.5 text-[10px] font-semibold text-ink-3 uppercase tracking-wide bg-surface-subtle border-y border-rule-soft">
            Amendoal — {almonds.length} setores
          </div>
          {almonds.map((s) => (
            <FlowmeterSectorRow
              key={s.sector_id}
              sector={s}
              period={period}
              deviation={deviationMap[s.sector_id] ?? null}
            />
          ))}
        </>
      )}

      {olives.length > 0 && cropFilter !== "almond" && (
        <>
          <div className="px-[18px] py-1.5 text-[10px] font-semibold text-ink-3 uppercase tracking-wide bg-surface-subtle border-y border-rule-soft">
            Olival — {olives.length} setores
          </div>
          {olives.map((s) => (
            <FlowmeterSectorRow
              key={s.sector_id}
              sector={s}
              period={period}
              deviation={deviationMap[s.sector_id] ?? null}
            />
          ))}
        </>
      )}
    </div>
  );
}
