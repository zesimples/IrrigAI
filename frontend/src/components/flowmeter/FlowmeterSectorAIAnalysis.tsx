"use client";

import { useEffect, useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterSectorAnalysisResponse } from "@/types";

import { formatDecimal } from "@/lib/utils";

type Period = "7d" | "30d" | "season";

const PERIOD_DAYS: Record<Period, number> = {
  "7d": 7,
  "30d": 30,
  season: 90,
};

const PATTERN_DOT: Record<string, string> = {
  regular: "bg-green-500",
  irregular: "bg-amber-500",
  stopped: "bg-red-500",
  declining: "bg-amber-500",
  increasing: "bg-amber-500",
  insufficient_data: "bg-gray-400",
};

const PATTERN_LABEL: Record<string, string> = {
  regular: "Regular",
  irregular: "Irregular",
  stopped: "Parado",
  declining: "Decrescente",
  increasing: "Crescente",
  insufficient_data: "Dados insuficientes",
};

interface Props {
  sectorId: string;
  period: Period;
}

export function FlowmeterSectorAIAnalysis({ sectorId, period }: Props) {
  const [data, setData] = useState<FlowmeterSectorAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setData(null);
    setError(null);
  }, [sectorId, period]);

  const runAnalysis = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const result = await flowmeterApi.sectorAnalysis(sectorId, {
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

  const dotClass = data
    ? (PATTERN_DOT[data.statistics.pattern] ?? "bg-gray-400")
    : "bg-gray-400";
  const patternLabel = data
    ? (PATTERN_LABEL[data.statistics.pattern] ?? data.statistics.pattern)
    : "";

  return (
    <div className="border-t border-rule-soft pt-3 mt-2">
      {/* Header */}
      <div
        className="flex items-center justify-between cursor-pointer select-none mb-2"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span className="text-xs font-semibold text-ink-3 uppercase tracking-wide">
          📊 Análise AI do Setor
        </span>
        <span className="text-ink-3 text-xs">{collapsed ? "▶" : "▼"}</span>
      </div>

      {!collapsed && (
        <div className="space-y-2">
          {/* Not-yet-fetched */}
          {!data && !loading && !error && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => runAnalysis(false)}
                className="px-2.5 py-1 text-xs font-medium bg-ink text-white rounded hover:bg-ink-2 transition-colors"
              >
                Analisar
              </button>
              <span className="text-xs text-ink-3">
                Análise de consumo deste setor
              </span>
            </div>
          )}

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
              <p className="text-xs text-terra">{error}</p>
              <button
                onClick={() => runAnalysis(false)}
                className="text-xs text-ink-3 hover:text-ink-1 underline"
              >
                Tentar novamente
              </button>
            </div>
          )}

          {/* Result */}
          {data && !loading && (
            <>
              <p className="text-sm text-ink-2 leading-relaxed">
                {data.analysis}
              </p>
              <div className="border-t border-rule-soft pt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-3">
                <span>
                  Média/evento:{" "}
                  <strong className="text-ink-1">
                    {formatDecimal(data.statistics.avg_m3_ha_per_event, 1)} m³/ha
                  </strong>
                </span>
                {data.statistics.avg_interval_days != null && (
                  <span>
                    Intervalo:{" "}
                    <strong className="text-ink-1">
                      {formatDecimal(data.statistics.avg_interval_days, 1)} dias
                    </strong>
                  </span>
                )}
                {data.statistics.avg_duration_minutes != null && (
                  <span>
                    Duração:{" "}
                    <strong className="text-ink-1">
                      {Math.floor(data.statistics.avg_duration_minutes / 60)}h
                      {String(
                        Math.round(data.statistics.avg_duration_minutes % 60),
                      ).padStart(2, "0")}
                    </strong>
                  </span>
                )}
                {data.statistics.vs_crop_avg_pct != null && (
                  <span>
                    vs. média:{" "}
                    <strong
                      className={
                        data.statistics.vs_crop_avg_pct >= 0
                          ? "text-ink-1"
                          : "text-terra"
                      }
                    >
                      {data.statistics.vs_crop_avg_pct >= 0 ? "+" : ""}
                      {formatDecimal(data.statistics.vs_crop_avg_pct, 1)}%
                    </strong>
                  </span>
                )}
                <span className="flex items-center gap-1">
                  Padrão:{" "}
                  <span
                    className={`inline-block w-2 h-2 rounded-full ${dotClass}`}
                  />
                  <strong className="text-ink-1">{patternLabel}</strong>
                </span>
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => runAnalysis(true)}
                  className="text-xs text-ink-3 hover:text-ink-1 underline"
                >
                  Atualizar
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
