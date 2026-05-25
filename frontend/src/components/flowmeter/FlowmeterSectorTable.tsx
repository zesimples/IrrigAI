"use client";

import { useMemo, useState } from "react";
import type { FlowmeterSectorDashboard } from "@/types";
import { FlowmeterSectorRow } from "./FlowmeterSectorRow";
import { FlowmeterDeviationWarnings } from "./FlowmeterDeviationWarnings";

type SortKey = "name" | "last_irrigation" | "total" | "events";
type CropFilter = "all" | "almond" | "olive";
type ActiveTab = "list" | "deviations";

interface Props {
  sectors: FlowmeterSectorDashboard[];
  period: "7d" | "30d" | "season";
  farmId: string;
}

export function FlowmeterSectorTable({ sectors, period, farmId }: Props) {
  const [cropFilter, setCropFilter] = useState<CropFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [activeTab, setActiveTab] = useState<ActiveTab>("list");

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
      {/* Filter / tab bar */}
      <div className="flex items-center gap-3 px-4 sm:px-[18px] py-2 border-b border-rule-soft bg-white text-sm">
        {/* Tab buttons */}
        <div className="flex gap-1.5">
          {(["list", "deviations"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={[
                "px-2.5 py-0.5 rounded text-xs font-medium transition-colors",
                activeTab === tab
                  ? "bg-ink-1 text-white"
                  : "text-ink-3 border border-rule-soft hover:text-ink-2",
              ].join(" ")}
            >
              {tab === "list" ? "Sectores" : "Desvios"}
            </button>
          ))}
        </div>

        {/* Crop filter + sort — only in list tab */}
        {activeTab === "list" && (
          <>
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
          </>
        )}
      </div>

      {/* List tab: column headers + sector rows */}
      {activeTab === "list" && (
        <>
          <div
            className="grid text-[10px] font-semibold text-ink-3 uppercase tracking-wide bg-surface-subtle border-b border-rule-soft"
            style={{ gridTemplateColumns: "56px 80px 120px 110px 90px 72px 1fr", padding: "6px 18px" }}
          >
            <span>Setor</span>
            <span>Cultura</span>
            <span>Último evento</span>
            <span>Última dotação</span>
            <span>Total período</span>
            <span>Nº regas</span>
            <span>Gráfico 7d</span>
          </div>

          {almonds.length > 0 && cropFilter !== "olive" && (
            <>
              <div className="px-[18px] py-1.5 text-[10px] font-semibold text-ink-3 uppercase tracking-wide bg-surface-subtle border-y border-rule-soft">
                Amendoal — {almonds.length} setores
              </div>
              {almonds.map((s) => (
                <FlowmeterSectorRow key={s.sector_id} sector={s} period={period} />
              ))}
            </>
          )}

          {olives.length > 0 && cropFilter !== "almond" && (
            <>
              <div className="px-[18px] py-1.5 text-[10px] font-semibold text-ink-3 uppercase tracking-wide bg-surface-subtle border-y border-rule-soft">
                Olival — {olives.length} setores
              </div>
              {olives.map((s) => (
                <FlowmeterSectorRow key={s.sector_id} sector={s} period={period} />
              ))}
            </>
          )}
        </>
      )}

      {/* Deviations tab */}
      {activeTab === "deviations" && (
        <FlowmeterDeviationWarnings farmId={farmId} embedded />
      )}
    </div>
  );
}
