"use client";

import { useEffect, useMemo, useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterDashboardResponse, FlowmeterDeviationsResponse } from "@/types";
import { FlowmeterSectorTable } from "./FlowmeterSectorTable";
import { FlowmeterAIAnalysis } from "./FlowmeterAIAnalysis";

type Period = "7d" | "30d" | "season";

interface Props {
  farmId: string;
}

export function FlowmeterDashboard({ farmId }: Props) {
  const [period, setPeriod] = useState<Period>("7d");
  const [data, setData] = useState<FlowmeterDashboardResponse | null>(null);
  const [deviations, setDeviations] = useState<FlowmeterDeviationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      flowmeterApi.dashboard(farmId, period),
      flowmeterApi.deviations(farmId),
    ])
      .then(([dashData, devData]) => {
        setData(dashData);
        setDeviations(devData);
      })
      .catch((e: Error) => setError(e.message ?? "Erro ao carregar dados"))
      .finally(() => setLoading(false));
  }, [farmId, period]);

  const stats = useMemo(() => {
    if (!data) return null;
    const totalRegas = data.sectors.reduce((s, r) => s + r.num_events, 0);
    const semDados = data.sectors.filter((s) => s.num_events === 0).length;
    const avgPerRega = totalRegas > 0 ? data.total_m3_ha / totalRegas : null;
    const almondTotal = data.by_crop['almond']?.total_m3_ha ?? 0;
    const oliveTotal = data.by_crop['olive']?.total_m3_ha ?? 0;
    const almondSectors = data.sectors.filter((s) => s.crop === 'almond' && s.num_events > 0).length;
    const oliveSectors = data.sectors.filter((s) => s.crop === 'olive' && s.num_events > 0).length;
    const almondPct = data.total_m3_ha > 0 ? Math.round((almondTotal / data.total_m3_ha) * 100) : 0;
    const olivePct = data.total_m3_ha > 0 ? Math.round((oliveTotal / data.total_m3_ha) * 100) : 0;
    return { totalRegas, semDados, avgPerRega, almondTotal, oliveTotal, almondSectors, oliveSectors, almondPct, olivePct };
  }, [data]);

  // Build sector_id → deviation_pct | null from the backend deviations response.
  // Sectors in `deviating` carry a pre-computed deviation_pct; all others are null.
  const deviationMap = useMemo((): Record<string, number | null> => {
    if (!deviations || !data) return {};
    const map: Record<string, number | null> = {};
    for (const s of data.sectors) map[s.sector_id] = null;
    for (const d of deviations.deviating) map[d.sector_id] = d.deviation_pct;
    return map;
  }, [deviations, data]);

  const periodLabel = period === '7d' ? 'últimos 7 dias' : period === '30d' ? 'últimos 30 dias' : 'campanha';
  const periodShort = period === 'season' ? 'Campanha' : period;

  return (
    <div style={{ width: '100%', minHeight: '100%', background: '#f5f0e6', color: '#2a2520' }}>

      {/* HERO */}
      <section style={{ padding: '24px 44px 22px', borderBottom: '1px solid #dcd3c2' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 28 }}>
          {/* Left: eyebrow + headline + sub */}
          <div style={{ flex: 1, maxWidth: 760 }}>
            <div style={{
              fontFamily: 'var(--font-jetbrains, ui-monospace)',
              fontSize: 10,
              color: '#b84a2a',
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              marginBottom: 8,
            }}>
              Consumo · {periodLabel}
            </div>

            {loading ? (
              <div style={{ height: 46, background: '#ece5d5', borderRadius: 6, width: '60%', marginBottom: 12 }} />
            ) : data ? (
              <>
                <h1 style={{
                  margin: 0,
                  fontFamily: 'var(--font-fraunces)',
                  fontSize: 38,
                  fontWeight: 500,
                  lineHeight: 1.08,
                  letterSpacing: '-0.025em',
                  color: '#2a2520',
                }}>
                  A herdade consumiu{' '}
                  <em style={{ fontFamily: 'var(--font-instrument)', color: '#b84a2a', fontStyle: 'italic' }}>
                    {data.total_m3_ha.toLocaleString('pt-PT', { maximumFractionDigits: 0 })} m³/ha
                  </em>
                  {stats && stats.almondPct > 0 && stats.olivePct > 0 && (
                    <> de água — {stats.almondPct}% no amendoal, {stats.olivePct}% no olival.</>
                  )}
                  {(!stats || stats.almondPct === 0 || stats.olivePct === 0) && ' de água.'}
                </h1>
                {stats && (
                  <p style={{
                    margin: '12px 0 0',
                    fontFamily: 'var(--font-dm-sans, system-ui)',
                    fontSize: 14,
                    lineHeight: 1.55,
                    color: '#5a5048',
                    maxWidth: 620,
                  }}>
                    {stats.almondSectors + stats.oliveSectors > 0
                      ? `${stats.almondSectors + stats.oliveSectors} sector${stats.almondSectors + stats.oliveSectors !== 1 ? 'es' : ''} ${stats.almondSectors + stats.oliveSectors !== 1 ? 'tiveram' : 'teve'} regas`
                      : 'Nenhum sector teve regas'}
                    {stats.semDados > 0 && `; ${stats.semDados} caudalímetro${stats.semDados !== 1 ? 's' : ''} sem dados`}.
                    {stats.avgPerRega && ` O consumo médio por rega situou-se em `}
                    {stats.avgPerRega && (
                      <strong style={{ color: '#2a2520', fontWeight: 600 }}>
                        {stats.avgPerRega.toFixed(1)} m³/ha
                      </strong>
                    )}
                    {stats.avgPerRega && '.'}
                  </p>
                )}
              </>
            ) : error ? (
              <p style={{ fontFamily: 'var(--font-fraunces)', fontSize: 17, color: '#b84a2a' }}>{error}</p>
            ) : null}
          </div>

          {/* Right: period toggle */}
          <div style={{ flexShrink: 0 }}>
            <div style={{
              fontFamily: 'var(--font-jetbrains, ui-monospace)',
              fontSize: 9.5,
              color: '#8a7f74',
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              marginBottom: 6,
              textAlign: 'right',
            }}>Período</div>
            <div style={{
              display: 'inline-flex',
              border: '1px solid #dcd3c2',
              borderRadius: 8,
              overflow: 'hidden',
              background: '#fbf8f1',
            }}>
              {(['7d', '30d', 'season'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  style={{
                    border: 'none',
                    cursor: 'pointer',
                    padding: '8px 14px',
                    fontFamily: 'var(--font-fraunces)',
                    fontSize: 13,
                    fontWeight: period === p ? 600 : 400,
                    background: period === p ? '#2a2520' : 'transparent',
                    color: period === p ? '#f5f0e6' : '#5a5048',
                    letterSpacing: '-0.005em',
                  }}
                >
                  {p === 'season' ? 'Campanha' : p}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* KPI strip */}
        {data && stats && (
          <div style={{
            marginTop: 24,
            display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            borderTop: '1px solid #e8e0d0',
            borderBottom: '1px solid #e8e0d0',
          }}>
            {[
              { k: `Total ${periodShort}`, v: data.total_m3_ha.toLocaleString('pt-PT', { maximumFractionDigits: 0 }), u: 'm³/ha', sub: 'todas as culturas', tint: '#2a2520', bar: undefined },
              { k: 'Amendoal', v: stats.almondTotal.toLocaleString('pt-PT', { maximumFractionDigits: 0 }), u: 'm³/ha', sub: `${stats.almondSectors} sectores activos`, tint: '#b84a2a', bar: data.total_m3_ha > 0 ? stats.almondTotal / data.total_m3_ha : 0 },
              { k: 'Olival', v: stats.oliveTotal.toLocaleString('pt-PT', { maximumFractionDigits: 0 }), u: 'm³/ha', sub: `${stats.oliveSectors} sectores activos`, tint: '#6b8f4e', bar: data.total_m3_ha > 0 ? stats.oliveTotal / data.total_m3_ha : 0 },
              { k: 'Regas totais', v: String(stats.totalRegas), u: undefined, sub: stats.avgPerRega ? `dose média ${stats.avgPerRega.toFixed(1)} m³` : 'sem regas', tint: '#2a2520', bar: undefined },
              { k: 'Caudalímetros sem dados', v: String(stats.semDados), u: `de ${data.sectors.length}`, sub: 'verificar comunicação', tint: '#c9a34a', bar: undefined },
            ].map((m, i) => (
              <div key={m.k} style={{ padding: '14px 18px', borderLeft: i === 0 ? 'none' : '1px solid #e8e0d0' }}>
                <div style={{ fontSize: 10.5, color: '#8a7f74', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 5, fontFamily: 'var(--font-jetbrains, ui-monospace)' }}>
                  {m.k}
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
                  <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 28, fontWeight: 500, letterSpacing: '-0.02em', color: m.tint, lineHeight: 1 }}>{m.v}</span>
                  {m.u && <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 11, color: '#8a7f74' }}>{m.u}</span>}
                </div>
                <div style={{ fontSize: 11, color: '#8a7f74', marginTop: 4 }}>{m.sub}</div>
                {m.bar !== undefined && (
                  <div style={{ marginTop: 8, position: 'relative', height: 4, background: '#e9e4dc', borderRadius: 999, overflow: 'hidden' }}>
                    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${m.bar * 100}%`, background: m.tint, borderRadius: 999 }} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* AI analysis card */}
      <FlowmeterAIAnalysis farmId={farmId} period={period} />

      {/* Sector table */}
      {data && (
        <FlowmeterSectorTable
          sectors={data.sectors}
          period={period}
          farmId={farmId}
          deviationMap={deviationMap}
          cropAverages={deviations?.crop_averages ?? {}}
        />
      )}
    </div>
  );
}
