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

  return (
    <div style={{
      margin: '22px 44px 0',
      background: '#f3f1e8',
      border: '1px solid rgba(107,143,78,0.2)',
      borderRadius: 10,
      padding: '18px 22px',
    }}>
      {/* Eyebrow */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 6, height: 6, borderRadius: 999, background: '#6b8f4e', flexShrink: 0 }} />
        <span style={{
          fontFamily: 'var(--font-jetbrains, ui-monospace)',
          fontSize: 10.5,
          color: '#4a6a36',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
        }}>Análise de consumo · IA</span>
      </div>

      {/* Prompt text + button (pre-analysis) */}
      {!data && !loading && !error && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
          <p style={{
            margin: 0,
            fontFamily: 'var(--font-fraunces)',
            fontSize: 17,
            fontWeight: 500,
            color: '#2a2520',
            letterSpacing: '-0.01em',
            lineHeight: 1.4,
          }}>
            Posso analisar os padrões de consumo dos caudalímetros — eventos de rega, dotações por setor e desvios entre culturas.{' '}
            <em style={{ fontFamily: 'var(--font-instrument)', color: '#5a5048', fontStyle: 'italic' }}>
              Demora cerca de 30 segundos.
            </em>
          </p>
          <button
            onClick={() => runAnalysis(false)}
            style={{
              background: '#2a2520',
              color: '#f5f0e6',
              border: 'none',
              padding: '12px 22px',
              borderRadius: 8,
              fontSize: 13.5,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 9,
              flexShrink: 0,
              boxShadow: '0 6px 18px rgba(42,37,32,0.18)',
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: 999, background: '#b84a2a' }} />
            Analisar com IA
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
          <p style={{ margin: 0, fontFamily: 'var(--font-fraunces)', fontSize: 17, fontWeight: 500, color: '#2a2520', letterSpacing: '-0.01em', lineHeight: 1.4 }}>
            A analisar o consumo da herdade…
          </p>
          <button
            disabled
            aria-busy
            style={{
              background: '#2a2520',
              color: '#f5f0e6',
              border: 'none',
              padding: '12px 22px',
              borderRadius: 8,
              fontSize: 13.5,
              fontWeight: 600,
              cursor: 'not-allowed',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 9,
              flexShrink: 0,
              opacity: 0.75,
            }}
          >
            <span style={{
              width: 6, height: 6, borderRadius: 999, background: '#b84a2a',
              animation: 'pulse 1.2s ease-in-out infinite',
            }} />
            A analisar…
          </button>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <p style={{ margin: 0, fontFamily: 'var(--font-fraunces)', fontSize: 15, color: '#b84a2a' }}>{error}</p>
          <button
            onClick={() => runAnalysis(false)}
            style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 13, color: '#8a7f74', textDecoration: 'underline' }}
          >
            Tentar novamente
          </button>
        </div>
      )}

      {/* Result */}
      {data && !loading && (
        <>
          <p style={{
            margin: '0 0 12px',
            fontFamily: 'var(--font-fraunces)',
            fontSize: 15,
            lineHeight: 1.6,
            color: '#2a2520',
            whiteSpace: 'pre-line',
          }}>
            {data.analysis}
          </p>
          <div style={{
            borderTop: '1px solid #dcd3c2',
            paddingTop: 10,
            display: 'flex',
            flexWrap: 'wrap',
            gap: '4px 16px',
            fontFamily: 'var(--font-jetbrains, ui-monospace)',
            fontSize: 10.5,
            color: '#8a7f74',
            letterSpacing: '0.04em',
          }}>
            <span>Total <strong style={{ color: '#2a2520' }}>{data.statistics.total_m3_ha.toLocaleString('pt-PT', { maximumFractionDigits: 0 })} m³/ha</strong></span>
            <span>Eventos <strong style={{ color: '#2a2520' }}>{data.statistics.total_events}</strong></span>
            <span>Tendência <strong style={{ color: '#2a2520' }}>{trendIcon(data.statistics.trend)}</strong></span>
            {Object.entries(data.statistics.by_crop).map(([crop, s]) => (
              <span key={crop}>
                {crop === 'almond' ? 'Amendoal' : 'Olival'} <strong style={{ color: '#2a2520' }}>{s.avg_per_sector.toFixed(1)}/sector</strong>
              </span>
            ))}
            <button
              onClick={() => runAnalysis(true)}
              style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 12, color: '#8a7f74', textDecoration: 'underline' }}
            >
              Atualizar análise
            </button>
          </div>
        </>
      )}
    </div>
  );
}
