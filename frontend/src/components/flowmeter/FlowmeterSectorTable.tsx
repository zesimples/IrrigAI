"use client";

import { useMemo, useState } from "react";
import type { FlowmeterSectorDashboard } from "@/types";
import { FlowmeterSectorRow } from "./FlowmeterSectorRow";

type SortKey = "name" | "last_irrigation" | "total" | "events";
type CropFilter = "all" | "almond" | "olive";

interface Props {
  sectors: FlowmeterSectorDashboard[];
  period: "7d" | "30d" | "season";
  farmId: string;
}

const ALARM_THRESHOLD = 5;

export function FlowmeterSectorTable({ sectors, period, farmId: _farmId }: Props) {
  const [cropFilter, setCropFilter] = useState<CropFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");

  // Per-culture averages of total_m3_ha (only sectors with irrigation events)
  const cropAverages = useMemo(() => {
    const acc: Record<string, number[]> = {};
    for (const s of sectors) {
      if (s.num_events > 0 && s.total_m3_ha > 0) {
        (acc[s.crop] ??= []).push(s.total_m3_ha);
      }
    }
    const result: Record<string, number> = {};
    for (const [crop, vals] of Object.entries(acc)) {
      result[crop] = vals.reduce((a, b) => a + b, 0) / vals.length;
    }
    return result;
  }, [sectors]);

  // Deviation percentage per sector (null if no data)
  const deviationMap = useMemo(() => {
    const map: Record<string, number | null> = {};
    for (const s of sectors) {
      if (s.num_events === 0 || s.total_m3_ha === 0) {
        map[s.sector_id] = null;
      } else {
        const avg = cropAverages[s.crop];
        map[s.sector_id] = avg != null && avg > 0
          ? ((s.total_m3_ha - avg) / avg) * 100
          : null;
      }
    }
    return map;
  }, [sectors, cropAverages]);

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

  // Alarm counts per group (for chip)
  function alarmCount(list: FlowmeterSectorDashboard[]) {
    return list.filter((s) => {
      const d = deviationMap[s.sector_id];
      return d != null && Math.abs(d) > ALARM_THRESHOLD;
    }).length;
  }

  // Group average label
  function groupAvg(list: FlowmeterSectorDashboard[], crop: string) {
    const avg = cropAverages[crop];
    if (avg == null) return null;
    return avg.toFixed(1);
  }

  // Group total
  function groupTotal(list: FlowmeterSectorDashboard[]) {
    return list.reduce((s, r) => s + r.total_m3_ha, 0).toFixed(1);
  }

  const noData = sectors.filter((s) => s.num_events === 0).length;

  const GRID = "92px 92px 106px 122px 116px 62px 1fr 176px";

  function GroupHeader({ name, list, crop }: { name: string; list: FlowmeterSectorDashboard[]; crop: string }) {
    const alarms = alarmCount(list);
    const avg = groupAvg(list, crop);
    const total = groupTotal(list);
    return (
      <div style={{
        padding: '10px 18px',
        background: '#fbf8f1',
        borderBottom: '1px solid #e8e0d0',
        display: 'flex',
        alignItems: 'baseline',
        gap: 10,
        flexWrap: 'wrap',
      }}>
        <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 14, fontWeight: 600, color: '#2a2520', letterSpacing: '-0.005em' }}>
          {name}
        </span>
        <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 10, color: '#8a7f74', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          {list.length} sectores
        </span>
        <div style={{ flex: 1, height: 1, background: '#e8e0d0', marginLeft: 6, alignSelf: 'center' }} />
        <span style={{ fontFamily: 'var(--font-fraunces)', fontStyle: 'italic', fontSize: 12, color: '#8a7f74' }}>
          total {total} m³/ha
        </span>
        {avg && (
          <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 10, color: '#8a7f74', letterSpacing: '0.06em' }}>
            · média/sector {avg} m³
          </span>
        )}
        {alarms > 0 && (
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '3px 9px',
            background: '#fbf4ee',
            border: '1px solid rgba(184,74,42,0.27)',
            borderRadius: 999,
            fontFamily: 'var(--font-dm-sans, system-ui)',
            fontSize: 11,
            fontWeight: 600,
            color: '#b84a2a',
          }}>
            <span style={{ width: 5, height: 5, borderRadius: 999, background: '#b84a2a', flexShrink: 0 }} />
            {alarms} {alarms === 1 ? 'alarme' : 'alarmes'} de desvio
          </span>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* Editorial filter bar */}
      <div style={{
        padding: '20px 44px 14px',
        display: 'flex',
        alignItems: 'center',
        gap: 28,
        flexWrap: 'wrap',
      }}>
        {/* Cultura filter */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
          <span style={{
            fontFamily: 'var(--font-jetbrains, ui-monospace)',
            fontSize: 10,
            color: '#8a7f74',
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
          }}>Cultura</span>
          <div style={{ display: 'inline-flex', gap: 6 }}>
            {(['all', 'almond', 'olive'] as const).map((c) => {
              const active = cropFilter === c;
              const label = c === 'all' ? 'Todos' : c === 'almond' ? 'Amendoal' : 'Olival';
              return (
                <button
                  key={c}
                  onClick={() => setCropFilter(c)}
                  style={{
                    cursor: 'pointer',
                    padding: '4px 11px',
                    borderRadius: 999,
                    fontFamily: 'var(--font-fraunces)',
                    fontSize: 13,
                    fontWeight: active ? 600 : 400,
                    letterSpacing: '-0.005em',
                    background: active ? '#2a2520' : 'transparent',
                    color: active ? '#f5f0e6' : '#5a5048',
                    border: active ? 'none' : '1px solid #dcd3c2',
                  }}
                >{label}</button>
              );
            })}
          </div>
        </div>

        <div style={{ flex: 1 }} />

        {/* Sort */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 11, color: '#8a7f74', letterSpacing: '0.04em' }}>
          <span style={{ textTransform: 'uppercase', letterSpacing: '0.14em', fontSize: 10 }}>Ordenar</span>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            style={{
              background: '#f5f0e6',
              border: '1px solid #dcd3c2',
              borderRadius: 6,
              padding: '5px 28px 5px 10px',
              fontFamily: 'var(--font-dm-sans, system-ui)',
              fontSize: 12.5,
              color: '#2a2520',
              appearance: 'none',
            }}
          >
            <option value="name">Setor</option>
            <option value="total">Maior consumo</option>
            <option value="last_irrigation">Última rega</option>
            <option value="events">Nº de regas</option>
          </select>
        </div>
      </div>

      {/* Table container */}
      <div style={{ padding: '0 44px 36px' }}>
        <div style={{
          border: '1px solid #dcd3c2',
          borderRadius: 10,
          overflow: 'hidden',
          background: '#fbf8f1',
        }}>
          {/* Column header */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: GRID,
            padding: '11px 18px',
            background: '#ece5d5',
            borderBottom: '1px solid #dcd3c2',
            fontFamily: 'var(--font-jetbrains, ui-monospace)',
            fontSize: 9.5,
            color: '#8a7f74',
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            alignItems: 'center',
          }}>
            <div>Sector</div>
            <div>Cultura</div>
            <div>Último evento</div>
            <div>Última dotação</div>
            <div>Total período</div>
            <div>N.º regas</div>
            <div>Gráfico 7d</div>
            {/* Deviation column header — alarm rail */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 7,
              paddingLeft: 14,
              marginLeft: 6,
              borderLeft: '1px solid #dcd3c2',
              alignSelf: 'stretch',
            }}>
              <span style={{ width: 5, height: 5, borderRadius: 999, background: '#b84a2a', flexShrink: 0 }} />
              <span style={{ color: '#2a2520', fontSize: 10.5, fontWeight: 600, letterSpacing: '0.16em' }}>Desvio</span>
              <span
                title="Alarme se o desvio face à média da cultura ultrapassar ±5%."
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 13,
                  height: 13,
                  borderRadius: 999,
                  border: '1px solid #8a7f74',
                  fontSize: 9,
                  color: '#8a7f74',
                  cursor: 'help',
                  fontFamily: 'var(--font-fraunces)',
                  fontStyle: 'italic',
                  letterSpacing: 0,
                  textTransform: 'none',
                }}
              >i</span>
            </div>
          </div>

          {/* Amendoal group */}
          {almonds.length > 0 && cropFilter !== 'olive' && (
            <>
              <GroupHeader name="Amendoal" list={almonds} crop="almond" />
              {almonds.map((s, i) => (
                <FlowmeterSectorRow
                  key={s.sector_id}
                  sector={s}
                  period={period}
                  deviation={deviationMap[s.sector_id] ?? null}
                  odd={i % 2 === 1}
                />
              ))}
            </>
          )}

          {/* Olival group */}
          {olives.length > 0 && cropFilter !== 'almond' && (
            <>
              <GroupHeader name="Olival" list={olives} crop="olive" />
              {olives.map((s, i) => (
                <FlowmeterSectorRow
                  key={s.sector_id}
                  sector={s}
                  period={period}
                  deviation={deviationMap[s.sector_id] ?? null}
                  odd={i % 2 === 1}
                />
              ))}
            </>
          )}
        </div>

        {/* Below-table note */}
        {noData > 0 && (
          <div style={{
            marginTop: 16,
            fontFamily: 'var(--font-fraunces)',
            fontStyle: 'italic',
            fontSize: 13,
            color: '#8a7f74',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 10,
          }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
              <span>
                <span style={{ color: '#c9a34a', marginRight: 6 }}>●</span>
                {noData} sector{noData !== 1 ? 'es' : ''} sem leituras nos últimos 7 dias — pode haver problema de comunicação.
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontStyle: 'normal', fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 11.5, color: '#5a5048' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 999, background: '#b84a2a' }} />
                  <span>acima +5%</span>
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 999, background: '#c9a34a' }} />
                  <span>abaixo −5%</span>
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 999, background: '#6b8f4e' }} />
                  <span>dentro ±5%</span>
                </span>
              </span>
            </span>
            <a style={{ color: '#5a5048', textDecoration: 'none', fontStyle: 'normal', fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 13 }}>
              Diagnóstico de sondas ↗
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
