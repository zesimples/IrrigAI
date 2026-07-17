"use client";

import { useEffect, useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterDeviationsResponse } from "@/types";

import { formatDecimal } from "@/lib/utils";

interface Props {
  farmId: string;
  embedded?: boolean;
}

export function FlowmeterDeviationWarnings({ farmId, embedded = false }: Props) {
  const [data, setData] = useState<FlowmeterDeviationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const fetchDeviations = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await flowmeterApi.deviations(farmId);
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao carregar desvios");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDeviations();
  }, [farmId]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalIssues = data
    ? data.deviating.length + data.insufficient_data.length
    : 0;

  const content = (
    <div className="px-4 py-3 space-y-2">
      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-2 animate-pulse">
          <div className="h-3 bg-surface-subtle rounded w-4/5" />
          <div className="h-3 bg-surface-subtle rounded w-3/5" />
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="flex items-center gap-2">
          <p className="text-sm text-terra">{error}</p>
          <button
            onClick={fetchDeviations}
            className="text-xs text-ink-3 hover:text-ink-1 underline"
          >
            Tentar novamente
          </button>
        </div>
      )}

      {/* All OK */}
      {data && !loading && totalIssues === 0 && (
        <p className="text-sm text-green-600 flex items-center gap-1.5">
          <span>✓</span>
          <span>Dotação dentro do normal</span>
        </p>
      )}

      {/* Deviating sectors */}
      {data && !loading && data.deviating.length > 0 && (
        <div className="space-y-1.5">
          {data.deviating.map((s) => (
            <div
              key={s.sector_id}
              className="flex items-center justify-between text-xs"
            >
              <span className="text-ink-2 truncate mr-2">{s.sector_name}</span>
              <div className="flex items-center gap-2 shrink-0">
                <span
                  className={
                    s.direction === "above"
                      ? "text-terra font-medium"
                      : "text-amber-600 font-medium"
                  }
                >
                  {s.direction === "above" ? "▲ +" : "▼ −"}
                  {formatDecimal(Math.abs(s.deviation_pct ?? 0), 1)}%
                </span>
                <span className="text-ink-4">
                  {(s.sector_avg_m3ha != null ? formatDecimal(s.sector_avg_m3ha, 1) : undefined)} m³/ha/rega
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Insufficient data sectors */}
      {data && !loading && data.insufficient_data.length > 0 && (
        <div className="border-t border-rule-soft pt-2 space-y-1">
          <p className="text-xs text-ink-4">Dados insuficientes:</p>
          {data.insufficient_data.map((s) => (
            <div
              key={s.sector_id}
              className="flex items-center justify-between text-xs"
            >
              <span className="text-ink-3 truncate mr-2">{s.sector_name}</span>
              <span className="text-ink-4 shrink-0">
                {s.reason === "insufficient_events"
                  ? `${s.event_count} rega${s.event_count !== 1 ? "s" : ""} detetada${s.event_count !== 1 ? "s" : ""}`
                  : "sem sectores comparáveis"}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Crop averages footnote + refresh */}
      {data && !loading && (
        <div className="flex items-center justify-between pt-1 border-t border-rule-soft">
          <span className="text-xs text-ink-4">
            {Object.entries(data.crop_averages)
              .map(
                ([crop, avg]) =>
                  `${crop === "almond" ? "Amendoal" : crop === "olive" ? "Olival" : crop} ${formatDecimal(avg, 1)} m³/ha`,
              )
              .join(" · ")}
          </span>
          <button
            onClick={fetchDeviations}
            className="text-xs text-ink-3 hover:text-ink-1 underline shrink-0 ml-2"
          >
            Atualizar
          </button>
        </div>
      )}
    </div>
  );

  if (embedded) {
    return content;
  }

  return (
    <div className="border border-rule-soft rounded-lg overflow-hidden bg-white">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-surface-subtle cursor-pointer select-none"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2">
          <span className="text-base">⚠️</span>
          <span className="text-sm font-semibold text-ink-1">
            Desvios de Dotação — {data?.period_days ?? 7} dias
          </span>
          {!loading && data && totalIssues > 0 && (
            <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
              {totalIssues}
            </span>
          )}
        </div>
        <span className="text-ink-3 text-xs">{collapsed ? "▶" : "▼"}</span>
      </div>

      {!collapsed && content}
    </div>
  );
}
