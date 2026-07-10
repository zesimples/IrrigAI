"use client";

import { useState } from "react";
import type { FlowmeterDeviationSector, FlowmeterSectorDashboard } from "@/types";
import { FlowmeterSparkline } from "./FlowmeterSparkline";
import { FlowmeterSectorDetail } from "./FlowmeterSectorDetail";
import { DeviationCell } from "./DeviationCell";
import { FlowmeterReferenceStatusDot } from "./FlowmeterReferenceStatusDot";
import type { FlowmeterReferenceOut } from "@/types";

interface Props {
  sector: FlowmeterSectorDashboard;
  period: "7d" | "30d" | "season";
  deviation: FlowmeterDeviationSector | null;
  odd?: boolean;
  reference?: FlowmeterReferenceOut | null;
  onRecompute?: (sectorId: string) => void;
}

function relativeDate(iso: string | null): string {
  if (!iso) return "";
  const daysAgo = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (daysAgo === 0) return "hoje";
  if (daysAgo === 1) return "ontem";
  return `há ${daysAgo} dias`;
}

export function FlowmeterSectorRow({ sector, period, deviation, reference, onRecompute, odd }: Props) {
  const [expanded, setExpanded] = useState(false);
  const hasData = sector.num_events > 0;
  const isAlarm = deviation?.status === "warning";
  const above = deviation?.direction === "above";

  return (
    <>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '92px 92px 106px 122px 116px 62px 1fr 110px 176px',
          padding: '12px 18px',
          gap: 8,
          alignItems: 'center',
          borderBottom: '1px solid #e8e0d0',
          background: odd ? 'rgba(0,0,0,0.015)' : 'transparent',
          opacity: hasData ? 1 : 0.65,
          position: 'relative',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded((v) => !v)}
        role="button"
        aria-expanded={expanded}
      >
        {/* Alarm wash — absolute, behind content */}
        {isAlarm && (
          <div style={{
            position: 'absolute',
            right: 0,
            top: 0,
            bottom: 0,
            width: 194,
            background: above ? 'rgba(184,74,42,0.045)' : 'rgba(201,163,74,0.06)',
            pointerEvents: 'none',
          }} />
        )}

        {/* Sector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            width: 7,
            height: 7,
            borderRadius: 999,
            background: hasData ? '#b84a2a' : '#8a7f74',
            flexShrink: 0,
          }} />
          <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 15, fontWeight: 600, color: '#2a2520', letterSpacing: '-0.01em' }}>
            {sector.sector_name}
          </span>
        </div>

        {/* Cultura */}
        <div style={{ fontFamily: 'var(--font-instrument)', fontStyle: 'italic', fontSize: 13, color: '#5a5048' }}>
          {sector.crop === 'almond' ? 'Amendoal' : 'Olival'}
        </div>

        {/* Último evento */}
        <div>
          {sector.last_irrigation ? (
            <span style={{ fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 12.5, color: '#b84a2a', fontWeight: 500 }}>
              {relativeDate(sector.last_irrigation)}
            </span>
          ) : (
            <span style={{ fontFamily: 'var(--font-fraunces)', fontStyle: 'italic', fontSize: 12.5, color: '#8a7f74' }}>
              sem dados
            </span>
          )}
        </div>

        {/* Última dotação */}
        <div>
          {sector.last_event_m3_ha != null ? (
            <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
              <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 16, fontWeight: 600, color: '#2a2520', letterSpacing: '-0.01em' }}>
                {sector.last_event_m3_ha.toFixed(1)}
              </span>
              <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 10, color: '#8a7f74' }}>m³/ha</span>
            </span>
          ) : (
            <span style={{ fontFamily: 'var(--font-fraunces)', fontStyle: 'italic', fontSize: 13, color: '#8a7f74' }}>—</span>
          )}
        </div>

        {/* Total período */}
        <div>
          {sector.total_m3_ha > 0 ? (
            <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
              <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 16, fontWeight: 500, color: '#2a2520', letterSpacing: '-0.01em' }}>
                {sector.total_m3_ha.toFixed(1)}
              </span>
              <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 10, color: '#8a7f74' }}>m³/ha</span>
            </span>
          ) : (
            <span style={{ fontFamily: 'var(--font-fraunces)', fontStyle: 'italic', fontSize: 13, color: '#8a7f74' }}>—</span>
          )}
        </div>

        {/* Nº regas */}
        <div style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 13, fontWeight: 500, color: sector.num_events > 0 ? '#2a2520' : '#8a7f74' }}>
          {sector.num_events}
        </div>

        {/* Gráfico 7d */}
        <div style={{ paddingRight: 24 }}>
          <FlowmeterSparkline data={sector.daily_breakdown.slice(-7)} />
        </div>

        {/* Caudal ref. */}
        <div style={{ paddingLeft: 8 }}>
          <FlowmeterReferenceStatusDot
            reference={reference}
            sectorId={sector.sector_id}
            onRecompute={onRecompute}
          />
        </div>

        {/* Desvio */}
        <div
          style={{
            paddingLeft: 14,
            marginLeft: 6,
            borderLeft: '1px solid #e8e0d0',
            alignSelf: 'stretch',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            position: 'relative',
            zIndex: 1,
          }}
        >
          <DeviationCell deviation={deviation?.deviation_pct ?? null} status={deviation?.status} />
        </div>
      </div>

      {expanded && <FlowmeterSectorDetail sectorId={sector.sector_id} period={period} />}
    </>
  );
}
