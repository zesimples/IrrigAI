"use client";

import { useEffect, useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterDashboardResponse } from "@/types";
import { FlowmeterSectorTable } from "./FlowmeterSectorTable";
import { FlowmeterAIAnalysis } from "./FlowmeterAIAnalysis";

type Period = "7d" | "30d" | "season";

interface Props {
  farmId: string;
}

export function FlowmeterDashboard({ farmId }: Props) {
  const [period, setPeriod] = useState<Period>("7d");
  const [data, setData] = useState<FlowmeterDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    flowmeterApi
      .dashboard(farmId, period)
      .then(setData)
      .catch((e: Error) => setError(e.message ?? "Erro ao carregar dados"))
      .finally(() => setLoading(false));
  }, [farmId, period]);

  return (
    <div>
      {/* Summary bar */}
      <div className="flex flex-wrap items-center gap-5 px-4 sm:px-[18px] py-2.5 bg-surface-subtle border-b border-rule-soft">
        {data && (
          <>
            <div>
              <span className="text-[11px] text-ink-3 uppercase tracking-wide">
                Total {period === "7d" ? "7d" : period === "30d" ? "30d" : "campanha"}
              </span>
              <span className="text-base font-bold text-ink-1 ml-2">
                {data.total_m3_ha.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} m³/ha
              </span>
            </div>
            <span className="text-rule-soft">|</span>
            <div className="text-sm text-ink-3 space-x-3">
              {Object.entries(data.by_crop).map(([crop, s]) => (
                <span key={crop}>
                  {crop === "almond" ? "Amendoal" : "Olival"}{" "}
                  <span className="text-ink-1 font-semibold">
                    {s.total_m3_ha.toLocaleString("pt-PT", { maximumFractionDigits: 0 })}
                  </span>{" "}
                  <span className="text-ink-4">m³/ha</span>
                </span>
              ))}
            </div>
          </>
        )}
        {loading && <span className="text-sm text-ink-3">A carregar...</span>}
        <div className="ml-auto flex gap-1.5">
          {(["7d", "30d", "season"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={[
                "px-2.5 py-1 text-xs font-medium rounded transition-colors",
                period === p
                  ? "bg-ink-1 text-white"
                  : "text-ink-3 border border-rule-soft hover:text-ink-2",
              ].join(" ")}
            >
              {p === "season" ? "Campanha" : p}
            </button>
          ))}
        </div>
      </div>

      {/* AI analysis */}
      <FlowmeterAIAnalysis farmId={farmId} period={period} />

      {error && (
        <div className="px-[18px] py-4 text-sm text-terra">{error}</div>
      )}

      {data && <FlowmeterSectorTable sectors={data.sectors} period={period} farmId={farmId} />}
    </div>
  );
}
