// frontend/src/components/flowmeter/DeviationMeter.tsx

interface DeviationMeterProps {
  pct: number | null;         // deviation percentage, null = no data
  threshold?: number;         // default 5
  tone?: string;              // bar color, default '#8a7f74'
}

export function DeviationMeter({ pct, threshold = 5, tone }: DeviationMeterProps) {
  const W = 56;
  const H = 14;
  const range = threshold * 3;
  const norm = pct == null ? 0 : Math.max(-1, Math.min(1, pct / range));
  const half = W / 2;
  const barW = Math.abs(norm) * half;
  const barLeft = norm >= 0 ? half : half - barW;
  const thresholdW = (threshold / range) * half;

  return (
    <div
      style={{
        position: 'relative',
        width: W,
        height: H,
        flexShrink: 0,
        background: '#ece5d5',
        borderRadius: 3,
        border: '1px solid #e8e0d0',
        overflow: 'hidden',
      }}
    >
      {/* tolerance band ±threshold */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: half - thresholdW,
          width: thresholdW * 2,
          background: 'rgba(107,143,78,0.12)',
        }}
      />
      {/* center tick */}
      <div
        style={{
          position: 'absolute',
          top: 1,
          bottom: 1,
          left: half - 0.5,
          width: 1,
          background: '#8a7f74',
          opacity: 0.5,
        }}
      />
      {/* value bar */}
      {pct != null && (
        <div
          style={{
            position: 'absolute',
            top: 3,
            bottom: 3,
            left: barLeft,
            width: Math.max(barW, 1.5),
            background: tone ?? '#8a7f74',
            borderRadius: 1,
          }}
        />
      )}
    </div>
  );
}
