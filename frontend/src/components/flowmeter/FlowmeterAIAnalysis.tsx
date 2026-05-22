"use client";

import { useEffect, useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterAnalysisResponse } from "@/types";

type Period = "7d" | "30d" | "season";

const PERIOD_DAYS: Record<Period, number> = {
  "7d": 7,
  "30d": 30,
  season: 90,
};

interface Props {
  farmId: string;
  period: Period;
}

function trendIcon(trend: string): string {
  if (trend === "increasing") return "↑";
  if (trend === "decreasing") return "↓";
  return "═";
}

export function FlowmeterAIAnalysis({ farmId, period }: Props) {
  const [data, setData] = useState<FlowmeterAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  // Reset analysis when period changes
  useEffect(() => {
    setData(null);
    setError(null);
  }, [period]);

  const runAnalysis = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const result = await flowmeterApi.analysis(farmId, {
        period_days: PERIOD_DAYS[period],
        language: "pt",
        force_refresh: forceRefresh,
      });
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao carregar análise");
    } finally {
      setLoading(false);
    }
  };

  const periodLabel =
    period === "7d"
      ? "Últimos 7 dias"
      : period === "30d"
        ? "Últimos 30 dias"
        : "Campanha";

  return (
    <div className="border border-rule-soft rounded-lg mx-4 my-3 overflow-hidden bg-white">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-surface-subtle cursor-pointer select-none"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2">
          <span className="text-base">📊</span>
          <span className="text-sm font-semibold text-ink-1">
            Análise de Consumo — {periodLabel}
          </span>
        </div>
        <span className="text-ink-3 text-xs">{collapsed ? "▶" : "▼"}</span>
      </div>

      {!collapsed && (
        <div className="px-4 py-3 space-y-3">
          {/* Not-yet-fetched state */}
          {!data && !loading && !error && (
            <div className="flex items-center gap-3">
              <p className="text-sm text-ink-3">
                Análise de consumo com IA — sob pedido.
              </p>
              <button
                onClick={() => runAnalysis(false)}
                className="px-3 py-1.5 text-xs font-medium bg-ink-1 text-white rounded hover:bg-ink-2 transition-colors"
              >
                Analisar com IA
              </button>
            </div>
          )}

          {/* Loading skeleton */}
          {loading && (
            <div className="space-y-2 animate-pulse">
              <div className="h-3 bg-surface-subtle rounded w-4/5" />
              <div className="h-3 bg-surface-subtle rounded w-3/5" />
              <div className="h-3 bg-surface-subtle rounded w-2/3" />
              <div className="h-3 bg-surface-subtle rounded w-1/2" />
            </div>
          )}

          {/* Error */}
          {error && !loading && (
            <div className="flex items-center gap-2">
              <p className="text-sm text-terra">{error}</p>
              <button
                onClick={() => runAnalysis(false)}
                className="text-xs text-ink-3 hover:text-ink-1 underline"
              >
                Tentar novamente
              </button>
            </div>
          )}

          {/* Analysis result */}
          {data && !loading && (
            <>
              <p className="text-sm text-ink-2 leading-relaxed whitespace-pre-line">
                {data.analysis}
              </p>

              {/* Indicator row */}
              <div className="border-t border-rule-soft pt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
                <span>
                  Total:{" "}
                  <strong className="text-ink-1">
                    {data.statistics.total_m3_ha.toLocaleString("pt-PT", {
                      maximumFractionDigits: 0,
                    })}{" "}
                    m³/ha
                  </strong>
                </span>
                <span>
                  Eventos:{" "}
                  <strong className="text-ink-1">
                    {data.statistics.total_events}
                  </strong>
                </span>
                <span>
                  Tendência:{" "}
                  <strong className="text-ink-1">
                    {trendIcon(data.statistics.trend)}
                  </strong>
                </span>
                {data.statistics.typical_start_hour != null && (
                  <span>
                    Hora típica:{" "}
                    <strong className="text-ink-1">
                      {String(data.statistics.typical_start_hour).padStart(2, "0")}:00
                    </strong>
                  </span>
                )}
                {data.statistics.stopped_sectors.length > 0 && (
                  <span className="text-amber-600">
                    Parados:{" "}
                    <strong>{data.statistics.stopped_sectors.length} setores</strong>
                  </span>
                )}
                {Object.entries(data.statistics.by_crop).map(([crop, s]) => (
                  <span key={crop}>
                    {crop === "almond" ? "Amendoal" : "Olival"}:{" "}
                    <strong className="text-ink-1">
                      {s.avg_per_sector.toFixed(1)}/setor
                    </strong>
                  </span>
                ))}
              </div>

              <div className="flex justify-end">
                <button
                  onClick={() => runAnalysis(true)}
                  className="text-xs text-ink-3 hover:text-ink-1 underline"
                >
                  Atualizar análise
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
