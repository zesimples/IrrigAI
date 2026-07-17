// frontend/src/components/flowmeter/DeviationCell.tsx
import { DeviationMeter } from './DeviationMeter';

import { formatDecimal } from "@/lib/utils";

interface DeviationCellProps {
  deviation: number | null;
  status?: "normal" | "info" | "warning" | "insufficient_data" | "insufficient_peer_data";
  threshold?: number;
}

export function DeviationCell({ deviation, status, threshold = 5 }: DeviationCellProps) {
  if (deviation == null) {
    const label = status === "insufficient_data"
      ? "sem regas"
      : status === "insufficient_peer_data"
        ? "sem pares"
        : "—";
    return (
      <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
        <DeviationMeter pct={null} threshold={threshold} />
        <span style={{ fontFamily: 'var(--font-fraunces)', fontStyle: 'italic', fontSize: 12, color: '#8a7f74', minWidth: 54, textAlign: 'right' }}>{label}</span>
      </div>
    );
  }

  const abs = Math.abs(deviation);
  const isWarning = status === "warning";
  const isInfo = status === "info";
  const above = deviation > 0;
  const sign = abs < 0.05 ? "" : above ? "+" : "−";

  if (!isWarning) {
    const tone = isInfo ? '#c9a34a' : '#6b8f4e';
    return (
      <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
        <DeviationMeter pct={deviation} threshold={threshold} tone={tone} />
        <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 3, minWidth: 54, justifyContent: 'flex-end' }}>
          <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 15, fontWeight: 500, color: isInfo ? tone : '#5a5048', letterSpacing: '-0.01em' }}>
            {sign}{formatDecimal(abs, 1)}
          </span>
          <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 10, color: '#8a7f74' }}>%</span>
        </span>
      </div>
    );
  }

  const tone = above ? '#b84a2a' : '#c9a34a';
  const toneBg = above ? '#fbf4ee' : '#faf3e2';

  return (
    <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
      <DeviationMeter pct={deviation} threshold={threshold} tone={tone} />
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '4px 10px 4px 8px',
        background: toneBg,
        border: `1px solid ${tone}55`,
        borderRadius: 999,
        boxShadow: `0 1px 0 ${tone}11`,
        minWidth: 76,
        justifyContent: 'center',
      }}>
        <span style={{
          width: 0,
          height: 0,
          borderLeft: '4px solid transparent',
          borderRight: '4px solid transparent',
          ...(above
            ? { borderBottom: `6px solid ${tone}` }
            : { borderTop: `6px solid ${tone}` }),
        }} />
        <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 2 }}>
          <span style={{ fontFamily: 'var(--font-fraunces)', fontSize: 17, fontWeight: 600, color: tone, letterSpacing: '-0.015em', lineHeight: 1 }}>
            {sign}{formatDecimal(abs, 1)}
          </span>
          <span style={{ fontFamily: 'var(--font-jetbrains, ui-monospace)', fontSize: 10.5, color: tone, fontWeight: 600 }}>%</span>
        </span>
      </span>
    </div>
  );
}
